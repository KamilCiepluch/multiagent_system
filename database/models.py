from datetime import datetime
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


class RepoCommand(BaseModel):
    """Rekord z tabeli repo_commands — komenda dostępna po zainstalowaniu repo."""

    id: int | None = None
    repo_id: int
    command: str
    description: str | None = None
    output: str
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "RepoCommand":
        return cls(
            id=row[0], repo_id=row[1], command=row[2],
            description=row[3], output=row[4], created_at=row[5],
        )

    def as_summary(self) -> str:
        desc = f" — {self.description}" if self.description else ""
        return f"  $ {self.command}{desc}"
