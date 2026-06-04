"""
Przechowuje run_id i invocation_id bieżącego przebiegu w ContextVar.

ContextVar działa per-wątek / per-task asyncio — bezpieczne przy LangGraph.
run_id: UUID przebiegu workflow (ustawiany przez workflow.py).
invocation_id: ID wywołania w ramach ataku (ustawiany przez AttackRunner).
"""

from contextvars import ContextVar

_current_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_current_invocation_id: ContextVar[int | None] = ContextVar("invocation_id", default=None)


def set_run_id(run_id: str) -> None:
    _current_run_id.set(run_id)


def get_run_id() -> str | None:
    return _current_run_id.get()


def set_invocation_id(invocation_id: int | None) -> None:
    _current_invocation_id.set(invocation_id)


def get_invocation_id() -> int | None:
    return _current_invocation_id.get()
