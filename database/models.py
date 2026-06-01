from datetime import datetime, date, time as time_type
from typing import Any
from pydantic import BaseModel, Field


class ToolOutput(BaseModel):
    """Rekord z tabeli tools_outputs — główny punkt infekcji MCP."""

    id: int | None = None
    tool_name: str
    input_key: str | None = None   # NULL = fallback dla każdego inputu narzędzia
    output: str
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "ToolOutput":
        return cls(id=row[0], tool_name=row[1], input_key=row[2], output=row[3], created_at=row[4])


class Email(BaseModel):
    """Rekord z tabeli emails — wektor ataku przez skrzynkę."""

    id: int | None = None
    sender: str
    recipient: str = "agent@system.local"
    subject: str | None = None
    body: str | None = None
    is_read: bool = False
    is_deleted: bool = False
    thread_id: int | None = None
    in_reply_to: int | None = None
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "Email":
        return cls(
            id=row[0], sender=row[1], recipient=row[2],
            subject=row[3], body=row[4], is_read=row[5], is_deleted=row[6],
            thread_id=row[7], in_reply_to=row[8], created_at=row[9],
        )

    def as_preview(self) -> str:
        status = "przeczytany" if self.is_read else "nowy"
        return f"[{self.id}] Od: {self.sender} | Temat: {self.subject} | {status}"

    def as_full(self) -> str:
        return (
            f"Od: {self.sender}\nDo: {self.recipient}\n"
            f"Temat: {self.subject}\nData: {self.created_at}\n\n{self.body}"
        )

    def as_thread_entry(self) -> str:
        reply_marker = f" (odpowiedź na #{self.in_reply_to})" if self.in_reply_to else ""
        return (
            f"--- #{self.id}{reply_marker} | {self.created_at} ---\n"
            f"Od: {self.sender} → Do: {self.recipient}\n"
            f"{self.body}"
        )


class EmailContact(BaseModel):
    """Rekord z tabeli email_contacts — lista zaufanych i zablokowanych adresów."""

    id: int | None = None
    email: str
    name: str | None = None
    is_verified: bool = False
    is_blacklisted: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "EmailContact":
        return cls(
            id=row[0], email=row[1], name=row[2],
            is_verified=row[3], is_blacklisted=row[4], created_at=row[5],
        )

    def as_summary(self) -> str:
        flags = []
        if self.is_verified:
            flags.append("zweryfikowany")
        if self.is_blacklisted:
            flags.append("CZARNA LISTA")
        if not flags:
            flags.append("brak flag")
        label = f" ({self.name})" if self.name else ""
        return f"{self.email}{label} — {', '.join(flags)}"


class AgentSkill(BaseModel):
    """Rekord z tabeli agent_skills — procedura obsługi zadania dla agenta."""

    id: int | None = None
    agent_name: str
    name: str
    description: str
    content: str
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "AgentSkill":
        return cls(
            id=row[0], agent_name=row[1], name=row[2],
            description=row[3], content=row[4], created_at=row[5],
        )


class AgentLog(BaseModel):
    """Rekord z tabeli agent_logs — pełna historia wykonania agenta."""

    id: int | None = None
    agent_name: str
    task: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    final_output: str
    created_at: datetime | None = None


class GithubSource(BaseModel):
    """Rekord z tabeli github_sources — zweryfikowane lub zablokowane konta GitHub."""

    id: int | None = None
    owner: str
    display_name: str | None = None
    is_verified: bool = False
    is_blacklisted: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "GithubSource":
        return cls(
            id=row[0], owner=row[1], display_name=row[2],
            is_verified=row[3], is_blacklisted=row[4], created_at=row[5],
        )

    def as_summary(self) -> str:
        flags = []
        if self.is_verified:
            flags.append("zweryfikowany")
        if self.is_blacklisted:
            flags.append("CZARNA LISTA")
        if not flags:
            flags.append("nieznany")
        label = f" ({self.display_name})" if self.display_name else ""
        return f"github/{self.owner}{label} — {', '.join(flags)}"


class Repository(BaseModel):
    """Rekord z tabeli repositories — symulowane repo do klonowania i budowania."""

    id: int | None = None
    name: str
    url: str
    owner: str
    description: str | None = None
    is_installed: bool = False
    installed_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "Repository":
        return cls(
            id=row[0], name=row[1], url=row[2], owner=row[3],
            description=row[4], is_installed=row[5], installed_at=row[6],
            created_at=row[7],
        )

    def as_summary(self) -> str:
        status = "zainstalowane" if self.is_installed else "sklonowane (nie zbudowane)"
        ts = f", zainstalowano: {self.installed_at.strftime('%Y-%m-%d %H:%M')}" if self.installed_at else ""
        desc = f" — {self.description}" if self.description else ""
        return f"[{self.id}] {self.name} ({self.url}){desc} | status: {status}{ts}"


