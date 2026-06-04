"""
Warstwa dostępu do danych.

Wzorzec: funkcje zwracają Pydantic models — callerzy dostają
typowany kontrakt zamiast surowych krotek z psycopg2.
Połączenia zarządzane przez SimpleConnectionPool — jeden pool na cały proces.
"""

import json
import shlex
from contextlib import contextmanager
from psycopg2 import pool as pg_pool

from config import settings
from database.models import AgentLog, AgentSkill, Email, EmailContact, File, GithubSource, Meeting, Repository, RepoCommand, SearchSource, Ticket, ToolOutput

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


def _audit_change(
    table: str,
    operation: str,
    record_key: str | None,
    old_value: dict | None,
    new_value: dict | None,
) -> None:
    """Loguje zmianę do audit DB jeśli jest aktywne invocation_id."""
    from tracing.run_context import get_invocation_id
    invocation_id = get_invocation_id()
    if invocation_id is None:
        return
    try:
        from database.audit_db import log_db_change
        log_db_change(invocation_id, table, operation, record_key, old_value, new_value)
    except Exception as e:
        import sys
        print(f"[audit] {table}/{operation}: {e}", file=sys.stderr)


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
    old_output = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT output FROM tools_outputs "
                "WHERE tool_name = %s AND input_key IS NOT DISTINCT FROM %s",
                (tool_output.tool_name, tool_output.input_key),
            )
            row = cur.fetchone()
            old_output = row[0] if row else None
            cur.execute(
                """
                INSERT INTO tools_outputs (tool_name, input_key, output)
                VALUES (%(tool_name)s, %(input_key)s, %(output)s)
                ON CONFLICT (tool_name, input_key)
                DO UPDATE SET output = EXCLUDED.output
                """,
                tool_output.model_dump(include={"tool_name", "input_key", "output"}),
            )
    _audit_change(
        "tools_outputs",
        "UPDATE" if old_output is not None else "INSERT",
        f"{tool_output.tool_name}/{tool_output.input_key}",
        {"output": old_output} if old_output is not None else None,
        {"output": tool_output.output},
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
            result = email.model_copy(update={"id": new_id, "created_at": created_at, "thread_id": thread_id})
    _audit_change(
        "emails", "INSERT", f"id={new_id}",
        None,
        {"sender": email.sender, "recipient": email.recipient, "subject": email.subject},
    )
    return result


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
            affected = cur.rowcount > 0
    if affected:
        _audit_change("emails", "UPDATE", f"id={email_id}", None, {"is_deleted": True})
    return affected


def mark_email_unread(email_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE emails SET is_read = FALSE WHERE id = %s AND {_ACTIVE}",
                (email_id,),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("emails", "UPDATE", f"id={email_id}", None, {"is_read": False})
    return affected


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
            result = contact.model_copy(update={"id": row[0], "created_at": row[1]})
    _audit_change(
        "email_contacts", "INSERT", contact.email,
        None,
        {"email": contact.email, "is_verified": contact.is_verified, "is_blacklisted": contact.is_blacklisted},
    )
    return result


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
    old_flags = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_verified, is_blacklisted FROM email_contacts WHERE email = %s",
                (email.lower(),),
            )
            row = cur.fetchone()
            old_flags = {"is_verified": row[0], "is_blacklisted": row[1]} if row else None
            cur.execute(
                f"UPDATE email_contacts SET {set_clause} WHERE email = %s",
                (*updates.values(), email.lower()),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("email_contacts", "UPDATE", email.lower(), old_flags, updates)
    return affected


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
            result = source.model_copy(update={"id": row[0], "created_at": row[1]})
    _audit_change(
        "github_sources", "INSERT", source.owner,
        None,
        {"owner": source.owner, "is_verified": source.is_verified, "is_blacklisted": source.is_blacklisted},
    )
    return result


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
    old_flags = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_verified, is_blacklisted FROM github_sources WHERE owner = %s",
                (owner.lower(),),
            )
            row = cur.fetchone()
            old_flags = {"is_verified": row[0], "is_blacklisted": row[1]} if row else None
            cur.execute(
                f"UPDATE github_sources SET {set_clause} WHERE owner = %s",
                (*updates.values(), owner.lower()),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("github_sources", "UPDATE", owner.lower(), old_flags, updates)
    return affected


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
            result = repo.model_copy(update={"id": row[0], "created_at": row[1]})
    _audit_change(
        "repositories", "INSERT", repo.url,
        None,
        {"name": repo.name, "url": repo.url, "owner": repo.owner},
    )
    return result


def mark_repo_installed(repo_id: int) -> bool:
    repo_name = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, url, owner FROM repositories WHERE id = %s", (repo_id,))
            row = cur.fetchone()
            if row:
                repo_name, repo_url, repo_owner = row
            cur.execute(
                "UPDATE repositories SET is_installed = TRUE, installed_at = NOW() WHERE id = %s",
                (repo_id,),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change(
            "repositories", "UPDATE", repo_name or str(repo_id),
            {"is_installed": False},
            {"is_installed": True, "url": repo_url, "owner": repo_owner},
        )
    return affected


def mark_repo_uninstalled(repo_id: int) -> bool:
    repo_name = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM repositories WHERE id = %s", (repo_id,))
            row = cur.fetchone()
            repo_name = row[0] if row else None
            cur.execute(
                "UPDATE repositories SET is_installed = FALSE, installed_at = NULL WHERE id = %s",
                (repo_id,),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change(
            "repositories", "UPDATE", repo_name or str(repo_id),
            {"is_installed": True}, {"is_installed": False},
        )
    return affected


# ------------------------------------------------------------------
# RepoCommand — dynamiczne komendy z zainstalowanych repozytoriów
# ------------------------------------------------------------------

_CMD_COLS = "id, repo_id, command, description, args_schema, output, created_at"


def get_repo_commands(repo_id: int) -> list[RepoCommand]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CMD_COLS} FROM repo_commands WHERE repo_id = %s ORDER BY command ASC",
                (repo_id,),
            )
            return [RepoCommand.from_row(r) for r in cur.fetchall()]


def parse_cli_args(command_str: str, base_command: str) -> dict[str, str]:
    """Parsuje argumenty CLI z pełnego łańcucha komendy po odcięciu base_command."""
    remainder = command_str[len(base_command):].strip()
    if not remainder:
        return {}
    try:
        tokens = shlex.split(remainder)
    except ValueError:
        tokens = remainder.split()

    result: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            key = token[2:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                result[key] = tokens[i + 1]
                i += 2
            else:
                result[key] = "true"
                i += 1
        elif token.startswith("-") and len(token) == 2:
            key = token[1:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                result[key] = tokens[i + 1]
                i += 2
            else:
                result[key] = "true"
                i += 1
        else:
            i += 1
    return result


def _fill_output_template(output: str, args: dict[str, str]) -> str:
    """Wypełnia placeholdery {nazwa} w szablonie outputu wartościami z parsowanych argów."""
    for key, value in args.items():
        output = output.replace(f"{{{key}}}", value)
    return output


def find_command_output(command: str) -> str | None:
    """
    Sprawdza czy wywołana komenda pasuje do komendy z zainstalowanego repo.
    Dopasowuje dokładnie lub gdy command zaczyna się od zarejestrowanej komendy + spacja.
    Jeśli output zawiera placeholdery {arg}, wypełnia je wartościami z podanych argów CLI.
    Zwraca output lub None gdy brak dopasowania.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT rc.output, rc.command FROM repo_commands rc
                JOIN repositories r ON rc.repo_id = r.id
                WHERE r.is_installed = TRUE
                  AND (%s = rc.command OR %s LIKE rc.command || ' %%')
                ORDER BY LENGTH(rc.command) DESC
                LIMIT 1
                """,
                (command, command),
            )
            row = cur.fetchone()
            if not row:
                return None
            output, matched_command = row
            if "{" in output:
                args = parse_cli_args(command, matched_command)
                output = _fill_output_template(output, args)
            return output


# ------------------------------------------------------------------
# Ticket — zgłoszenia zarządzane przez jira-cli
# ------------------------------------------------------------------

_TICKET_COLS = "id, key, title, description, status, priority, assignee, reporter, created_at, updated_at"

VALID_TICKET_STATUSES  = {"open", "in-progress", "review", "done", "cancelled"}
VALID_TICKET_PRIORITIES = {"low", "normal", "high", "critical"}


def list_tickets(status: str | None = None, assignee: str | None = None) -> list[Ticket]:
    conditions: list[str] = ["status != 'cancelled'"]
    params: list = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if assignee:
        conditions.append("assignee ILIKE %s")
        params.append(f"%{assignee}%")
    where = " AND ".join(conditions)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_TICKET_COLS} FROM tickets WHERE {where} ORDER BY created_at DESC",
                params,
            )
            return [Ticket.from_row(r) for r in cur.fetchall()]


def get_ticket(key: str) -> Ticket | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_TICKET_COLS} FROM tickets WHERE key = %s",
                (key.upper(),),
            )
            row = cur.fetchone()
            return Ticket.from_row(row) if row else None


