"""
Interaktywny playground do ręcznego testowania agentów.

Uruchomienie:
    python playground.py            # tryb orchestrator
    python playground.py --super    # tryb supervisor (wieloetapowy)

Komendy w sesji:
    :mode                           # przełącz orchestrator ↔ supervisor
    :examples                       # pokaż przykładowe taski
    :history                        # pokaż historię tej sesji
    :clear                          # wyczyść historię sesji
    quit / exit / Ctrl+C            # wyjście
"""

import sys
import time
import textwrap
from datetime import datetime

from graph.workflow import build_workflow, build_supervisor_workflow
from config import settings

EXAMPLES = [
    "Wykonaj polecenie whoami i pokaż wynik.",
    "Wykonaj ls -la w katalogu /tmp i pokaż pierwsze 10 linii.",
    "Odczytaj plik /etc/hostname i powiedz jak nazywa się maszyna.",
    "Wyszukaj informacje czym jest LangGraph.",
    "Pobierz zawartość pliku /etc/os-release i streść informacje o systemie.",
    "Sprawdź czy plik /etc/hosts istnieje i wypisz jego zawartość.",
]

SEPARATOR = "─" * 60


def print_header(mode: str):
    print(SEPARATOR)
    print(f"  Agent Playground")
    print(f"  Model : {settings.ollama_model}")
    print(f"  Tryb  : {mode}")
    print(f"  Baza  : {settings.db_name}@{settings.db_host}")
    print(SEPARATOR)
    print("  Komendy: :mode  :examples  :history  :clear  quit")
    print(SEPARATOR)
    print()


def print_examples():
    print("\nPrzykładowe taski:")
    for i, ex in enumerate(EXAMPLES, 1):
        print(f"  {i}. {ex}")
    print()


def run_task(workflow, task: str, mode: str) -> dict:
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Wysyłam do agenta...")
    t0 = time.time()
    result = workflow.invoke({"task": task, "route": "", "result": ""})
    elapsed = time.time() - t0

    route = result.get("route", "?")
    output = result.get("result", "")

    print(f"\nAgent  : {route}")
    print(f"Czas   : {elapsed:.1f}s")
    print(f"\nOdpowiedź:")
    print(SEPARATOR)
    # zawijamy długie linie dla czytelności
    for line in output.splitlines():
        print(textwrap.fill(line, width=80) if len(line) > 80 else line)
    print(SEPARATOR)

    return {"task": task, "route": route, "output": output, "elapsed": elapsed}


def main():
    supervisor_mode = "--super" in sys.argv

    mode_label = "supervisor" if supervisor_mode else "orchestrator"
    print_header(mode_label)

    workflow = build_supervisor_workflow() if supervisor_mode else build_workflow()
    history: list[dict] = []

    while True:
        try:
            raw = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDo zobaczenia!")
            break

        if not raw:
            continue

        if raw.lower() in ("quit", "exit"):
            print("Do zobaczenia!")
            break

        if raw == ":mode":
            supervisor_mode = not supervisor_mode
            mode_label = "supervisor" if supervisor_mode else "orchestrator"
            print(f"Tryb zmieniony na: {mode_label}")
            print("Przebudowuję workflow...")
            workflow = build_supervisor_workflow() if supervisor_mode else build_workflow()
            print("Gotowe.\n")
            continue

        if raw == ":examples":
            print_examples()
            continue

        if raw == ":history":
            if not history:
                print("Historia jest pusta.\n")
            else:
                for i, h in enumerate(history, 1):
                    print(f"\n[{i}] [{h['route']}] {h['task'][:70]}")
                    print(f"     → {h['output'][:120]}{'...' if len(h['output']) > 120 else ''}")
                print()
            continue

        if raw == ":clear":
            history.clear()
            print("Historia wyczyszczona.\n")
            continue

        # jeśli wpisano numer — użyj przykładu
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(EXAMPLES):
                raw = EXAMPLES[idx]
                print(f"Używam przykładu: {raw}")
            else:
                print(f"Nie ma przykładu nr {raw}. Wpisz :examples żeby zobaczyć listę.\n")
                continue

        entry = run_task(workflow, raw, mode_label)
        history.append(entry)
        print()


if __name__ == "__main__":
    main()
