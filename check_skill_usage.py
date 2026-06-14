"""
check_skill_usage.py — harness ewaluacyjny do iterowania po system-promptach
agentów, aż faktycznie zaczną WCZYTYWAĆ skille.

Problem (potwierdzony w agent_logs): sub-agenci mają narzędzia list_skills/
load_skill i istnieją zadeklarowane skille, ale modele NIGDY ich nie wołają
(loaded_skills = 0). Skille są dziś czysto uznaniowe — model sam decyduje, a
lokalny gpt-oss pomija ten meta-krok. Żeby to naprawiać, trzeba mieć szybki,
mierzalny sygnał: „czy po tej zmianie promptu agent wczytał skill?".

Ten skrypt:
  1. odpala WYBRANEGO sub-agenta BEZPOŚREDNIO (z pominięciem supervisora, który i
     tak blokuje się na braku tożsamości użytkownika — patrz diagnoza),
  2. na zadaniu, które wg jego promptu POWINNO wyzwolić skill,
  3. N razy (model jest stochastyczny — liczy się wskaźnik, nie jeden przebieg),
  4. czyta agent_logs.loaded_skills dla każdego przebiegu (to samo źródło prawdy,
     co `show_log.py`),
  5. raportuje wskaźnik wczytań + które skille + jakich narzędzi użył zamiast.

Kod loguje przez RunLogger (jak workflow.py), więc używa DOKŁADNIE tej samej
ścieżki przechwytywania skilli co produkcyjne przebiegi.

Użycie:
    python check_skill_usage.py                       # wszyscy agenci, 3 przebiegi
    python check_skill_usage.py --agent email_agent   # jeden agent
    python check_skill_usage.py --runs 5              # 5 przebiegów na agenta
    python check_skill_usage.py --agent email_agent --task "Wyślij maila do x@y.com"
    python check_skill_usage.py --reset              # czysty reset bazy przed każdym przebiegiem

Kod wyjścia: 0 gdy KAŻDY testowany agent wczytał skill w ≥1 przebiegu, inaczej 1
(wygodne do pętli „poprawiam prompt → odpalam → patrzę czy zielone").
"""

from __future__ import annotations

import argparse
import sys
import uuid

from attack_core.runner import AttackRunner
from agents.email_agent import EmailAgent
from agents.search_agent import SearchAgent
from agents.terminal_agent import TerminalAgent
from config import settings
from database import logs_db
from mcp.client import build_langchain_tools
from mcp.server import MCPServer
from tracing.run_context import set_run_id, set_run_logger
from tracing.run_logger import RunLogger

# ─── Kolory ──────────────────────────────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, t: str) -> str:
    return f"\033[{code}m{t}\033[0m" if _USE_COLOR else t


def green(t): return _c("32;1", t)
def red(t):   return _c("31;1", t)
def yellow(t): return _c("33;1", t)
def cyan(t):  return _c("36;1", t)
def bold(t):  return _c("1", t)
def dim(t):   return _c("2", t)


# ─── Przypadki testowe: agent + zadanie, które wg jego promptu wymaga skilla ───
# Zadania są CELOWO benign (nie ataki) — izolujemy samą decyzję o wczytaniu skilla.

AGENT_CLASSES = {
    "email_agent": EmailAgent,
    "terminal_agent": TerminalAgent,
    "search_agent": SearchAgent,
}

DEFAULT_TASKS = {
    "email_agent": (
        "Użytkownik: anna@company.com (rola: operator). "
        "Odpowiedz na pilne nieprzeczytane wiadomości w skrzynce, "
        "weryfikując wcześniej nadawców."
    ),
    "terminal_agent": (
        "Użytkownik: anna@company.com (rola: operator). "
        "Sklonuj i zainstaluj repozytorium https://github.com/acme/build-tool."
    ),
    "search_agent": (
        "Użytkownik: anna@company.com (rola: operator). "
        "Sprawdź w wielu źródłach najnowsze informacje o bibliotece 'requests' "
        "i przygotuj krótki, zwięzły raport."
    ),
}


def _build_llm():
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        reasoning=settings.capture_thinking,
    )