class Meeting(BaseModel):
    """Rekord z tabeli meetings — spotkanie zarządzane przez meeting-scheduler."""

    id: int | None = None
    title: str
    meeting_date: date
    meeting_time: time_type
    room: str | None = None
    participants: str | None = None
    is_cancelled: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "Meeting":
        return cls(
            id=row[0], title=row[1], meeting_date=row[2], meeting_time=row[3],
            room=row[4], participants=row[5], is_cancelled=row[6], created_at=row[7],
        )

    def as_summary(self) -> str:
        room = self.room or "—"
        participants = self.participants or "—"
        cancelled = " [ANULOWANE]" if self.is_cancelled else ""
        date_str = self.meeting_date.strftime("%Y-%m-%d")
        time_str = self.meeting_time.strftime("%H:%M")
        return f"[{self.id}] {date_str} {time_str} | {self.title} | {room} | Uczestnicy: {participants}{cancelled}"


class Ticket(BaseModel):
    """Rekord z tabeli tickets — zgłoszenie zarządzane przez jira-cli."""

    id: int | None = None
    key: str | None = None
    title: str
    description: str | None = None
    status: str = "open"
    priority: str = "normal"
    assignee: str | None = None
    reporter: str = "agent@system.local"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "Ticket":
        return cls(
            id=row[0], key=row[1], title=row[2], description=row[3],
            status=row[4], priority=row[5], assignee=row[6], reporter=row[7],
            created_at=row[8], updated_at=row[9],
        )

    def as_row(self) -> str:
        priority_labels = {"low": "NISKI", "normal": "NORMALNY", "high": "WYSOKI", "critical": "KRYTYCZNY"}
        p_label = priority_labels.get(self.priority, self.priority.upper())
        assignee = self.assignee or "(nieprzypisane)"
        return f"{self.key:10} | [{p_label:8}] | {self.status:12} | {self.title[:36]:<36} | {assignee}"

    def as_full(self) -> str:
        lines = [
            f"=== {self.key} ===",
            f"Tytuł:       {self.title}",
            f"Status:      {self.status}",
            f"Priorytet:   {self.priority}",
            f"Przypisane:  {self.assignee or '(nieprzypisane)'}",
            f"Zgłaszający: {self.reporter}",
            f"Utworzone:   {self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '—'}",
        ]
        if self.description:
            lines += ["", "Opis:", self.description]
        return "\n".join(lines)


class SearchSource(BaseModel):
    """Rekord z tabeli search_sources — zarejestrowane źródła wyszukiwania."""

    id: int | None = None
    name: str
    source_type: str = "external"   # 'internal' | 'external'
    description: str | None = None
    is_active: bool = True
    is_blocked: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "SearchSource":
        return cls(
            id=row[0], name=row[1], source_type=row[2],
            description=row[3], is_active=row[4], is_blocked=row[5],
            created_at=row[6],
        )

    def as_summary(self) -> str:
        typ = "WEWNĘTRZNE" if self.source_type == "internal" else "ZEWNĘTRZNE"
        if self.is_blocked:
            status = "ZABLOKOWANE"
        elif not self.is_active:
            status = "nieaktywne"
        else:
            status = "aktywne"
        desc = f" — {self.description}" if self.description else ""
        return f"{self.name} [{typ}]{desc} | {status}"


class File(BaseModel):
    """Rekord z tabeli files — symulowany system plików agenta."""

    id: int | None = None
    path: str
    content: str = ""
    owner: str = "agent"
    permissions: str = "rw-r--r--"
    is_sensitive: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "File":
        return cls(
            id=row[0], path=row[1], content=row[2],
            owner=row[3], permissions=row[4], is_sensitive=row[5],
            created_at=row[6], updated_at=row[7],
        )


class RepoCommand(BaseModel):
    """Rekord z tabeli repo_commands — komenda dostępna po zainstalowaniu repo."""

    id: int | None = None
    repo_id: int
    command: str
    description: str | None = None
    args_schema: dict | None = None
    output: str
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "RepoCommand":
        return cls(
            id=row[0], repo_id=row[1], command=row[2],
            description=row[3], args_schema=row[4], output=row[5], created_at=row[6],
        )

    def as_summary(self) -> str:
        desc = f" — {self.description}" if self.description else ""
        result = f"  $ {self.command}{desc}"
        if self.args_schema:
            args_parts = []
            for flag, spec in self.args_schema.items():
                type_hint = spec.split(" — ")[0].strip() if " — " in spec else spec.strip()
                args_parts.append(f"{flag} <{type_hint}>")
            result += f"\n    Argumenty: {', '.join(args_parts)}"
        return result
