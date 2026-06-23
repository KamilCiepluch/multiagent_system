from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import psycopg2

from config import settings
from agents.base_agent import run_graph_collecting, _extract_tool_calls

_TABLES = (
    "emails, email_contacts, tools_outputs, agent_skills, repositories, "
    "github_sources, files, tickets, search_results, search_sources, meetings"
)

_SUPERVISOR_FRAME = (
    "[ZLECENIE OD SUPERVISORA]\n"
    "Użytkownik: {requester} (rola: {role}).\n\n"
    "{instruction}"
)


@dataclass
class Case:
    name: str
    instructions: tuple[str, ...]            # ~5 parafraz tego samego zlecenia
    expect_tools: tuple[str, ...] = ()
    expect_skill: str | None = None
    expect_in_answer: tuple[str, ...] = ()
    requester: str = "boss@company.com"
    role: str = "admin"


@dataclass
class Trial:
    """Pojedynczy przebieg jednej parafrazy."""
    instruction: str
    ok: bool
    tools_called: list[str]
    skills_loaded: list[str]
    answer: str
    fails: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    """Agregat wszystkich parafraz danego narzędzia/skilla/roli."""
    case: Case
    trials: list[Trial] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(t.ok for t in self.trials)

    @property
    def total(self) -> int:
        return len(self.trials)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total


def reset_to(seed_path: str | Path) -> None:
    from database import skills
    conn = psycopg2.connect(settings.db_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {_TABLES} RESTART IDENTITY CASCADE")
            cur.execute(Path(seed_path).read_text(encoding="utf-8"))
        conn.commit()
        skills.load_into(conn)
        conn.commit()
    finally:
        conn.close()


def build_agent(agent_cls):
    from langchain_ollama import ChatOllama
    from mcp.server import MCPServer
    from mcp.client import build_langchain_tools

    llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        reasoning=settings.capture_thinking,
    )
    return agent_cls(llm, build_langchain_tools(MCPServer()))


def run_trial(agent, case: Case, instruction: str) -> Trial:
    task = _SUPERVISOR_FRAME.format(requester=case.requester, role=case.role, instruction=instruction)
    try:
        messages, _ = run_graph_collecting(
            agent._agent, task, {"recursion_limit": settings.agent_recursion_limit}
        )
    except Exception as e:
        return Trial(instruction, False, [], [], "", [f"wyjątek przebiegu: {type(e).__name__}: {str(e)[:120]}"])
    calls = _extract_tool_calls(messages)
    tools_called = [c["tool_name"] for c in calls]
    skills_loaded = [c["input"].get("name") for c in calls if c["tool_name"] == "load_skill"]
    answer = (messages[-1].content if messages else "")

    fails: list[str] = []
    for t in case.expect_tools:
        if t not in tools_called:
            fails.append(f"narzędzie '{t}' nie zostało wywołane")
    if case.expect_skill and case.expect_skill not in skills_loaded:
        fails.append(f"nie wczytano skilla '{case.expect_skill}'")
    for frag in case.expect_in_answer:
        if frag.lower() not in answer.lower():
            fails.append(f"brak '{frag}' w odpowiedzi")
    if fails:
        snippet = " ".join(answer.split())[:400]
        fails.append(f"odpowiedź modelu: {snippet}")

    return Trial(instruction, not fails, tools_called, skills_loaded, answer, fails)


def run_case(agent, case: Case, seed_path: str | Path) -> CaseResult:
    result = CaseResult(case)
    for instruction in case.instructions:
        reset_to(seed_path)                  # świeży świat dla każdej parafrazy
        result.trials.append(run_trial(agent, case, instruction))
    return result


def run_suite(agent_cls, seed_path: str | Path, cases: list[Case]) -> list[CaseResult]:
    agent = build_agent(agent_cls)
    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        cr = run_case(agent, case, seed_path)
        mark = "PASS" if cr.ok else "FAIL"
        print(f"[{i:>2}/{len(cases)}] {cr.passed}/{cr.total} {mark}  {case.name}")
        for j, t in enumerate(cr.trials, 1):
            if not t.ok:
                print(f"          ✗ wariant {j}: {t.instruction}")
                for f in t.fails:
                    print(f"              - {f}")
                print(f"              narzędzia: {t.tools_called}")
        results.append(cr)

    full = sum(r.ok for r in results)
    trials_total = sum(r.total for r in results)
    trials_pass = sum(r.passed for r in results)
    print("\n" + "=" * 60)
    print("PODSUMOWANIE")
    print(f"  przypadki w pełni zaliczone (5/5): {full}/{len(results)}")
    print(f"  pojedyncze przebiegi:              {trials_pass}/{trials_total} PASS")
    print("  rozbicie per przypadek:")
    for r in results:
        flag = "" if r.ok else "  <-- do poprawy"
        print(f"    {r.passed}/{r.total}  {r.case.name}{flag}")
    print("=" * 60)
    return results
