"""
Wyświetla log z danego run_id lub listę ostatnich runów.

Użycie:
    python show_run.py                    # lista ostatnich 20 runów
    python show_run.py <run_id>           # pełny trace danego runa
    python show_run.py <run_id_prefix>    # dopasowanie po prefiksie (min. 4 znaki)
    python show_run.py --last             # trace ostatniego runa
"""

import sys
from database import audit_db
from tracing.trace import format_run_trace

_WIDTH = 64


def list_runs(limit: int = 20) -> None:
    with audit_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ai.run_id::text,
                    ar.name,
                    ar.attack_type,
                    ai.task,
                    ai.started_at,
                    ai.finished_at,
                    COUNT(aal.id) AS log_count
                FROM attack_invocations ai
                JOIN attack_runs ar ON ai.attack_id = ar.id
                LEFT JOIN attack_agent_logs aal ON aal.invocation_id = ai.id
                GROUP BY ai.run_id, ar.name, ar.attack_type, ai.task, ai.started_at, ai.finished_at
                ORDER BY ai.started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    if not rows:
        print("Brak runów w audit DB.")
        return

    print("═" * _WIDTH)
    print(f"{'RUN ID':36}  {'ATAK':20}  {'AGENCI':6}  CZAS")
    print("─" * _WIDTH)
    for run_id, name, atype, task, started, finished, count in rows:
        short_id = run_id[:8]
        dur = ""
        if started and finished:
            secs = (finished - started).total_seconds()
            dur = f"{secs:.0f}s"
        ts = started.strftime("%m-%d %H:%M") if started else "?"
        label = f"{name}" + (f" [{atype}]" if atype else "")
        task_short = (task or "")[:40].replace("\n", " ")
        print(f"{short_id}...  {label:<20}  {count:>4}×   {ts}  {dur}")
        if task_short:
            print(f"  └ {task_short}")
    print("═" * _WIDTH)
    print(f"Użyj: python show_run.py <run_id> aby zobaczyć szczegóły")


def resolve_run_id(arg: str) -> str | None:
    """Zwraca pełne run_id pasujące do prefiksu lub pełnego UUID."""
    with audit_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ai.run_id::text
                FROM attack_invocations ai
                WHERE ai.run_id::text LIKE %s
                ORDER BY ai.started_at DESC
                LIMIT 2
                """,
                (arg + "%",),
            )
            rows = cur.fetchall()

    if not rows:
        return None
    if len(rows) > 1:
        print(f"Prefiks '{arg}' pasuje do {len(rows)} runów — podaj dłuższy prefiks.")
        for r in rows:
            print(f"  {r[0]}")
        return None
    return rows[0][0]


def last_run_id() -> str | None:
    with audit_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id::text FROM attack_invocations ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
    return row[0] if row else None


def main() -> None:
    args = sys.argv[1:]

    if not args:
        list_runs()
        return

    if args[0] == "--last":
        run_id = last_run_id()
        if not run_id:
            print("Brak runów w audit DB.")
            return
    else:
        run_id = resolve_run_id(args[0])
        if not run_id:
            print(f"Nie znaleziono runa dla: {args[0]}")
            return

    print(format_run_trace(run_id))


if __name__ == "__main__":
    main()
