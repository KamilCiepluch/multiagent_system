"""
Warstwa dostępu do bazy audytowej (agents_audit).

Baza nigdy nie jest resetowana — przechowuje pełną historię ataków.
Operacje są odporne na błędy: audit nie może blokować głównej logiki agentów.
"""

import json
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool

from config import settings

_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.audit_db_dsn)
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


# ------------------------------------------------------------------
# Attack runs
# ------------------------------------------------------------------

def start_attack(
    name: str,
    attack_type: str | None = None,
    description: str | None = None,
) -> str:
    """Tworzy rekord ataku, zwraca attack_id (UUID jako string)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_runs (name, attack_type, description) "
                "VALUES (%s, %s, %s) RETURNING id::text",
                (name, attack_type, description),
            )
            return cur.fetchone()[0]


def finish_attack(attack_id: str, outcome: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attack_runs SET finished_at = NOW(), outcome = %s "
                "WHERE id = %s::uuid",
                (outcome, attack_id),
            )


# ------------------------------------------------------------------
# Invocations
# ------------------------------------------------------------------

def start_invocation(
    attack_id: str,
    invocation_n: int,
    run_id: str,
    task: str | None = None,
) -> int:
    """Tworzy rekord wywołania, zwraca invocation_id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_invocations (attack_id, invocation_n, run_id, task) "
                "VALUES (%s::uuid, %s, %s::uuid, %s) RETURNING id",
                (attack_id, invocation_n, run_id, task),
            )
            return cur.fetchone()[0]


def finish_invocation(invocation_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attack_invocations SET finished_at = NOW() WHERE id = %s",
                (invocation_id,),
            )


def next_invocation_n(attack_id: str) -> int:
    """Zwraca kolejny numer wywołania w ramach ataku (1-based)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(invocation_n), 0) + 1 "
                "FROM attack_invocations WHERE attack_id = %s::uuid",
                (attack_id,),
            )
            return cur.fetchone()[0]


# ------------------------------------------------------------------
# Logs & changes
# ------------------------------------------------------------------

def log_agent_log(
    invocation_id: int,
    agent_name: str | None,
    task: str | None,
    tool_calls: list,
    final_output: str | None,
    attack_success: bool | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_agent_logs "
                "(invocation_id, agent_name, task, tool_calls, final_output, attack_success) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                (
                    invocation_id,
                    agent_name,
                    task,
                    json.dumps(tool_calls, ensure_ascii=False),
                    final_output,
                    attack_success,
                ),
            )


def get_run_logs(run_id: str):
    """Zwraca logi agentów dla danego run_id jako list[AgentLog], posortowane chronologicznie."""
    from database.models import AgentLog
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT aal.id, ai.run_id, aal.agent_name, aal.task,
                       aal.tool_calls, aal.final_output, aal.attack_success, aal.created_at
                FROM attack_agent_logs aal
                JOIN attack_invocations ai ON aal.invocation_id = ai.id
                WHERE ai.run_id = %s::uuid
                ORDER BY aal.created_at ASC
                """,
                (run_id,),
            )
            return [AgentLog.from_row(r) for r in cur.fetchall()]


def log_db_change(
    invocation_id: int,
    table_name: str,
    operation: str,
    record_key: str | None,
    old_value: dict | None,
    new_value: dict | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_db_changes "
                "(invocation_id, table_name, operation, record_key, old_value, new_value) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)",
                (
                    invocation_id,
                    table_name,
                    operation,
                    record_key,
                    json.dumps(old_value, default=str) if old_value is not None else None,
                    json.dumps(new_value, default=str) if new_value is not None else None,
                ),
            )
