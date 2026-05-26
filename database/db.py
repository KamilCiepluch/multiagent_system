"""
Warstwa dostępu do danych.

Wzorzec: funkcje zwracają Pydantic models — callerzy dostają
typowany kontrakt zamiast surowych krotek z psycopg2.
Połączenia zarządzane przez SimpleConnectionPool — jeden pool na cały proces.
"""

import json
from contextlib import contextmanager
from psycopg2 import pool as pg_pool

from config import settings
from database.models import AgentLog, Email, ToolOutput

_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 10, dsn=settings.db_dsn)
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
# ToolOutput — główny punkt infekcji MCP
# ------------------------------------------------------------------

def fetch_tool_output(tool_name: str, input_key: str) -> str:
    """
    Pobiera output narzędzia z bazy.
    Próbuje exact match, potem fallback na NULL (default dla narzędzia).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tool_name, input_key, output, created_at "
                "FROM tools_outputs WHERE tool_name = %s AND input_key = %s",
                (tool_name, input_key),
            )
            row = cur.fetchone()
            if row:
                return ToolOutput.from_row(row).output

            cur.execute(
                "SELECT id, tool_name, input_key, output, created_at "
                "FROM tools_outputs WHERE tool_name = %s AND input_key IS NULL",
                (tool_name,),
            )
            row = cur.fetchone()
            if row:
                return ToolOutput.from_row(row).output

    return f"[MCP] Brak outputu dla narzędzia '{tool_name}'"


def upsert_tool_output(tool_output: ToolOutput) -> None:
    """Ustawia/nadpisuje output narzędzia — używane w skryptach ataku."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tools_outputs (tool_name, input_key, output)
                VALUES (%(tool_name)s, %(input_key)s, %(output)s)
                ON CONFLICT (tool_name, input_key)
                DO UPDATE SET output = EXCLUDED.output
                """,
                tool_output.model_dump(include={"tool_name", "input_key", "output"}),
            )


# ------------------------------------------------------------------
# Email
# ------------------------------------------------------------------

def list_emails() -> list[Email]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sender, recipient, subject, body, is_read, created_at "
                "FROM emails ORDER BY created_at DESC"
            )
            return [Email.from_row(r) for r in cur.fetchall()]


def get_email(email_id: int) -> Email | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sender, recipient, subject, body, is_read, created_at "
                "FROM emails WHERE id = %s",
                (email_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("UPDATE emails SET is_read = TRUE WHERE id = %s", (email_id,))
            return Email.from_row(row)


def create_email(email: Email) -> Email:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO emails (sender, recipient, subject, body) "
                "VALUES (%(sender)s, %(recipient)s, %(subject)s, %(body)s) RETURNING id, created_at",
                email.model_dump(include={"sender", "recipient", "subject", "body"}),
            )
            row = cur.fetchone()
            return email.model_copy(update={"id": row[0], "created_at": row[1]})


# ------------------------------------------------------------------
# AgentLog
# ------------------------------------------------------------------

def create_agent_log(log: AgentLog) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_logs (agent_name, task, steps, final_output) "
                "VALUES (%(agent_name)s, %(task)s, %(steps)s, %(final_output)s)",
                {
                    **log.model_dump(include={"agent_name", "task", "final_output"}),
                    "steps": json.dumps(log.steps, ensure_ascii=False),
                },
            )
