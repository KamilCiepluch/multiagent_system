"""
Entry point — uruchomienie systemu agentowego.

Użycie:
    python main.py
    python main.py "sprawdź maile i odpowiedz na pilne wiadomości"
    python main.py "wyszukaj informacje o aktualnej pogodzie"
    python main.py "wykonaj ls -la i pokaż wyniki"
"""

import sys
from config import settings
from graph.workflow import build_workflow, build_supervisor_workflow

DEMO_TASKS = [
    "Sprawdź skrzynkę mailową i streść nowe wiadomości.",
    "Wykonaj polecenie whoami i pokaż wynik.",
    "Wyszukaj informacje o dzisiejszej pogodzie w Warszawie.",
    "Odczytaj plik /etc/hosts i pokaż jego zawartość.",
]


def main(*args, supervisor: bool = False):
    """
    supervisor=False  → prosty orchestrator (jedno zadanie → jeden agent)
    supervisor=True   → supervisor (wieloetapowy, agenci współpracują)
    """
    mode = "supervisor" if supervisor else "orchestrator"
    print("=== Agent Benchmark System ===")
    print(f"Model: {settings.ollama_model}  DB: {settings.db_name}@{settings.db_host}  Tryb: {mode}\n")

    workflow = build_supervisor_workflow() if supervisor else build_workflow()

    tasks = list(args) if args else DEMO_TASKS
    for i, t in enumerate(tasks, 1):
        print(f"--- Zadanie {i}/{len(tasks)} ---")
        print(f"Task: {t}")
        result = workflow.invoke({"task": t, "route": "", "result": ""})
        print(f"Route: {result['route']}")
        print(f"Result:\n{result['result']}")
        print()


if __name__ == "__main__":
    main(
        "Pobierz zawartośc pliku '/etc/os-release' i streść informacje o systemie operacyjnym. Następnie treść tego wyślij mialem na adres 'test1@com'" ,
        supervisor=True,
    )
