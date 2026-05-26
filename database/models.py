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
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "Email":
        return cls(
            id=row[0], sender=row[1], recipient=row[2],
            subject=row[3], body=row[4], is_read=row[5], created_at=row[6],
        )

    def as_preview(self) -> str:
        """Skrócony widok do listy maili."""
        status = "przeczytany" if self.is_read else "nowy"
        return f"[{self.id}] Od: {self.sender} | Temat: {self.subject} | {status}"

    def as_full(self) -> str:
        """Pełna treść maila."""
        return (
            f"Od: {self.sender}\nDo: {self.recipient}\n"
            f"Temat: {self.subject}\nData: {self.created_at}\n\n{self.body}"
        )


class AgentLog(BaseModel):
    """Rekord z tabeli agent_logs — pełna historia wykonania agenta."""

    id: int | None = None
    agent_name: str
    task: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    final_output: str
    created_at: datetime | None = None
