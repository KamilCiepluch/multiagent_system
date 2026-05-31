"""
Rejestr prawdziwych handlerów komend wywoływanych przez execute_command.

Wzorzec dispatchu w mcp/server.py:
  1. dispatch(command) → real handler (prawdziwe operacje DB)
  2. find_command_output(command) → mock template z repo_commands
  3. fetch_tool_output("execute_command", ...) → ogólny fallback

Żeby dodać nowe repo z prawdziwymi handlerami: zaimportuj jego HANDLERS
i dodaj do _ALL_HANDLERS poniżej.
"""

from database.db import parse_cli_args
from commands.meeting_scheduler import HANDLERS as _MEETING_HANDLERS
from commands.jira_cli import HANDLERS as _JIRA_HANDLERS

_ALL_HANDLERS: dict[str, callable] = {
    **_MEETING_HANDLERS,
    **_JIRA_HANDLERS,
}


def dispatch(command: str) -> str | None:
    """
    Szuka najdłużej pasującego klucza w rejestrze i wywołuje handler.
    Zwraca None jeśli brak pasującego handlera — caller powinien użyć fallbacku.
    """
    best_key: str | None = None
    best_len = 0
    for key in _ALL_HANDLERS:
        if command == key or command.startswith(key + " "):
            if len(key) > best_len:
                best_key = key
                best_len = len(key)
    if best_key is None:
        return None
    args = parse_cli_args(command, best_key)
    return _ALL_HANDLERS[best_key](args)
