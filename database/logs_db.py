"""
Warstwa dostępu do bazy logów (agent_logs).

Dedykowana baza obserwowalności — zapisywana ZAWSZE przy każdym przebiegu
workflow (niezależnie od ataku). Schemat znormalizowany: runs →
agent_invocations → (reasoning_steps | tool_calls | loaded_skills), plus
run_db_changes. Te trzy dzielą wspólny licznik `step` w obrębie wywołania —
scalenie po `step` odtwarza pełną oś czasu (myśl → decyzja → narzędzie → wynik
→ myśl po wyniku → …).

Operacje są pisane tak, by były odporne na błędy — logowanie nigdy nie może
wywrócić głównej logiki agentów. Funkcje zwracają surowe wartości/krotki;
warstwę wyższego poziomu (sekwencjonowanie, pairing tool-start/end) trzyma
RunLogger w tracing/run_logger.py.
"""

import json
from contextlib import contextmanager

from psycopg2 import pool as pg_pool
from psycopg2.extras import Json

from config import settings

_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.logs_db_dsn)
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


def is_available() -> bool:
    """Czy baza logów jest dostępna i ma zaaplikowany schemat."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM runs LIMIT 1")
        return True
    except Exception:
        return False


def _jsonb(value) -> Json | None:
    return Json(value) if value is not None else None


# ------------------------------------------------------------------
# Runs
# ------------------------------------------------------------------

def create_run(run_id: str, task: str, mode: str | None) -> None:
    """Idempotentne utworzenie przebiegu. Może być wołane dwukrotnie: najpierw przez
    AttackRunner (by spełnić FK audit→logs), potem przez run_logger (z trybem) —
    COALESCE dba, by pierwsze nie-NULL pola się utrwaliły, a żadne nie wyzerowało."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (run_id, task, mode) VALUES (%s::uuid, %s, %s) "
                "ON CONFLICT (run_id) DO UPDATE SET "
                "  task = COALESCE(runs.task, EXCLUDED.task), "
                "  mode = COALESCE(runs.mode, EXCLUDED.mode)",
                (run_id, task, mode),
            )


def finish_run(run_id: str, status: str, result: str | None, error: str | None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = %s, result = %s, error = %s, finished_at = NOW() "
                "WHERE run_id = %s::uuid",
                (status, result, error, run_id),
            )


# ------------------------------------------------------------------
# Agent invocations
# ------------------------------------------------------------------

def start_invocation(
    run_id: str,
    parent_id: int | None,
    seq: int,
    agent_name: str,
    input_text: str | None,
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_invocations (run_id, parent_id, seq, agent_name, input) "
                "VALUES (%s::uuid, %s, %s, %s, %s) RETURNING id",
                (run_id, parent_id, seq, agent_name, input_text),
            )
            return cur.fetchone()[0]


def finish_invocation(
    invocation_id: int,
    output: str | None,
    status: str,
    error: str | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_invocations "
                "SET output = %s, status = %s, error = %s, finished_at = NOW() WHERE id = %s",
                (output, status, error, invocation_id),
            )


# ------------------------------------------------------------------
# Reasoning steps — kolejne tury modelu (myśl / treść / decyzja)
# ------------------------------------------------------------------

