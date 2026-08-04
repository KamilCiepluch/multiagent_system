"""Data-access layer for the mini system's observability database (`mini_system_logs`).

Its own database, so the mini system stays self-contained and never mixes into the big system's
agent_logs. Schema in schema_logs.sql; setup is idempotent:

    python -m mini_system.logs_db          # create the database + schema
    python -m mini_system.logs_db --show   # print the last conversation as a timeline

Functions here are thin and return raw ids. Sequencing and the never-break-the-chat guarantee
live one layer up, in observability.py.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import Json

from config import settings

_SCHEMA_FILE = Path(__file__).with_name("schema_logs.sql")
_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.mini_system_logs_dsn)
    return _pool


@contextmanager
def get_conn():
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def _ensure_database() -> None:
    admin_dsn = (
        f"postgresql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/postgres"
    )
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.mini_system_logs_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{settings.mini_system_logs_name}"')
    finally:
        conn.close()


def ensure_schema() -> None:
    _ensure_database()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_FILE.read_text(encoding="utf-8"))


def is_available() -> bool:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM turns LIMIT 1")
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Writes
# ------------------------------------------------------------------

def create_conversation(conversation_id: str, model: str | None, note: str | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (conversation_id, model, note) VALUES (%s,%s,%s) RETURNING id",
            (conversation_id, model, note),
        )
        return cur.fetchone()[0]


def start_turn(conversation_pk: int, turn_index: int, user_message: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO turns (conversation_pk, turn_index, user_message) VALUES (%s,%s,%s) RETURNING id",
            (conversation_pk, turn_index, user_message),
        )
        return cur.fetchone()[0]


def finish_turn(turn_id: int, assistant_message: str | None, *, status: str = "ok",
                error: str | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE turns SET assistant_message=%s, status=%s, error=%s, finished_at=now(), "
            "duration_ms = (EXTRACT(EPOCH FROM (now() - started_at)) * 1000)::int WHERE id=%s",
            (assistant_message, status, error, turn_id),
        )


def start_invocation(turn_id: int, agent_name: str, task: str, parent_id: int | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_invocations (turn_id, parent_id, agent_name, task) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (turn_id, parent_id, agent_name, task),
        )
        return cur.fetchone()[0]


def finish_invocation(invocation_id: int, final_output: str | None, *, status: str = "ok",
                      error: str | None = None, structured: dict | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_invocations SET final_output=%s, status=%s, error=%s, structured=%s, "
            "finished_at=now(), "
            "duration_ms = (EXTRACT(EPOCH FROM (now() - started_at)) * 1000)::int WHERE id=%s",
            (final_output, status, error, Json(structured) if structured is not None else None,
             invocation_id),
        )


def log_tool_call(invocation_id: int, step: int, tool_name: str, tool_input, output: str | None,
                  *, status: str = "ok", error: str | None = None, duration_ms: int | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tool_calls (invocation_id, step, tool_name, input, output, status, error, duration_ms) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (invocation_id, step, tool_name, Json(tool_input) if tool_input is not None else None,
             output, status, error, duration_ms),
        )


def log_messages(turn_id: int, rows: list[dict], invocation_id: int | None = None) -> None:
    """rows: [{position, role, content, tool_calls, tool_call_id}], all from one agent's run."""
    if not rows:
        return
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO messages (turn_id, invocation_id, position, role, content, tool_calls, "
            "tool_call_id, tool_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(turn_id, invocation_id, r["position"], r["role"], r.get("content"),
              Json(r["tool_calls"]) if r.get("tool_calls") else None, r.get("tool_call_id"),
              r.get("tool_name"))
             for r in rows],
        )


# ------------------------------------------------------------------
# Reads — enough to inspect a run without leaving the terminal
# ------------------------------------------------------------------

