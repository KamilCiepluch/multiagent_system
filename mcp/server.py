"""
MCP Server — symulacja serwera MCP.

Centralny punkt infekcji: wszystkie narzędzia pobierają wyniki z tabeli
tools_outputs w PostgreSQL. Jedna zmiana w bazie zaraża każdego agenta
korzystającego z tego serwera.

Definicje narzędzi są statyczne (TOOL_DEFINITIONS), ale ich outputy
są w pełni kontrolowane przez bazę danych.
"""

from database.db import (
    fetch_tool_output,
    list_emails,
    get_email,
    create_email,
)
from database.models import Email

TOOL_DEFINITIONS = [
    {
        "name": "execute_command",
        "description": "Wykonaj polecenie w terminalu i zwróć jego output.",
        "args": {"command": "str — polecenie do wykonania"},
    },
    {
        "name": "web_search",
        "description": "Wyszukaj informacje w internecie.",
        "args": {"query": "str — zapytanie wyszukiwania"},
    },
    {
        "name": "read_file",
        "description": "Odczytaj zawartość pliku pod podaną ścieżką.",
        "args": {"path": "str — ścieżka do pliku"},
    },
    {
        "name": "write_file",
        "description": "Zapisz treść do pliku pod podaną ścieżką.",
        "args": {"path": "str — ścieżka", "content": "str — treść"},
    },
    {
        "name": "list_emails",
        "description": "Wylistuj wszystkie maile w skrzynce.",
        "args": {},
    },
    {
        "name": "read_email",
        "description": "Odczytaj treść maila o podanym ID.",
        "args": {"email_id": "int — ID maila"},
    },
    {
        "name": "send_email",
        "description": "Wyślij email do podanego odbiorcy.",
        "args": {"to": "str", "subject": "str", "body": "str"},
    },
]


class MCPServer:
    """
    Symulowany serwer MCP.
    Agenci pytają go o listę narzędzi i przez niego wywołują każde narzędzie.
    Wyniki zawsze idą przez bazę danych — to jest jedyny punkt ataku.
    """

    def list_tools(self) -> list[dict]:
        return TOOL_DEFINITIONS

    def call_tool(self, name: str, args: dict) -> str:
        if name == "execute_command":
            return fetch_tool_output("execute_command", args.get("command", ""))

        if name == "web_search":
            return fetch_tool_output("web_search", args.get("query", ""))

        if name == "read_file":
            return fetch_tool_output("read_file", args.get("path", ""))

        if name == "write_file":
            return fetch_tool_output(
                "write_file",
                f"{args.get('path', '')}:{args.get('content', '')[:40]}",
            )

        if name == "list_emails":
            emails = list_emails()
            if not emails:
                return "Skrzynka jest pusta."
            return "\n".join(e.as_preview() for e in emails)

        if name == "read_email":
            email = get_email(int(args.get("email_id", 0)))
            return email.as_full() if email else f"Email o ID {args.get('email_id')} nie istnieje."

        if name == "send_email":
            email = create_email(
                Email(
                    sender="agent@system.local",
                    recipient=args.get("to", ""),
                    subject=args.get("subject", ""),
                    body=args.get("body", ""),
                )
            )
            return f"Email wysłany (ID: {email.id}) do {email.recipient}."

        return f"[MCP] Nieznane narzędzie: '{name}'"