def add_reasoning_step(
    invocation_id: int,
    step: int,
    thinking: str | None,
    content: str | None,
    decided_tools: list | None,
) -> None:
    """Zapisuje jedną turę modelu w obrębie wywołania agenta (jedno on_llm_end).

    thinking      — ukryty kanał rozumowania (None gdy model go nie zwraca),
    content       — widoczna treść wiadomości modelu,
    decided_tools — [{name, args}] narzędzi zleconych w tej turze (None gdy brak).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reasoning_steps (invocation_id, step, thinking, content, decided_tools) "
                "VALUES (%s, %s, %s, %s, %s)",
                (invocation_id, step, thinking, content, _jsonb(decided_tools)),
            )


# ------------------------------------------------------------------
# Tool calls
# ------------------------------------------------------------------

def start_tool_call(
    invocation_id: int,
    seq: int,
    step: int,
    tool_name: str,
    input_args: dict | None,
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tool_calls (invocation_id, seq, step, tool_name, input) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (invocation_id, seq, step, tool_name, _jsonb(input_args)),
            )
            return cur.fetchone()[0]


def finish_tool_call(
    tool_call_id: int,
    output: str | None,
    is_error: bool,
    error: str | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tool_calls "
                "SET output = %s, is_error = %s, error = %s, finished_at = NOW() WHERE id = %s",
                (output, is_error, error, tool_call_id),
            )


# ------------------------------------------------------------------
# Loaded skills
# ------------------------------------------------------------------

def add_loaded_skill(
    invocation_id: int,
    seq: int,
    step: int,
    action: str,
    skill_name: str | None,
    content: str | None,
    is_error: bool = False,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO loaded_skills (invocation_id, seq, step, action, skill_name, content, is_error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (invocation_id, seq, step, action, skill_name, content, is_error),
            )


# ------------------------------------------------------------------
# Run DB changes
# ------------------------------------------------------------------

def log_db_change(
    run_id: str,
    invocation_id: int | None,
    seq: int,
    table_name: str,
    operation: str,
    record_key: str | None,
    old_value: dict | None,
    new_value: dict | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO run_db_changes "
                "(run_id, invocation_id, seq, table_name, operation, record_key, old_value, new_value) "
                "VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    invocation_id,
                    seq,
                    table_name,
                    operation,
                    record_key,
                    _jsonb(old_value),
                    _jsonb(new_value),
                ),
            )


# ------------------------------------------------------------------
# Readery — dla viewera / analiz
# ------------------------------------------------------------------

def get_run(run_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id::text, task, mode, status, result, error, started_at, finished_at "
                "FROM runs WHERE run_id = %s::uuid",
                (run_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "run_id": row[0], "task": row[1], "mode": row[2], "status": row[3],
                "result": row[4], "error": row[5], "started_at": row[6], "finished_at": row[7],
            }


def get_invocations(run_id: str) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, parent_id, seq, agent_name, input, output, "
                "       status, error, started_at, finished_at "
                "FROM agent_invocations WHERE run_id = %s::uuid ORDER BY seq ASC",
                (run_id,),
            )
            cols = ["id", "parent_id", "seq", "agent_name", "input", "output",
                    "status", "error", "started_at", "finished_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_reasoning_steps(invocation_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, step, thinking, content, decided_tools, created_at "
                "FROM reasoning_steps WHERE invocation_id = %s ORDER BY step ASC",
                (invocation_id,),
            )
            cols = ["id", "step", "thinking", "content", "decided_tools", "created_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_tool_calls(invocation_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, seq, step, tool_name, input, output, is_error, error, started_at, finished_at "
                "FROM tool_calls WHERE invocation_id = %s ORDER BY seq ASC",
                (invocation_id,),
            )
            cols = ["id", "seq", "step", "tool_name", "input", "output", "is_error", "error",
                    "started_at", "finished_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_loaded_skills(invocation_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, seq, step, action, skill_name, content, is_error, created_at "
                "FROM loaded_skills WHERE invocation_id = %s ORDER BY seq ASC",
                (invocation_id,),
            )
            cols = ["id", "seq", "step", "action", "skill_name", "content", "is_error", "created_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_db_changes(run_id: str) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, invocation_id, seq, table_name, operation, record_key, "
                "       old_value, new_value, changed_at "
                "FROM run_db_changes WHERE run_id = %s::uuid ORDER BY seq ASC",
                (run_id,),
            )
            cols = ["id", "invocation_id", "seq", "table_name", "operation", "record_key",
                    "old_value", "new_value", "changed_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_run_logs(run_id: str) -> list:
    """Logi agentów przebiegu jako list[AgentLog] — JEDYNE źródło prawdy o trace'ie.

    Buduje kształt AgentLog (agent_name, task, tool_calls=[{tool_name,input,output}],
    final_output) z agent_invocations + tool_calls. Zastępuje czytanie z (usuniętej)
    kopii audit.attack_agent_logs — judge, depth-scorer, hyperagent czytają stąd,
    z właściciela danych (logi są append-only, tylko do odczytu)."""
    from database.models import AgentLog

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, agent_name, input, output FROM agent_invocations "
                "WHERE run_id = %s::uuid ORDER BY seq ASC",
                (run_id,),
            )
            invs = cur.fetchall()
            cur.execute(
                "SELECT tc.invocation_id, tc.tool_name, tc.input, tc.output "
                "FROM tool_calls tc JOIN agent_invocations ai ON ai.id = tc.invocation_id "
                "WHERE ai.run_id = %s::uuid ORDER BY tc.seq ASC",
                (run_id,),
            )
            tool_rows = cur.fetchall()

    by_inv: dict[int, list[dict]] = {}
    for inv_id, tool_name, tc_input, tc_output in tool_rows:
        by_inv.setdefault(inv_id, []).append(
            {"tool_name": tool_name, "input": tc_input, "output": tc_output}
        )

    return [
        AgentLog(
            id=inv_id, run_id=run_id, agent_name=agent_name,
            task=task or "", tool_calls=by_inv.get(inv_id, []),
            final_output=output or "", attack_success=None,
        )
        for inv_id, agent_name, task, output in invs
    ]


def list_runs(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.run_id::text, r.task, r.mode, r.status, r.started_at, r.finished_at, "
                "       (SELECT COUNT(*) FROM agent_invocations ai WHERE ai.run_id = r.run_id) "
                "FROM runs r ORDER BY r.started_at DESC LIMIT %s",
                (limit,),
            )
            cols = ["run_id", "task", "mode", "status", "started_at", "finished_at", "agent_count"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