def list_conversations(limit: int = 20) -> list[tuple]:
    """(pk, conversation_id, model, note, started_at, turns) — newest first. Each `/new` chat is
    its own row, which is the point of starting one."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.conversation_id, c.model, c.note, c.started_at, "
            "(SELECT count(*) FROM turns t WHERE t.conversation_pk = c.id) "
            "FROM conversations c ORDER BY c.id DESC LIMIT %s", (limit,))
        return list(cur.fetchall())


def last_conversation_pk() -> int | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM conversations ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def _flat(text, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


_INVOCATION_COLS = "id, agent_name, task, status, duration_ms, structured"


def _tool_call_line(call, indent: str) -> str:
    step, name, tin, tout, status, ms = call
    flag = "" if status == "ok" else " !!"
    return (f"{indent}  tool>  {step}. {name}({_flat(tin, 90)}) "
            f"[{status}{f', {ms} ms' if ms else ''}]{flag} -> {_flat(tout, 110)}")


def _render_invocation(cur, turn_id: int, row, indent: str) -> list[str]:
    """One agent's run: what its model said, what it called, and — in the place where it called
    it — the agent it delegated to."""
    inv_id, agent, task, status, ms, structured = row
    out = [f"{indent}[agent] {agent} ({status}{f', {ms} ms' if ms else ''}) "
           f"task={_flat(task, 90)!r}" + (f"  {structured}" if structured else "")]

    cur.execute("SELECT step, tool_name, input, output, status, duration_ms FROM tool_calls "
                "WHERE invocation_id=%s ORDER BY step", (inv_id,))
    calls = list(cur.fetchall())
    cur.execute("SELECT role, content, tool_calls, tool_name FROM messages "
                "WHERE invocation_id=%s ORDER BY position", (inv_id,))
    messages = list(cur.fetchall())
    cur.execute(f"SELECT {_INVOCATION_COLS} FROM agent_invocations WHERE turn_id=%s AND "
                "parent_id=%s ORDER BY id", (turn_id, inv_id))
    children = list(cur.fetchall())

    def child_for(tool_input) -> list:
        """The agent this tool call delegated to, if any — matched on the task it was given."""
        values = [str(v) for v in tool_input.values()] if isinstance(tool_input, dict) else []
        for i, child in enumerate(children):
            if str(child[2]) in values:
                return _render_invocation(cur, turn_id, children.pop(i), indent + "    ")
        return []

    # The messages are the order of events; the tool_calls rows are the ground truth of what each
    # call received and returned. Matched by tool name, so a tool result nobody called (a skill
    # gate injects one) cannot shift the pairing.
    used: set[int] = set()
    for role, content, tool_calls, tool_name in messages:
        if role == "ai":
            if _flat(content, 1):
                out.append(f"{indent}  model> {_flat(content, 160)}")
            for tc in tool_calls or []:
                out.append(f"{indent}  model> calls {tc.get('name')}({_flat(tc.get('args'), 90)})")
        elif role == "tool":
            match = next((i for i, c in enumerate(calls) if i not in used and c[1] == tool_name),
                         None)
            if match is None:
                out.append(f"{indent}  tool>  {tool_name} -> {_flat(content, 110)}")
                continue
            used.add(match)
            out += child_for(calls[match][2])
            out.append(_tool_call_line(calls[match], indent))

    # calls with no message row (messages not logged, or an older run) and any agent whose call
    # could not be matched — nothing is dropped just because the pairing failed
    for i, call in enumerate(calls):
        if i not in used:
            out += child_for(call[2])
            out.append(_tool_call_line(call, indent))
    for child in list(children):
        out += _render_invocation(cur, turn_id, child, indent + "    ")
    return out


def _invocation_lines(cur, turn_id: int, parent_id: int | None, indent: str) -> list[str]:
    cur.execute(f"SELECT {_INVOCATION_COLS} FROM agent_invocations WHERE turn_id=%s AND "
                "parent_id IS NOT DISTINCT FROM %s ORDER BY id", (turn_id, parent_id))
    out: list[str] = []
    for row in cur.fetchall():
        out += _render_invocation(cur, turn_id, row, indent)
    return out


def timeline(conversation_pk: int) -> list[str]:
    """The conversation replayed: every turn, every agent that ran inside it, what each model
    said and every tool call it made, in order."""
    out: list[str] = []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, turn_index, user_message, assistant_message, status, duration_ms "
            "FROM turns WHERE conversation_pk=%s ORDER BY turn_index", (conversation_pk,))
        for turn_id, idx, user_msg, answer, status, ms in cur.fetchall():
            out.append(f"\n=== turn {idx}  [{status}{f', {ms} ms' if ms else ''}]")
            out.append(f"  user> {user_msg}")
            out += _invocation_lines(cur, turn_id, None, "    ")
            out.append(f"  bot>  {_flat(answer, 200)}")
    return out


if __name__ == "__main__":
    import sys

    try:  # the log holds whatever the world and the models wrote; a cp1250 console must not crash
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = sys.argv[1:]
    if "--list" in args:
        rows = list_conversations()
        if not rows:
            print("No conversations logged yet.")
        for pk, cid, model, note, started, turns in rows:
            print(f"{pk:>5}  {started:%Y-%m-%d %H:%M}  {cid:<28} {turns:>3} turns  "
                  f"{model or '?'}{f'  — {note}' if note else ''}")
    elif "--show" in args:
        after = args[args.index("--show") + 1:]
        pk = int(after[0]) if after and after[0].isdigit() else last_conversation_pk()
        if pk is None:
            print("No conversations logged yet.")
        else:
            print("\n".join(timeline(pk)))
    else:
        ensure_schema()
        print(f"mini_system_logs ready ({settings.mini_system_logs_name}).")
