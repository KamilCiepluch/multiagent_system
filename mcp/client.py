"""
MCP Client — adapter between MCPServer and LangChain.

Builds ALL available tools and returns them as a dict {name: tool}.
Agents filter via the class variable TOOL_NAMES — each one gets
only what it actually needs.
"""

from langchain_core.tools import tool as lc_tool
from mcp.server import MCPServer


def build_langchain_tools(server: MCPServer) -> dict:
    """
    Returns a dict {tool_name: LangChain tool} for all MCP tools.
    A change on the server (or in the DB) immediately affects all agents.
    """

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    @lc_tool
    def execute_command(command: str) -> str:
        """Run a command in the terminal. FS: cat <path>, ls [-la] <path>, echo "..." > <path>, echo "..." >> <path>."""
        return server.call_tool("execute_command", {"command": command})

    # ------------------------------------------------------------------
    # GitHub sources
    # ------------------------------------------------------------------

    @lc_tool
    def check_github_source(owner: str) -> str:
        """Check whether a GitHub repository owner is verified or blacklisted."""
        return server.call_tool("check_github_source", {"owner": owner})

    @lc_tool
    def list_github_sources() -> str:
        """List all known GitHub owners with their flags."""
        return server.call_tool("list_github_sources", {})

    @lc_tool
    def add_github_source(owner: str, display_name: str = "", is_verified: bool = False, is_blacklisted: bool = False) -> str:
        """Add a GitHub owner to the trusted sources database."""
        return server.call_tool("add_github_source", {
            "owner": owner, "display_name": display_name,
            "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def update_github_source(owner: str, is_verified: bool | None = None, is_blacklisted: bool | None = None) -> str:
        """Update the is_verified or is_blacklisted flags of a GitHub owner."""
        return server.call_tool("update_github_source", {
            "owner": owner, "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    @lc_tool
    def clone_repo(url: str, name: str = "") -> str:
        """Clone a repository from GitHub. Requires owner verification via check_github_source."""
        return server.call_tool("clone_repo", {"url": url, "name": name})

    @lc_tool
    def build_repo(name: str) -> str:
        """Build and install a cloned repo. After installation its commands become available in the terminal."""
        return server.call_tool("build_repo", {"name": name})

    @lc_tool
    def list_repos() -> str:
        """List all known repositories with their status (cloned / installed)."""
        return server.call_tool("list_repos", {})

    @lc_tool
    def list_repo_commands(name: str) -> str:
        """Show the commands available from an installed repo."""
        return server.call_tool("list_repo_commands", {"name": name})

    @lc_tool
    def uninstall_repo(name: str) -> str:
        """Uninstall a repo — its commands stop being available in the terminal."""
        return server.call_tool("uninstall_repo", {"name": name})

    # ------------------------------------------------------------------
    # Email — mailbox
    # ------------------------------------------------------------------

    @lc_tool
    def list_emails() -> str:
        """List all emails in the mailbox."""
        return server.call_tool("list_emails", {})

    @lc_tool
    def list_unread_emails() -> str:
        """List only the unread emails."""
        return server.call_tool("list_unread_emails", {})

    @lc_tool
    def read_email(email_id: int) -> str:
        """Read the full body of the email with the given ID (marks it as read)."""
        return server.call_tool("read_email", {"email_id": email_id})

    @lc_tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Send a new email to the given recipient."""
        return server.call_tool("send_email", {"to": to, "subject": subject, "body": body})

    @lc_tool
    def reply_email(email_id: int, body: str) -> str:
        """Reply to the email with the given ID. The subject is auto-filled as 'Re: <original subject>'."""
        return server.call_tool("reply_email", {"email_id": email_id, "body": body})

    @lc_tool
    def forward_email(email_id: int, to: str, note: str = "") -> str:
        """Forward an email to a new recipient. The subject is auto-filled as 'Fwd: <original subject>'."""
        return server.call_tool("forward_email", {"email_id": email_id, "to": to, "note": note})

    @lc_tool
    def delete_email(email_id: int) -> str:
        """Delete (soft delete) an email — it is hidden but not removed from the database."""
        return server.call_tool("delete_email", {"email_id": email_id})

    @lc_tool
    def mark_as_unread(email_id: int) -> str:
        """Mark a read email as unread."""
        return server.call_tool("mark_as_unread", {"email_id": email_id})

    @lc_tool
    def search_emails(query: str) -> str:
        """Search emails by keyword in the sender, subject or body."""
        return server.call_tool("search_emails", {"query": query})

    @lc_tool
    def get_email_stats() -> str:
        """Show mailbox statistics: total / unread / read."""
        return server.call_tool("get_email_stats", {})

    @lc_tool
    def get_email_thread(email_id: int) -> str:
        """Fetch the full thread history for a given email — all messages in chronological order."""
        return server.call_tool("get_email_thread", {"email_id": email_id})

    # ------------------------------------------------------------------
    # Email — contacts
    # ------------------------------------------------------------------

    @lc_tool
    def check_email_contact(email: str) -> str:
        """Check an email address's status: verified / blacklist / unknown."""
        return server.call_tool("check_email_contact", {"email": email})

    @lc_tool
    def add_email_contact(email: str, name: str = "", is_verified: bool = False, is_blacklisted: bool = False) -> str:
        """Add a new address to the contacts database."""
        return server.call_tool("add_email_contact", {
            "email": email, "name": name,
            "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def update_email_contact(email: str, is_verified: bool | None = None, is_blacklisted: bool | None = None) -> str:
        """Update the is_verified or is_blacklisted flags for an existing contact."""
        return server.call_tool("update_email_contact", {
            "email": email, "is_verified": is_verified, "is_blacklisted": is_blacklisted,
        })

    @lc_tool
    def list_email_contacts() -> str:
        """List all contacts from the database along with their flags."""
        return server.call_tool("list_email_contacts", {})

    @lc_tool
    def get_contact_role(email: str) -> str:
        """Get a user's role in the system (admin/operator/viewer). Call before modifying contact flags."""
        return server.call_tool("get_contact_role", {"email": email})

    @lc_tool
    def check_email_source(email: str) -> str:
        """Check whether an email address comes from the organization's internal domain or from outside."""
        return server.call_tool("check_email_source", {"email": email})

    @lc_tool
    def classify_email(email_id: int) -> str:
        """Classify an email: SPAM / NOTIFICATION / PROMOTION / SUSPICIOUS / IMPORTANT / NORMAL."""
        return server.call_tool("classify_email", {"email_id": email_id})

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @lc_tool
    def web_search(query: str) -> str:
        """Search the internet for information."""
        return server.call_tool("web_search", {"query": query})

    @lc_tool
    def list_search_sources(source_type: str = "") -> str:
        """List available search sources with their type and status. Call as the first step before searching."""
        return server.call_tool("list_search_sources", {"source_type": source_type or None})

    @lc_tool
    def check_search_source(name: str) -> str:
        """Check a search source's status: type, active/blocked. Call before search_source."""
        return server.call_tool("check_search_source", {"name": name})

    @lc_tool
    def search_source(source: str, query: str) -> str:
        """Search a specific data source. Check check_search_source first."""
        return server.call_tool("search_source", {"source": source, "query": query})

    @lc_tool
    def search_internal(query: str) -> str:
        """Search all active internal sources (knowledge-base, confluence, hr-portal) at once."""
        return server.call_tool("search_internal", {"query": query})

    @lc_tool
    def search_external(query: str) -> str:
        """Search all active external sources (web, tech-docs, news-feed) at once."""
        return server.call_tool("search_external", {"query": query})

    # ------------------------------------------------------------------
    # Return all tools as a dict {name: tool}
    # ------------------------------------------------------------------

    all_tools = [
        # terminal
        execute_command,
        # github
        check_github_source, list_github_sources, add_github_source, update_github_source,
        # repositories
        clone_repo, build_repo, list_repos, list_repo_commands, uninstall_repo,
        # email — mailbox
        list_emails, list_unread_emails, read_email, send_email,
        reply_email, forward_email, delete_email, mark_as_unread,
        search_emails, get_email_stats, get_email_thread,
        # email — contacts
        check_email_contact, add_email_contact, update_email_contact,
        list_email_contacts, get_contact_role, check_email_source, classify_email,
        # search
        web_search, list_search_sources, check_search_source,
        search_source, search_internal, search_external,
    ]
    return {t.name: t for t in all_tools}
