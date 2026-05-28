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
from database.models import AgentLog, AgentSkill, Email, EmailContact, GithubSource, Repository, RepoCommand, ToolOutput

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

_EMAIL_COLS = "id, sender, recipient, subject, body, is_read, is_deleted, thread_id, in_reply_to, created_at"
_ACTIVE = "is_deleted = FALSE"


def list_emails() -> list[Email]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_EMAIL_COLS} FROM emails WHERE {_ACTIVE} ORDER BY created_at DESC"
            )
            return [Email.from_row(r) for r in cur.fetchall()]


def get_email(email_id: int) -> Email | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_EMAIL_COLS} FROM emails WHERE id = %s AND {_ACTIVE}",
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
                "INSERT INTO emails (sender, recipient, subject, body, in_reply_to) "
                "VALUES (%(sender)s, %(recipient)s, %(subject)s, %(body)s, %(in_reply_to)s) "
                "RETURNING id, created_at",
                email.model_dump(include={"sender", "recipient", "subject", "body", "in_reply_to"}),
            )
            row = cur.fetchone()
            new_id, created_at = row[0], row[1]
            thread_id = email.thread_id if email.thread_id is not None else new_id
            cur.execute("UPDATE emails SET thread_id = %s WHERE id = %s", (thread_id, new_id))
            return email.model_copy(update={"id": new_id, "created_at": created_at, "thread_id": thread_id})


def get_email_thread(email_id: int) -> list[Email]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT thread_id FROM emails WHERE id = %s AND {_ACTIVE}",
                (email_id,),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return []
            thread_id = row[0]
            cur.execute(
                f"SELECT {_EMAIL_COLS} FROM emails "
                f"WHERE thread_id = %s AND {_ACTIVE} ORDER BY created_at ASC",
                (thread_id,),
            )
            return [Email.from_row(r) for r in cur.fetchall()]


def soft_delete_email(email_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE emails SET is_deleted = TRUE WHERE id = %s AND {_ACTIVE}",
                (email_id,),
            )
            return cur.rowcount > 0


def mark_email_unread(email_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE emails SET is_read = FALSE WHERE id = %s AND {_ACTIVE}",
                (email_id,),
            )
            return cur.rowcount > 0


def list_unread_emails() -> list[Email]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_EMAIL_COLS} FROM emails "
                f"WHERE is_read = FALSE AND {_ACTIVE} ORDER BY created_at DESC"
            )
            return [Email.from_row(r) for r in cur.fetchall()]


def search_emails(query: str) -> list[Email]:
    pattern = f"%{query}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_EMAIL_COLS} FROM emails "
                f"WHERE {_ACTIVE} AND (sender ILIKE %s OR subject ILIKE %s OR body ILIKE %s) "
                "ORDER BY created_at DESC",
                (pattern, pattern, pattern),
            )
            return [Email.from_row(r) for r in cur.fetchall()]


def get_email_stats() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_read = FALSE) "
                f"FROM emails WHERE {_ACTIVE}"
            )
            total, unread = cur.fetchone()
            return {"total": total, "unread": unread, "read": total - unread}


# ------------------------------------------------------------------
# EmailContact
# ------------------------------------------------------------------

_CONTACT_COLS = "id, email, name, is_verified, is_blacklisted, created_at"


def check_contact(email: str) -> EmailContact | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CONTACT_COLS} FROM email_contacts WHERE email = %s",
                (email.lower(),),
            )
            row = cur.fetchone()
            return EmailContact.from_row(row) if row else None


def add_contact(contact: EmailContact) -> EmailContact:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO email_contacts (email, name, is_verified, is_blacklisted) "
                "VALUES (%(email)s, %(name)s, %(is_verified)s, %(is_blacklisted)s) "
                "RETURNING id, created_at",
                contact.model_dump(include={"email", "name", "is_verified", "is_blacklisted"}),
            )
            row = cur.fetchone()
            return contact.model_copy(update={"id": row[0], "created_at": row[1]})


def update_contact_flags(
    email: str,
    is_verified: bool | None = None,
    is_blacklisted: bool | None = None,
) -> bool:
    updates = {}
    if is_verified is not None:
        updates["is_verified"] = is_verified
    if is_blacklisted is not None:
        updates["is_blacklisted"] = is_blacklisted
    if not updates:
        return False
    set_clause = ", ".join(f"{col} = %s" for col in updates)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE email_contacts SET {set_clause} WHERE email = %s",
                (*updates.values(), email.lower()),
            )
            return cur.rowcount > 0


def list_contacts() -> list[EmailContact]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CONTACT_COLS} FROM email_contacts ORDER BY email ASC"
            )
            return [EmailContact.from_row(r) for r in cur.fetchall()]


# ------------------------------------------------------------------
# GithubSource
# ------------------------------------------------------------------

_GITHUB_COLS = "id, owner, display_name, is_verified, is_blacklisted, created_at"


def check_github_source(owner: str) -> GithubSource | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_GITHUB_COLS} FROM github_sources WHERE owner = %s",
                (owner.lower(),),
            )
            row = cur.fetchone()
            return GithubSource.from_row(row) if row else None


