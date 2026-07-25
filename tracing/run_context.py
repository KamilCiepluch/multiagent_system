"""
Przechowuje kontekst bieżącego przebiegu w ContextVar.

ContextVar działa per-wątek / per-task asyncio — bezpieczne przy LangGraph.
run_id:        UUID przebiegu workflow (ustawiany przez workflow.py).
invocation_id: ID wywołania w ramach ataku (ustawiany przez AttackRunner) — forensika ataków.
run_logger:    aktywny RunLogger przebiegu (obserwowalność, baza agent_logs).
agent_invocation_id: ID bieżącego wywołania agenta w bazie logów — stos zagnieżdżenia
                     (supervisor → agent podrzędny). Pozwala przypisać tool calle,
                     skille i zmiany DB do właściwego agenta.
"""

from contextvars import ContextVar
from typing import Any

_current_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_current_invocation_id: ContextVar[int | None] = ContextVar("invocation_id", default=None)
_current_run_logger: ContextVar[Any] = ContextVar("run_logger", default=None)
_current_agent_invocation: ContextVar[int | None] = ContextVar("agent_invocation_id", default=None)


def set_run_id(run_id: str) -> None:
    _current_run_id.set(run_id)


def get_run_id() -> str | None:
    return _current_run_id.get()


def set_invocation_id(invocation_id: int | None) -> None:
    _current_invocation_id.set(invocation_id)


def get_invocation_id() -> int | None:
    return _current_invocation_id.get()


# ------------------------------------------------------------------
# RunLogger (obserwowalność — baza agent_logs)
# ------------------------------------------------------------------

def set_run_logger(logger: Any) -> None:
    _current_run_logger.set(logger)


def get_run_logger() -> Any:
    return _current_run_logger.get()


# ------------------------------------------------------------------
# Stos zagnieżdżenia agentów — bieżące wywołanie agenta w bazie logów
# ------------------------------------------------------------------

def set_current_agent_invocation(invocation_id: int | None):
    """Ustawia bieżące wywołanie agenta; zwraca token do przywrócenia (reset)."""
    return _current_agent_invocation.set(invocation_id)


def get_current_agent_invocation() -> int | None:
    return _current_agent_invocation.get()


def reset_current_agent_invocation(token) -> None:
    _current_agent_invocation.reset(token)
