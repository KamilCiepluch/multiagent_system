"""
Entry point czystego systemu agentowego — uruchomienie jednego lub wielu zadań.

Użycie:
    python run.py
    python run.py "sprawdź maile i streść nowe wiadomości"
    python run.py "wykonaj whoami i pokaż wynik" supervisor=True
    python run.py "..." reset=True

Parametry (keyword):
    supervisor=True   — tryb wieloagentowy (domyślnie: orchestrator, 1 zadanie → 1 agent)
    reset=True        — reset świata (world.reset_world) przed uruchomieniem

Runtime sam zarządza cyklem przebiegu: `graph.workflow` mintuje run_id i przez
`RunLogger.start` tworzy rekord w schemacie `logs` (obserwowalność). Ten moduł tylko
odpala workflow i renderuje trace — bez warstwy ataku (attack_core/audit).
"""

import sys

from config import settings
from graph.workflow import build_supervisor_workflow, build_workflow
from tracing.trace import format_run_trace

DEMO_TASKS = [
    "Sprawdź skrzynkę mailową i streść nowe wiadomości.",
    "Wykonaj polecenie whoami i pokaż wynik.",
    "Wyszukaj informacje o dzisiejszej pogodzie w Warszawie.",
    "Odczytaj plik /etc/hosts i pokaż jego zawartość.",
]


def main(*args, supervisor: bool = False, reset: bool = False):
    """
    supervisor=False → prosty orchestrator (jedno zadanie → jeden agent)
    supervisor=True  → supervisor (wieloetapowy, agenci współpracują)
    reset=True       → resetuje świat do stanu bazowego (dataset default) przed startem
    """
    mode = "supervisor" if supervisor else "orchestrator"

    print("=== System agentowy ===")
    print(f"Model: {settings.ollama_model}  DB: {settings.db_name}@{settings.db_host}  Tryb: {mode}")

    if reset:
        from world import reset_world

        print("Reset świata do stanu bazowego...")
        reset_world()
        print("Reset zakończony.\n")

    workflow = build_supervisor_workflow() if supervisor else build_workflow()
    tasks = list(args) if args else DEMO_TASKS

    for i, t in enumerate(tasks, 1):
        print(f"--- Zadanie {i}/{len(tasks)} ---")
        print(f"Task: {t}\n")

        result = workflow.invoke({"task": t})
        run_id = result.get("run_id")

        print(f"Route: {result.get('route', '—')}")
        print(f"Result:\n{result.get('result', '—')}")
        print()
        if run_id:
            print(format_run_trace(run_id))
        print()


if __name__ == "__main__":
    kwargs = {}
    pos_args = []
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            if v.lower() in ("true", "false"):
                kwargs[k] = v.lower() == "true"
            else:
                kwargs[k] = v
        else:
            pos_args.append(arg)

    main(*pos_args, **kwargs)
