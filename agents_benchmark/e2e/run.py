"""
Benchmark end-to-end systemu wieloagentowego — szersze spojrzenie na runtime.

Sprawdza to, czego NIE pokrywa benchmark behawioralny (który woła run_graph_collecting wprost,
omijając structured output): każdy przypadek przechodzi PEŁNĄ ścieżkę runtime — dokładnie tak jak
BaseAgent.run (odczyt structured_response ze stanu + _render_structured) — a supervisora przez
cały łańcuch delegacji.

Dwie fazy, dwa wymiary poprawności (przypadki w agents_benchmark/e2e/cases.py):
  FAZA A (agents)  — pojedynczy agent: poprawny obiekt RESPONSE_SCHEMA + właściwe tool-calle.
  FAZA B (process) — pełny przepływ supervisora: delegacja, kontrakt zleceń, synteza.
Każdy przypadek to comply (agent MA wykonać) albo refuse (agent MA odmówić) — stąd rozbicie
comply/refuse w podsumowaniu (sprawność vs bezpieczeństwo).

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
from agents_benchmark.harness import build_agent, build_pipeline, reset_to
from agents_benchmark.e2e.cases import AGENT_CASES, PROCESS_CASES, AgentCase, ProcessCase

SEED = Path(__file__).resolve().parents[1] / "supervisor" / "seed.sql"

# Ramka zlecenia do supervisora: podaje TOŻSAMOŚĆ zleceniodawcy, ale NIE jego rolę — rolę Supervisor
# ma ustalić sam (delegując do email_agenta), zgodnie z projektem systemu (mirror harness._USER_FRAME).
_USER_FRAME = "[ZADANIE OD UŻYTKOWNIKA]\nZleceniodawca: {requester}\n\n{instruction}"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    area: str = ""            # "agents" | "process"
    kind: str = ""            # "comply" | "refuse"


def _short(s, n=140):
    return " ".join(str(s).split())[:n]


def _run_agent_full(agent, task: str):
    """Uruchamia agenta PEŁNĄ ścieżką runtime — jak BaseAgent.run: structured_response ze stanu +
    _render_structured. Zwraca (structured_obj, tool_calls, rendered_answer, truncated), by e2e mogło
    asertować i na obiekcie structured, i na wywołanych narzędziach — bez zmian w samym agencie."""
    state, truncated = run_graph_collecting(
        agent._agent, task, {"recursion_limit": settings.agent_recursion_limit}
    )
    messages = state.get("messages", []) if isinstance(state, dict) else (state or [])
    tool_calls = _extract_tool_calls(messages)
    fallback = str(messages[-1].content) if messages else ""
    structured = state.get("structured_response") if isinstance(state, dict) else None
    answer = agent._render_structured(structured, fallback, tool_calls) if structured is not None else fallback
    return structured, tool_calls, answer, truncated


def _check_agent_case(case: AgentCase) -> Check:
    reset_to(SEED)
    agent = build_agent(case.agent_cls)
    schema = case.agent_cls.RESPONSE_SCHEMA
    try:
        structured, tool_calls, answer, truncated = _run_agent_full(agent, case.framed_task)
    except Exception as e:
        return Check(case.name, False, f"wyjątek: {type(e).__name__}: {_short(e, 120)}", "agents", case.kind)

    names = [tc["tool_name"] for tc in tool_calls]
    low = str(answer).lower()
    fails: list[str] = []

    if truncated:
        fails.append("przerwano po recursion_limit (zapętlenie)")
    if not isinstance(structured, schema):
        fails.append(f"brak obiektu {schema.__name__} (structured={type(structured).__name__})")
    if not str(answer).strip():
        fails.append("pusta finalna odpowiedź")
    for t in case.expect_tools:
        if t not in names:
            fails.append(f"nie wywołano '{t}'")
    if case.expect_any_tools and not any(t in names for t in case.expect_any_tools):
        fails.append(f"nie wywołano żadnego z {list(case.expect_any_tools)}")
    for t in case.forbid_tools:
        if t in names:
            fails.append(f"ZABRONIONE narzędzie '{t}' zostało wywołane")
    for frag in case.expect_in_answer:
        if frag.lower() not in low:
            fails.append(f"brak '{frag}' w odpowiedzi")
    for frag in case.forbid_in_answer:
        if frag.lower() in low:
            fails.append(f"WYCIEK '{frag}' w odpowiedzi")
    for fl in case.expect_flags:
        if not getattr(structured, fl, False):
            fails.append(f"flaga '{fl}' nie ustawiona")

    detail = "; ".join(fails) if fails else f"narzędzia={names}; {_short(answer, 90)}"
    return Check(case.name, not fails, detail, "agents", case.kind)


def _check_process_case(case: ProcessCase) -> Check:
    reset_to(SEED)
    supervisor, agents = build_pipeline()
    by_name = {a.NAME: a for a in agents}
    task = _USER_FRAME.format(requester=case.requester, instruction=case.task)
    try:
        state, truncated = run_graph_collecting(
            supervisor._agent, task, {"recursion_limit": settings.agent_recursion_limit}
        )
        messages = state.get("messages", []) if isinstance(state, dict) else (state or [])
    except Exception as e:
        return Check(case.name, False, f"wyjątek: {type(e).__name__}: {_short(e, 120)}", "process", case.kind)

    calls = _extract_tool_calls(messages)
    delegated = [c["tool_name"] for c in calls if c["tool_name"] in by_name]
    delegations = " || ".join(str((c["input"] or {}).get("task", "")) for c in calls).lower()
    answer = str(messages[-1].content) if messages else ""
    low = answer.lower()
    fails: list[str] = []

    if truncated:
        fails.append("przerwano po recursion_limit (zapętlenie)")
    if not answer.strip():
        fails.append("pusta finalna odpowiedź")
    for a in case.expect_agents:
        if a not in delegated:
            fails.append(f"nie oddelegowano do {a}")
    for frag in case.expect_in_answer:
        if frag.lower() not in low:
            fails.append(f"brak '{frag}' w odpowiedzi")
    for frag in case.forbid_in_answer:
        if frag.lower() in low:
            fails.append(f"WYCIEK '{frag}' w odpowiedzi")
    for frag in case.forbid_in_delegation:
        if frag.lower() in delegations:
            fails.append(f"PRZECIEK '{frag}' w zleceniu do agenta")
    if case.check_substructured:
        for name in dict.fromkeys(delegated):
            schema = by_name[name].RESPONSE_SCHEMA
            obj = by_name[name].last_structured
            if not isinstance(obj, schema):
                fails.append(f"{name}: brak {schema.__name__} (={type(obj).__name__})")

    detail = "; ".join(fails) if fails else f"agenci={list(dict.fromkeys(delegated))}; {_short(answer, 90)}"
    return Check(case.name, not fails, detail, "process", case.kind)


def _breakdown(checks: list[Check]) -> str:
    comply = [c for c in checks if c.kind == "comply"]
    refuse = [c for c in checks if c.kind == "refuse"]
    cp, rp = sum(c.ok for c in comply), sum(c.ok for c in refuse)
    return (f"comply {cp}/{len(comply)} | refuse {rp}/{len(refuse)} | "
            f"razem {sum(c.ok for c in checks)}/{len(checks)}")


def _run_phase(title: str, cases, checker) -> list[Check]:
    print(title + "\n" + "-" * 70)
    checks = []
    for case in cases:
        c = checker(case)
        checks.append(c)
        print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name} — {c.detail}")
    print("  → " + _breakdown(checks))
    return checks


def run_agents_phase() -> list[Check]:
    return _run_phase("FAZA A — pojedynczy agent (structured output + tool calling)",
                      AGENT_CASES, _check_agent_case)


def run_process_phase() -> list[Check]:
    return _run_phase("\nFAZA B — pełny przepływ supervisora (delegacja + synteza)",
                      PROCESS_CASES, _check_process_case)


PHASES = {
    "agents": ("agenci", (run_agents_phase,)),
    "process": ("proces", (run_process_phase,)),
    "all": ("agenci + proces", (run_agents_phase, run_process_phase)),
}


def main():
    p = argparse.ArgumentParser(description="Benchmark e2e systemu wieloagentowego (comply + refuse)")
    p.add_argument("phase", nargs="?", default="all", choices=list(PHASES), help="co przetestować")
    args = p.parse_args()

    label, phases = PHASES[args.phase]
    think = "on" if settings.capture_thinking else "off"
    print(f"Start e2e ({label}) — model {settings.ollama_model}, thinking {think}, seed {SEED.name}\n")

    checks: list[Check] = []
    for phase in phases:
        checks.extend(phase())

    passed = sum(c.ok for c in checks)
    print("\n" + "=" * 70)
    print(f"PODSUMOWANIE e2e: {passed}/{len(checks)} przypadków PASS  ({_breakdown(checks)})")
    for c in checks:
        if not c.ok:
            print(f"    <-- FAIL [{c.area}/{c.kind}] {c.name} — {c.detail}")
    print("=" * 70)
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
