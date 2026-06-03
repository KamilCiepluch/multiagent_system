"""
MCP Client — adapter między MCPServer a LangChain.

Buduje WSZYSTKIE dostępne narzędzia i zwraca je jako dict {name: tool}.
Agenci filtrują przez klasową zmienną TOOL_NAMES — każdy dostaje
tylko to, czego faktycznie potrzebuje.
"""

from langchain_core.tools import tool as lc_tool
from mcp.server import MCPServer


def build_langchain_tools(server: MCPServer) -> dict:
    """
    Zwraca dict {tool_name: LangChain tool} dla wszystkich narzędzi MCP.
    Zmiana na serwerze (lub w DB) natychmiast dotyczy wszystkich agentów.
    """

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    @lc_tool
    def execute_command(command: str) -> str:
        """Wykonaj polecenie w terminalu. FS: cat <path>, ls [-la] <path>, echo "..." > <path>, echo "..." >> <path>."""
        return server.call_tool("execute_command", {"command": command})

    # ------------------------------------------------------------------
    # GitHub sources
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Repozytoria
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Email — skrzynka
    # ------------------------------------------------------------------

    @lc_tool
    def list_emails() -> str:
        """Wylistuj wszystkie maile w skrzynce."""
        return server.call_tool("list_emails", {})

    @lc_tool
    def list_unread_emails() -> str:
        """Wylistuj tylko nieprzeczytane maile."""
        return server.call_tool("list_unread_emails", {})

    @lc_tool
    def read_email(email_id: int) -> str:
        """Odczytaj pełną treść maila o podanym ID (oznacza jako przeczytany)."""
        return server.call_tool("read_email", {"email_id": email_id})

    @lc_tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Wyślij nowy email do podanego odbiorcy."""
        return server.call_tool("send_email", {"to": to, "subject": subject, "body": body})

    @lc_tool
    def reply_email(email_id: int, body: str) -> str:
        """Odpowiedz na maila o podanym ID. Temat auto-uzupełni się jako 'Re: <oryginalny temat>'."""
        return server.call_tool("reply_email", {"email_id": email_id, "body": body})

    @lc_tool
    def forward_email(email_id: int, to: str, note: str = "") -> str:
        """Przekaż maila do nowego odbiorcy. Temat auto-uzupełni się jako 'Fwd: <oryginalny temat>'."""
        return server.call_tool("forward_email", {"email_id": email_id, "to": to, "note": note})

    @lc_tool
    def delete_email(email_id: int) -> str:
        """Usuń (soft delete) maila — zostanie ukryty, ale nie usunięty z bazy."""
        return server.call_tool("delete_email", {"email_id": email_id})

    @lc_tool
    def mark_as_unread(email_id: int) -> str:
        """Oznacz przeczytanego maila jako nieprzeczytanego."""
        return server.call_tool("mark_as_unread", {"email_id": email_id})

    @lc_tool
    def search_emails(query: str) -> str:
        """Wyszukaj maile po słowie kluczowym w nadawcy, temacie lub treści."""
        return server.call_tool("search_emails", {"query": query})

    @lc_tool
    def get_email_stats() -> str:
        """Pokaż statystyki skrzynki: łącznie / nieprzeczytane / przeczytane."""
        return server.call_tool("get_email_stats", {})

    @lc_tool
    def get_email_thread(email_id: int) -> str:
        """Pobierz pełną historię wątku dla podanego maila — wszystkie wiadomości chronologicznie."""
        return server.call_tool("get_email_thread", {"email_id": email_id})

    # ------------------------------------------------------------------
    # Email — kontakty
    # ------------------------------------------------------------------

    @lc_tool
    def check_email_contact(email: str) -> str:
        """Sprawdź status adresu email: zweryfikowany / czarna lista / nieznany."""
        return server.call_tool("check_email_contact", {"email": email})

    @lc_tool
    def add_email_contact(email: str, name: str = "", is_verified: bool = False, is_blacklisted: bool = False) -> str:
        """Dodaj nowy adres do bazy kontaktów."""
        return server.call_tool("add_email_contact", {
            "email": email, "name": name,
            "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def update_email_contact(email: str, is_verified: bool | None = None, is_blacklisted: bool | None = None) -> str:
        """Zaktualizuj flagi is_verified lub is_blacklisted dla istniejącego kontaktu."""
        return server.call_tool("update_email_contact", {
            "email": email, "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def list_email_contacts() -> str:
        """Wylistuj wszystkie kontakty z bazy wraz z ich flagami."""
        return server.call_tool("list_email_contacts", {})

    @lc_tool
    def get_contact_role(email: str) -> str:
        """Pobierz rolę użytkownika w systemie (admin/operator/viewer). Wywołaj przed modyfikacją flag kontaktów."""
        return server.call_tool("get_contact_role", {"email": email})

    @lc_tool
    def check_email_source(email: str) -> str:
        """Sprawdź czy adres email pochodzi z wewnętrznej domeny organizacji czy z zewnątrz."""
        return server.call_tool("check_email_source", {"email": email})

    @lc_tool
    def classify_email(email_id: int) -> str:
        """Sklasyfikuj maila: SPAM / POWIADOMIENIE / REKLAMA / PODEJRZANE / WAŻNA / NORMALNA."""
        return server.call_tool("classify_email", {"email_id": email_id})

    # ------------------------------------------------------------------
    # Wyszukiwanie
    # ------------------------------------------------------------------

    @lc_tool
    def web_search(query: str) -> str:
        """Wyszukaj informacje w internecie."""
        return server.call_tool("web_search", {"query": query})

    @lc_tool
    def list_search_sources(source_type: str = "") -> str:
        """Wylistuj dostępne źródła wyszukiwania z typem i statusem. Wywołaj jako pierwszy krok przed wyszukiwaniem."""
        return server.call_tool("list_search_sources", {"source_type": source_type or None})

    @lc_tool
    def check_search_source(name: str) -> str:
        """Sprawdź status źródła wyszukiwania: typ, aktywne/zablokowane. Wywołaj przed search_source."""
        return server.call_tool("check_search_source", {"name": name})

    @lc_tool
    def search_source(source: str, query: str) -> str:
        """Przeszukaj konkretne źródło danych. Sprawdź najpierw check_search_source."""
        return server.call_tool("search_source", {"source": source, "query": query})

    @lc_tool
    def search_internal(query: str) -> str:
        """Przeszukaj wszystkie aktywne wewnętrzne źródła (knowledge-base, confluence, hr-portal) jednocześnie."""
        return server.call_tool("search_internal", {"query": query})

    @lc_tool
    def search_external(query: str) -> str:
        """Przeszukaj wszystkie aktywne zewnętrzne źródła (web, tech-docs, news-feed) jednocześnie."""
        return server.call_tool("search_external", {"query": query})

    # ------------------------------------------------------------------
    # Zwróć wszystkie narzędzia jako dict {name: tool}
    # ------------------------------------------------------------------

    all_tools = [
        # terminal
        execute_command,
        # github
        check_github_source, list_github_sources, add_github_source, update_github_source,
        # repozytoria
        clone_repo, build_repo, list_repos, list_repo_commands, uninstall_repo,
        # email — skrzynka
        list_emails, list_unread_emails, read_email, send_email,
        reply_email, forward_email, delete_email, mark_as_unread,
        search_emails, get_email_stats, get_email_thread,
        # email — kontakty
        check_email_contact, add_email_contact, update_email_contact,
        list_email_contacts, get_contact_role, check_email_source, classify_email,
        # wyszukiwanie
        web_search, list_search_sources, check_search_source,
        search_source, search_internal, search_external,
    ]
    return {t.name: t for t in all_tools}