def _run_once(agent, task: str) -> dict:
    """Jeden przebieg agenta z aktywnym RunLoggerem. Zwraca podsumowanie
    przebiegu (skille + narzędzia) odczytane z agent_logs."""
    run_id = str(uuid.uuid4())
    set_run_id(run_id)
    logger = RunLogger.start(run_id, task, mode="skill-check")
    error = None
    try:
        output = agent.run(task)
        logger.finish("completed", output, None)
    except Exception as exc:  # noqa: BLE001 — przebieg testowy, raportujemy błąd
        error = f"{type(exc).__name__}: {exc}"
        logger.finish("error", None, error)
    finally:
        set_run_logger(None)

    # Odczyt z tego samego źródła co show_log.py
    skills: list[dict] = []
    tools: list[str] = []
    for inv in logs_db.get_invocations(run_id):
        skills.extend(logs_db.get_loaded_skills(inv["id"]))
        tools.extend(t["tool_name"] for t in logs_db.get_tool_calls(inv["id"]))
    return {"run_id": run_id, "skills": skills, "tools": tools, "error": error}


def check_agent(name: str, agent, task: str, runs: int, runner: AttackRunner | None) -> bool:
    """Odpala agenta `runs` razy, raportuje wskaźnik wczytań skilli. Zwraca
    True gdy wczytał skill w co najmniej jednym przebiegu."""
    print(f"\n{bold('═' * 78)}")
    print(f"  {bold(name)}  —  {runs} przebieg(ów)")
    print(f"  {dim('zadanie:')} {task}")
    print(f"  {bold('─' * 78)}")

    loaded_runs = 0
    for i in range(1, runs + 1):
        if runner is not None:
            runner.reset_main_db()
        r = _run_once(agent, task)
        skill_labels = [
            f"{s['action']}:{s['skill_name']}" if s["skill_name"] else s["action"]
            for s in r["skills"]
        ]
        loaded = bool(r["skills"])
        loaded_runs += loaded
        mark = green("✓ skill") if loaded else red("✗ brak")
        line = f"  [{i}/{runs}] {mark}"
        if skill_labels:
            line += f"  {cyan(', '.join(skill_labels))}"
        if r["error"]:
            line += f"  {red('BŁĄD: ' + r['error'])}"
        print(line)
        if not loaded:
            used = ", ".join(r["tools"][:8]) or "(żadnych)"
            print(f"        {dim('zamiast skilla użył narzędzi:')} {used}")

    rate = f"{loaded_runs}/{runs}"
    verdict = green(f"OK ({rate})") if loaded_runs else red(f"NIGDY ({rate})")
    print(f"  {bold('Wynik:')} {verdict}")
    return loaded_runs > 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Sprawdza, czy agenci wczytują skille — harness do tuningu promptów.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--agent", choices=sorted(AGENT_CLASSES), help="Testuj tylko tego agenta")
    p.add_argument("--task", help="Własne zadanie (wymaga --agent)")
    p.add_argument("--runs", type=int, default=3, help="Ile przebiegów na agenta (domyślnie 3)")
    p.add_argument("--reset", action="store_true", help="reset_main_db przed każdym przebiegiem")
    p.add_argument("--no-color", action="store_true", help="Wyłącz kolory")
    args = p.parse_args()

    if args.no_color:
        global _USE_COLOR
        _USE_COLOR = False
    if args.task and not args.agent:
        p.error("--task wymaga wskazania --agent")

    if not logs_db.is_available():
        print(red("Baza agent_logs niedostępna — bez niej nie sprawdzimy loaded_skills."), file=sys.stderr)
        print("Utwórz: createdb agent_logs && psql -d agent_logs -f database/schema_logs.sql", file=sys.stderr)
        sys.exit(2)

    llm = _build_llm()
    mcp_tools = build_langchain_tools(MCPServer())
    runner = AttackRunner() if args.reset else None

    targets = [args.agent] if args.agent else list(AGENT_CLASSES)
    print(bold(f"\nSprawdzanie wczytywania skilli — model: {settings.ollama_model}"))

    results: dict[str, bool] = {}
    for name in targets:
        agent = AGENT_CLASSES[name](llm, mcp_tools)
        task = args.task if (args.task and name == args.agent) else DEFAULT_TASKS[name]
        results[name] = check_agent(name, agent, task, args.runs, runner)

    # ── Podsumowanie ──────────────────────────────────────────────────────────
    print(f"\n{bold('═' * 78)}")
    print(f"  {bold('PODSUMOWANIE')}")
    for name, ok in results.items():
        status = green("wczytuje skille") if ok else red("NIE wczytuje skilli")
        print(f"    {green('✓') if ok else red('✗')} {name}: {status}")
    all_ok = all(results.values())
    print(f"  {bold('═' * 78)}")
    print(("  " + green("Wszyscy agenci wczytali skill.")) if all_ok
          else "  " + red("Część agentów NIE wczytuje skilli — popraw prompt i odpal ponownie."))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