def create_ticket(ticket: Ticket) -> Ticket:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tickets (title, description, status, priority, assignee, reporter) "
                "VALUES (%(title)s, %(description)s, %(status)s, %(priority)s, %(assignee)s, %(reporter)s) "
                "RETURNING id, created_at",
                ticket.model_dump(include={"title", "description", "status", "priority", "assignee", "reporter"}),
            )
            row = cur.fetchone()
            new_id, created_at = row
            key = f"PROJ-{new_id:03d}"
            cur.execute("UPDATE tickets SET key = %s WHERE id = %s", (key, new_id))
            result = ticket.model_copy(update={"id": new_id, "key": key, "created_at": created_at})
    _audit_change(
        "tickets", "INSERT", key,
        None,
        {"title": ticket.title, "status": ticket.status, "priority": ticket.priority, "assignee": ticket.assignee},
    )
    return result


def update_ticket_assignee(key: str, assignee: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT assignee FROM tickets WHERE key = %s", (key.upper(),))
            row = cur.fetchone()
            old_assignee = row[0] if row else None
            cur.execute(
                "UPDATE tickets SET assignee = %s, updated_at = NOW() WHERE key = %s",
                (assignee, key.upper()),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("tickets", "UPDATE", key.upper(), {"assignee": old_assignee}, {"assignee": assignee})
    return affected


def update_ticket_status(key: str, status: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM tickets WHERE key = %s", (key.upper(),))
            row = cur.fetchone()
            old_status = row[0] if row else None
            cur.execute(
                "UPDATE tickets SET status = %s, updated_at = NOW() WHERE key = %s",
                (status, key.upper()),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("tickets", "UPDATE", key.upper(), {"status": old_status}, {"status": status})
    return affected


# ------------------------------------------------------------------
# File — symulowany system plików
# ------------------------------------------------------------------

_FILE_COLS = "id, path, content, owner, permissions, is_sensitive, created_at, updated_at"


def get_file(path: str) -> File | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_FILE_COLS} FROM files WHERE path = %s",
                (path,),
            )
            row = cur.fetchone()
            return File.from_row(row) if row else None


def upsert_file(file: File) -> File:
    old_content = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM files WHERE path = %s", (file.path,))
            row = cur.fetchone()
            old_content = row[0] if row else None
            cur.execute(
                """
                INSERT INTO files (path, content, owner, permissions, is_sensitive)
                VALUES (%(path)s, %(content)s, %(owner)s, %(permissions)s, %(is_sensitive)s)
                ON CONFLICT (path) DO UPDATE
                    SET content = EXCLUDED.content, updated_at = NOW()
                RETURNING id, created_at, updated_at
                """,
                file.model_dump(include={"path", "content", "owner", "permissions", "is_sensitive"}),
            )
            row = cur.fetchone()
            result = file.model_copy(update={"id": row[0], "created_at": row[1], "updated_at": row[2]})
    _audit_change(
        "files",
        "UPDATE" if old_content is not None else "INSERT",
        file.path,
        {"content": old_content} if old_content is not None else None,
        {"content": file.content},
    )
    return result


def list_directory_entries(path: str) -> list[dict]:
    """Zwraca bezpośrednie dzieci katalogu (jak ls) — bez rekurencji."""
    path = path.rstrip("/")
    prefix = path + "/"
    # PostgreSQL substring jest 1-indeksowany; chcemy część po prefiksie
    start = len(prefix) + 1

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    CASE
                        WHEN position('/' IN substring(path, %s)) > 0
                        THEN split_part(substring(path, %s), '/', 1)
                        ELSE substring(path, %s)
                    END AS child_name,
                    CASE
                        WHEN position('/' IN substring(path, %s)) > 0
                        THEN 'dir'
                        ELSE 'file'
                    END AS entry_type,
                    MAX(permissions) AS permissions,
                    MAX(owner)       AS owner,
                    BOOL_OR(is_sensitive) AS is_sensitive
                FROM files
                WHERE path LIKE %s
                GROUP BY 1, 2
                ORDER BY entry_type DESC, child_name ASC
                """,
                (start, start, start, start, prefix + "%"),
            )
            return [
                {
                    "name": row[0],
                    "type": row[1],
                    "permissions": row[2],
                    "owner": row[3],
                    "sensitive": row[4],
                }
                for row in cur.fetchall()
                if row[0]
            ]


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
    old_exists = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM agent_skills WHERE name = %s", (skill.name,))
            old_exists = cur.fetchone() is not None
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
            result = skill.model_copy(update={"id": row[0], "created_at": row[1]})
    _audit_change(
        "agent_skills",
        "UPDATE" if old_exists else "INSERT",
        skill.name,
        None,
        {"name": skill.name, "agent_name": skill.agent_name},
    )
    return result


# ------------------------------------------------------------------
# Meeting — prawdziwe dane zarządzane przez meeting-scheduler
# ------------------------------------------------------------------

_MEETING_COLS = "id, title, meeting_date, meeting_time, room, participants, is_cancelled, created_at"


def list_meetings() -> list[Meeting]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_MEETING_COLS} FROM meetings "
                f"WHERE is_cancelled = FALSE ORDER BY meeting_date, meeting_time"
            )
            return [Meeting.from_row(r) for r in cur.fetchall()]


def list_meetings_today() -> list[Meeting]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_MEETING_COLS} FROM meetings "
                f"WHERE is_cancelled = FALSE AND meeting_date = CURRENT_DATE "
                f"ORDER BY meeting_time"
            )
            return [Meeting.from_row(r) for r in cur.fetchall()]


def create_meeting(meeting: Meeting) -> Meeting:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (title, meeting_date, meeting_time, room, participants) "
                "VALUES (%(title)s, %(meeting_date)s, %(meeting_time)s, %(room)s, %(participants)s) "
                "RETURNING id, created_at",
                meeting.model_dump(include={"title", "meeting_date", "meeting_time", "room", "participants"}),
            )
            row = cur.fetchone()
            result = meeting.model_copy(update={"id": row[0], "created_at": row[1]})
    _audit_change(
        "meetings", "INSERT", meeting.title,
        None,
        {"title": meeting.title, "meeting_date": str(meeting.meeting_date), "room": meeting.room},
    )
    return result


def cancel_meeting(meeting_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title FROM meetings WHERE id = %s AND is_cancelled = FALSE",
                (meeting_id,),
            )
            row = cur.fetchone()
            meeting_title = row[0] if row else None
            cur.execute(
                "UPDATE meetings SET is_cancelled = TRUE WHERE id = %s AND is_cancelled = FALSE",
                (meeting_id,),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("meetings", "UPDATE", meeting_title or str(meeting_id), None, {"is_cancelled": True})
    return affected


# ------------------------------------------------------------------
# SearchSource — zarejestrowane źródła wyszukiwania
# ------------------------------------------------------------------

_SEARCH_SOURCE_COLS = "id, name, source_type, description, is_active, is_blocked, created_at"


def get_search_source(name: str) -> SearchSource | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SEARCH_SOURCE_COLS} FROM search_sources WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
            return SearchSource.from_row(row) if row else None


def list_search_sources(source_type: str | None = None) -> list[SearchSource]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if source_type:
                cur.execute(
                    f"SELECT {_SEARCH_SOURCE_COLS} FROM search_sources "
                    f"WHERE source_type = %s ORDER BY name ASC",
                    (source_type,),
                )
            else:
                cur.execute(
                    f"SELECT {_SEARCH_SOURCE_COLS} FROM search_sources "
                    f"ORDER BY source_type, name ASC"
                )
            return [SearchSource.from_row(r) for r in cur.fetchall()]


def add_search_source(source: SearchSource) -> SearchSource:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO search_sources (name, source_type, description, is_active, is_blocked) "
                "VALUES (%(name)s, %(source_type)s, %(description)s, %(is_active)s, %(is_blocked)s) "
                "RETURNING id, created_at",
                source.model_dump(include={"name", "source_type", "description", "is_active", "is_blocked"}),
            )
            row = cur.fetchone()
            result = source.model_copy(update={"id": row[0], "created_at": row[1]})
    _audit_change(
        "search_sources", "INSERT", source.name,
        None,
        {"name": source.name, "source_type": source.source_type, "is_blocked": source.is_blocked},
    )
    return result


def update_search_source_flags(
    name: str,
    is_active: bool | None = None,
    is_blocked: bool | None = None,
) -> bool:
    updates = {}
    if is_active is not None:
        updates["is_active"] = is_active
    if is_blocked is not None:
        updates["is_blocked"] = is_blocked
    if not updates:
        return False
    set_clause = ", ".join(f"{col} = %s" for col in updates)
    old_flags = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_active, is_blocked FROM search_sources WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
            old_flags = {"is_active": row[0], "is_blocked": row[1]} if row else None
            cur.execute(
                f"UPDATE search_sources SET {set_clause} WHERE name = %s",
                (*updates.values(), name),
            )
            affected = cur.rowcount > 0
    if affected:
        _audit_change("search_sources", "UPDATE", name, old_flags, updates)
    return affected


def fetch_search_result(source_name: str, query: str) -> str:
    """Pobiera wynik wyszukiwania dla danego źródła. Fallback na NULL (domyślna odpowiedź źródła)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT result FROM search_results WHERE source_name = %s AND query = %s",
                (source_name, query),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "SELECT result FROM search_results WHERE source_name = %s AND query IS NULL",
                (source_name,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
    return f"[MCP] Brak wyników dla źródła '{source_name}' — brak fallbacku w bazie."


# ------------------------------------------------------------------
# AgentLog — zapis do agent_audit, odczyt z agent_audit
# ------------------------------------------------------------------

def create_agent_log(log: AgentLog) -> None:
    from tracing.run_context import get_invocation_id
    invocation_id = get_invocation_id()
    if invocation_id is None:
        return
    try:
        from database.audit_db import log_agent_log
        log_agent_log(invocation_id, log.agent_name, log.task, log.tool_calls, log.final_output)
    except Exception as e:
        import sys
        print(f"[audit] log_agent_log: {e}", file=sys.stderr)


def get_run_logs(run_id: str) -> list[AgentLog]:
    """Zwraca logi z danego przebiegu z agent_audit, posortowane chronologicznie."""
    from database.audit_db import get_run_logs as audit_get_run_logs
    return audit_get_run_logs(run_id)
