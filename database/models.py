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


class AgentLog(BaseModel):
    """Rekord z tabeli agent_logs — pełna historia wykonania agenta."""

    id: int | None = None
    agent_name: str
    task: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    final_output: str
    created_at: datetime | None = None
