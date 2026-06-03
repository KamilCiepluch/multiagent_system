"""
Przechowuje run_id bieżącego przebiegu w ContextVar.

ContextVar działa per-wątek / per-task asyncio — bezpieczne przy LangGraph.
Ustawiany raz w workflow.py, odczytywany przez wszystkich agentów w trakcie
tego samego synchronicznego przebiegu.
"""

from contextvars import ContextVar

_current_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


def set_run_id(run_id: str) -> None:
    _current_run_id.set(run_id)


def get_run_id() -> str | None:
    return _current_run_id.get()
