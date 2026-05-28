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
    def list_directory(path: str = ".") -> str:
        """Wylistuj pliki i foldery w podanym katalogu (ls)."""
        return server.call_tool("list_directory", {"path": path})

    @lc_tool
    def check_github_source(owner: str) -> str:
        """Sprawdź czy właściciel repozytorium GitHub jest zweryfikowany lub na czarnej liście."""
        return server.call_tool("check_github_source", {"owner": owner})

    @lc_tool
    def list_github_sources() -> str:
        """Wylistuj wszystkich znanych właścicieli GitHub z ich flagami."""
        return server.call_tool("list_github_sources", {})

    @lc_tool
    def add_github_source(owner: str, display_name: str = "", is_verified: bool = False, is_blacklisted: bool = False) -> str:
        """Dodaj właściciela GitHub do bazy zaufanych źródeł."""
        return server.call_tool("add_github_source", {
            "owner": owner, "display_name": display_name,
            "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def update_github_source(owner: str, is_verified: bool | None = None, is_blacklisted: bool | None = None) -> str:
        """Zaktualizuj flagi is_verified lub is_blacklisted właściciela GitHub."""
        return server.call_tool("update_github_source", {
            "owner": owner, "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def clone_repo(url: str, name: str = "") -> str:
        """Sklonuj repozytorium z GitHub. Wymaga weryfikacji właściciela przez check_github_source."""
        return server.call_tool("clone_repo", {"url": url, "name": name})

    @lc_tool
    def build_repo(name: str) -> str:
        """Zbuduj i zainstaluj sklonowane repo. Po instalacji jego komendy stają się dostępne w terminalu."""
        return server.call_tool("build_repo", {"name": name})

    @lc_tool
    def list_repos() -> str:
        """Wylistuj wszystkie znane repozytoria z ich statusem (sklonowane / zainstalowane)."""
        return server.call_tool("list_repos", {})

    @lc_tool
    def list_repo_commands(name: str) -> str:
        """Pokaż komendy dostępne z zainstalowanego repo."""
        return server.call_tool("list_repo_commands", {"name": name})

    @lc_tool
    def uninstall_repo(name: str) -> str:
        """Odinstaluj repo — jego komendy przestają być dostępne w terminalu."""
        return server.call_tool("uninstall_repo", {"name": name})

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
        list_directory,
        check_github_source,
        list_github_sources,
        add_github_source,
        update_github_source,
        clone_repo,
        build_repo,
        list_repos,
        list_repo_commands,
        uninstall_repo,
        list_emails,
        read_email,
        send_email,
    ]
