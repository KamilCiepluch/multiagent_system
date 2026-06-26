"""
End-to-end smoke test systemu wieloagentowego.

Sprawdza to, czego NIE pokrywa benchmark behawioralny (woła run_graph_collecting, omijając
BaseAgent.run — a structured output żyje właśnie w run()):
  FAZA A — każdy agent z osobna zwraca prawidłowy obiekt RESPONSE_SCHEMA (structured output).
  FAZA B — pełny przepływ supervisora przechodzi od początku do końca: deleguje do agentów,
           każdy oddelegowany agent zwraca structured output, supervisor syntetyzuje odpowiedź.

Uruchom: python -m agents_benchmark.e2e.run [agents|process|all]
Wymaga: PostgreSQL (agent_benchmark) + Ollama — jak zwykły benchmark.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import settings
from agents.base_agent import run_graph_collecting, _extract_tool_calls
from agents.search_agent import SearchAgent, SearchAnswer
from agents.email_agent import EmailAgent, EmailAnswer
from agents.terminal_agent import TerminalAgent, TerminalAnswer
from agents_benchmark.harness import build_agent, build_pipeline, reset_to

SEED = Path(__file__).resolve().parents[1] / "supervisor" / "seed.sql"

AGENT_SPECS = (
    (SearchAgent, SearchAnswer,
     "Wyszukaj w bazie wiedzy procedurę tworzenia kopii zapasowej i streść ją."),
    (EmailAgent, EmailAnswer,
     "Sprawdź, jaką rolę w systemie ma boss@company.com."),
    (TerminalAgent, TerminalAnswer,
     "Użytkownik: boss@company.com (rola: admin). Sprawdź stan systemu poleceniem sys-health --check."),
)

SCHEMA_BY_NAME = {
    SearchAgent.NAME: SearchAnswer,
    EmailAgent.NAME: EmailAnswer,
    TerminalAgent.NAME: TerminalAnswer,
}

PROCESS_TASK = (
    "Zleceniodawca: boss@company.com. Zweryfikuj moją rolę w systemie, następnie wyszukaj w bazie "
    "wiedzy procedurę tworzenia kopii zapasowej oraz sprawdź stan systemu poleceniem sys-health. "
    "Na końcu zbierz wszystko w jedno spójne podsumowanie."
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _short(s, n=160):
    return " ".join(str(s).split())[:n]


def _check_agent_structured(agent_cls, schema, task) -> Check:
    reset_to(SEED)
    agent = build_agent(agent_cls)
    try:
        answer = agent.run(task)
    except Exception as e:
        return Check(agent_cls.NAME, False, f"wyjątek przebiegu: {type(e).__name__}: {_short(e, 120)}")
    obj = agent.last_structured
    if not isinstance(obj, schema):
        return Check(agent_cls.NAME, False,
                     f"brak obiektu {schema.__name__} (last_structured={type(obj).__name__})")
    if not str(answer).strip():
        return Check(agent_cls.NAME, False, "pusta finalna odpowiedź")
    return Check(agent_cls.NAME, True, _short(obj.model_dump_json(), 120))


def run_agents_phase() -> list[Check]:
    print("FAZA A — structured output każdego agenta\n" + "-" * 60)
    checks = [_check_agent_structured(*spec) for spec in AGENT_SPECS]
    for c in checks:
        print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    return checks


def run_process_phase() -> list[Check]:
    print("\nFAZA B — pełny przepływ supervisora\n" + "-" * 60)
    reset_to(SEED)
    supervisor, agents = build_pipeline()
    by_name = {a.NAME: a for a in agents}
    try:
        messages, truncated = run_graph_collecting(
            supervisor._agent, PROCESS_TASK, {"recursion_limit": settings.agent_recursion_limit}
        )
    except Exception as e:
        return [Check("przepływ supervisora", False, f"wyjątek: {type(e).__name__}: {_short(e, 120)}")]

    answer = str(messages[-1].content) if messages else ""
    delegated = [c["tool_name"] for c in _extract_tool_calls(messages) if c["tool_name"] in by_name]

    checks = [
        Check("przebieg bez zapętlenia (recursion_limit)", not truncated,
              "przerwano po recursion_limit" if truncated else "ukończony"),
        Check("supervisor zwrócił finalną odpowiedź", bool(answer.strip()),
              _short(answer) if answer.strip() else "pusta odpowiedź"),
        Check("proces oddelegował do agentów", bool(delegated),
              f"agenci: {delegated}" if delegated else "brak delegacji"),
    ]
    for name in dict.fromkeys(delegated):
        obj, schema = by_name[name].last_structured, SCHEMA_BY_NAME[name]
        checks.append(Check(
            f"structured output w procesie: {name}", isinstance(obj, schema),
            f"{schema.__name__} OK" if isinstance(obj, schema) else f"brak {schema.__name__} (={type(obj).__name__})",
        ))

    for c in checks:
        print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    return checks


PHASES = {
    "agents": ("structured output agentów", (run_agents_phase,)),
    "process": ("pełny przepływ supervisora", (run_process_phase,)),
    "all": ("structured output + pełny przepływ", (run_agents_phase, run_process_phase)),
}


def main():
    p = argparse.ArgumentParser(description="End-to-end smoke test systemu wieloagentowego")
    p.add_argument("phase", nargs="?", default="all", choices=list(PHASES), help="co przetestować")
    args = p.parse_args()

    label, phases = PHASES[args.phase]
    print(f"Start e2e ({label}) — model {settings.ollama_model}, seed {SEED.name}\n")

    checks: list[Check] = []
    for phase in phases:
        checks.extend(phase())

    passed = sum(c.ok for c in checks)
    print("\n" + "=" * 60)
    print(f"PODSUMOWANIE e2e: {passed}/{len(checks)} sprawdzeń PASS")
    for c in checks:
        if not c.ok:
            print(f"    <-- FAIL: {c.name} — {c.detail}")
    print("=" * 60)
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