def list_github_sources() -> list[GithubSource]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_GITHUB_COLS} FROM github_sources ORDER BY owner ASC")
            return [GithubSource.from_row(r) for r in cur.fetchall()]


def add_github_source(source: GithubSource) -> GithubSource:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO github_sources (owner, display_name, is_verified, is_blacklisted) "
                "VALUES (%(owner)s, %(display_name)s, %(is_verified)s, %(is_blacklisted)s) "
                "RETURNING id, created_at",
                source.model_dump(include={"owner", "display_name", "is_verified", "is_blacklisted"}),
            )
            row = cur.fetchone()
            return source.model_copy(update={"id": row[0], "created_at": row[1]})


def update_github_source_flags(
    owner: str,
    is_verified: bool | None = None,
    is_blacklisted: bool | None = None,
) -> bool:
    updates = {}
    if is_verified is not None:
        updates["is_verified"] = is_verified
    if is_blacklisted is not None:
        updates["is_blacklisted"] = is_blacklisted
    if not updates:
        return False
    set_clause = ", ".join(f"{col} = %s" for col in updates)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE github_sources SET {set_clause} WHERE owner = %s",
                (*updates.values(), owner.lower()),
            )
            return cur.rowcount > 0


# ------------------------------------------------------------------
# Repository
# ------------------------------------------------------------------

_REPO_COLS = "id, name, url, owner, description, is_installed, installed_at, created_at"


def get_repo_by_name(name: str) -> Repository | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_REPO_COLS} FROM repositories WHERE name = %s", (name,))
            row = cur.fetchone()
            return Repository.from_row(row) if row else None


def get_repo_by_url(url: str) -> Repository | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_REPO_COLS} FROM repositories WHERE url = %s", (url,))
            row = cur.fetchone()
            return Repository.from_row(row) if row else None


def list_repos() -> list[Repository]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_REPO_COLS} FROM repositories ORDER BY created_at DESC")
            return [Repository.from_row(r) for r in cur.fetchall()]


def create_repo(repo: Repository) -> Repository:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO repositories (name, url, owner, description) "
                "VALUES (%(name)s, %(url)s, %(owner)s, %(description)s) "
                "RETURNING id, created_at",
                repo.model_dump(include={"name", "url", "owner", "description"}),
            )
            row = cur.fetchone()
            return repo.model_copy(update={"id": row[0], "created_at": row[1]})


def mark_repo_installed(repo_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE repositories SET is_installed = TRUE, installed_at = NOW() WHERE id = %s",
                (repo_id,),
            )
            return cur.rowcount > 0


def mark_repo_uninstalled(repo_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE repositories SET is_installed = FALSE, installed_at = NULL WHERE id = %s",
                (repo_id,),
            )
            return cur.rowcount > 0


# ------------------------------------------------------------------
# RepoCommand — dynamiczne komendy z zainstalowanych repozytoriów
# ------------------------------------------------------------------

_CMD_COLS = "id, repo_id, command, description, output, created_at"


def get_repo_commands(repo_id: int) -> list[RepoCommand]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CMD_COLS} FROM repo_commands WHERE repo_id = %s ORDER BY command ASC",
                (repo_id,),
            )
            return [RepoCommand.from_row(r) for r in cur.fetchall()]


def find_command_output(command: str) -> str | None:
    """
    Sprawdza czy wywołana komenda pasuje do komendy z zainstalowanego repo.
    Dopasowuje dokładnie lub gdy command zaczyna się od zarejestrowanej komendy + spacja.
    Zwraca output lub None gdy brak dopasowania.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT rc.output FROM repo_commands rc
                JOIN repositories r ON rc.repo_id = r.id
                WHERE r.is_installed = TRUE
                  AND (%s = rc.command OR %s LIKE rc.command || ' %%')
                ORDER BY LENGTH(rc.command) DESC
                LIMIT 1
                """,
                (command, command),
            )
            row = cur.fetchone()
            return row[0] if row else None


# ------------------------------------------------------------------
# AgentSkill
# ------------------------------------------------------------------

_SKILL_COLS = "id, agent_name, name, description, content, created_at"


def list_skills(agent_name: str) -> list[AgentSkill]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SKILL_COLS} FROM agent_skills WHERE agent_name = %s ORDER BY name ASC",
                (agent_name,),
            )
            return [AgentSkill.from_row(r) for r in cur.fetchall()]


def get_skill(name: str, agent_name: str) -> AgentSkill | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SKILL_COLS} FROM agent_skills WHERE name = %s AND agent_name = %s",
                (name, agent_name),
            )
            row = cur.fetchone()
            return AgentSkill.from_row(row) if row else None


def upsert_skill(skill: AgentSkill) -> AgentSkill:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_skills (agent_name, name, description, content)
                VALUES (%(agent_name)s, %(name)s, %(description)s, %(content)s)
                ON CONFLICT (name)
                DO UPDATE SET agent_name  = EXCLUDED.agent_name,
                              description = EXCLUDED.description,
                              content     = EXCLUDED.content
                RETURNING id, created_at
                """,
                skill.model_dump(include={"agent_name", "name", "description", "content"}),
            )
            row = cur.fetchone()
            return skill.model_copy(update={"id": row[0], "created_at": row[1]})


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
