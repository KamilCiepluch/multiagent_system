"""
Liniowy trace przebiegu systemu agentowego — END-TO-END, do debugowania.

Czyta się od góry do dołu jak jeden ciągły przebieg: agent podrzędny jest
wstawiany dokładnie tam, gdzie agent nadrzędny go zlecił (delegacja → cały
przebieg pod-agenta → wartość zwrócona). Widać pełną ścieżkę od pierwszego
promptu do finalnej odpowiedzi: myśl modelu → decyzja → wywołanie narzędzia →
wynik → myśl PO wyniku → kolejna decyzja.

To uzupełnienie show_log.py (układ hierarchiczny). Oba czytają tę samą bazę
agent_logs — trace_run.py jest wygodniejszy do śledzenia kolejności i delegacji
(np. czy scheduler/supervisor deleguje poprawnie).

Domyślnie thinking jest skracany — dodaj --thinking, by zobaczyć pełne
rozumowanie modelu.

Użycie:
    python trace_run.py                    # lista ostatnich 20 przebiegów
    python trace_run.py <run_id>           # trace danego przebiegu
    python trace_run.py <run_id_prefix>    # dopasowanie po prefiksie (min. 4 znaki)
    python trace_run.py --last             # trace ostatniego przebiegu
    python trace_run.py --last --thinking  # ostatni przebieg z pełnym thinking
"""

import argparse
import sys

from database import logs_db
from tracing.flow_view import format_run_flow

# Wymuś UTF-8 na stdout — domyślne kodowanie konsoli Windows (np. cp1250) nie
# obsługuje znaków ramki (┌ │ └ → ↩) i wysypywałoby skrypt.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_WIDTH = 72


def list_runs(limit: int = 20) -> None:
    runs = logs_db.list_runs(limit)
    if not runs:
        print("Brak przebiegów w bazie agent_logs.")
        return

    print("=" * _WIDTH)
    print(f"{'RUN ID':36}  {'TRYB':12}  {'AG':>3}  {'STATUS':10}  CZAS")
    print("-" * _WIDTH)
    for r in runs:
        dur = ""
        if r["started_at"] and r["finished_at"]:
            dur = f"{(r['finished_at'] - r['started_at']).total_seconds():.0f}s"
        ts = r["started_at"].strftime("%m-%d %H:%M") if r["started_at"] else "?"
        task = (r["task"] or "").replace("\n", " ")[:48]
        print(f"{r['run_id']}  {(r['mode'] or '—'):12}  {r['agent_count']:>3}  "
              f"{r['status']:10}  {ts}  {dur}")
        if task:
            print(f"  └ {task}")
    print("=" * _WIDTH)
    print("Użyj: python trace_run.py <run_id> aby zobaczyć pełny trace")


def resolve_run_id(arg: str) -> str | None:
    runs = logs_db.list_runs(500)
    matches = [r["run_id"] for r in runs if r["run_id"].startswith(arg)]
    if not matches:
        return None
    if len(matches) > 1:
        print(f"Prefiks '{arg}' pasuje do {len(matches)} przebiegów — podaj dłuższy prefiks.")
        for m in matches[:10]:
            print(f"  {m}")
        return None
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Liniowy trace end-to-end przebiegu z bazy agent_logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python trace_run.py                    # lista przebiegów\n"
            "  python trace_run.py <run_id>           # trace (bez pełnego thinking)\n"
            "  python trace_run.py --last --thinking  # ostatni przebieg z thinking\n"
        ),
    )
    parser.add_argument("run_id", nargs="?", help="run_id (lub jego prefiks, min. 4 znaki)")
    parser.add_argument("--last", action="store_true", help="Pokaż ostatni przebieg")
    parser.add_argument("-t", "--thinking", action="store_true",
                        help="Dołącz pełny thinking modelu (domyślnie skracany)")
    parser.add_argument("--limit", type=int, default=20, help="Ile przebiegów na liście (domyślnie 20)")
    args = parser.parse_args()

    if args.last:
        runs = logs_db.list_runs(1)
        if not runs:
            print("Brak przebiegów w bazie agent_logs.")
            return
        run_id = runs[0]["run_id"]
    elif args.run_id:
        run_id = resolve_run_id(args.run_id)
        if not run_id:
            print(f"Nie znaleziono przebiegu dla: {args.run_id}")
            return
    else:
        list_runs(args.limit)
        return

    print(format_run_flow(run_id, show_thinking=args.thinking))


if __name__ == "__main__":
    main()
