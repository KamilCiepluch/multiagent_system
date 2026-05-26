"""
MCP Client — adapter między MCPServer a LangChain.

Pobiera narzędzia z serwera i zwraca je jako LangChain @tool,
gotowe do podania do create_react_agent.
Agenci nigdy nie wywołują bazy bezpośrednio — zawsze przez serwer.
"""

from langchain_core.tools import tool as lc_tool
from mcp.server import MCPServer


def build_langchain_tools(server: MCPServer) -> list:
    """
    Zwraca listę LangChain tools opartych o MCPServer.
    Każda funkcja deleguje wywołanie do server.call_tool —
    zmiana na serwerze (lub w DB) natychmiast dotyczy wszystkich agentów.
    """

    @lc_tool
    def execute_command(command: str) -> str:
        """Wykonaj polecenie w terminalu i zwróć jego output."""
        return server.call_tool("execute_command", {"command": command})

    @lc_tool
    def web_search(query: str) -> str:
        """Wyszukaj informacje w internecie."""
        return server.call_tool("web_search", {"query": query})

    @lc_tool
    def read_file(path: str) -> str:
        """Odczytaj zawartość pliku pod podaną ścieżką."""
        return server.call_tool("read_file", {"path": path})

    @lc_tool
    def write_file(path: str, content: str) -> str:
        """Zapisz treść do pliku pod podaną ścieżką."""
        return server.call_tool("write_file", {"path": path, "content": content})

    @lc_tool
    def list_emails() -> str:
        """Wylistuj wszystkie maile w skrzynce."""
        return server.call_tool("list_emails", {})

    @lc_tool(description="Odczytaj treść maila o podanym ID.")
    def read_email(email_id: int) -> str:
        """Odczytaj treść maila o podanym ID.
        """
        return server.call_tool("read_email", {"email_id": email_id})

    @lc_tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Wyślij email do podanego odbiorcy."""
        return server.call_tool("send_email", {"to": to, "subject": subject, "body": body})

    return [
        execute_command,
        web_search,
        read_file,
        write_file,
        list_emails,
        read_email,
        send_email,
    ]
