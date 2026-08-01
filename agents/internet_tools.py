"""Tools for search_sim_agent — thin LangChain wrappers over the fake_internet database.

Returned as a dict {name: tool}, the same shape BaseAgent expects for `all_mcp_tools`, so the
agent picks them up by TOOL_NAMES exactly like MCP tools. Kept separate from mcp/client.py so
this quick search-world rig does not touch the shared MCP surface.
"""

from __future__ import annotations

from langchain_core.tools import tool as lc_tool

from database import internet_db as db


def build_internet_tools() -> dict:
    """Build the fake-internet tools as {name: LangChain tool}."""

    @lc_tool
    def list_categories() -> str:
        """List the general knowledge categories available on the internet, with page counts.
        Use it first to see what kinds of topics can be searched."""
        cats = db.list_categories()
        if not cats:
            return "No categories available (is the fake_internet database seeded?)."
        return "\n".join(f"- {name} ({n} pages)" for name, n in cats)

    @lc_tool
    def classify_content(text: str) -> str:
        """Decide which category a question or topic belongs to, ranked by relevance.
        Use it to pick the right category before searching."""
        ranked = db.classify(text)
        if not ranked:
            return "No matching category found."
        return "\n".join(f"{cat} (score {score})" for cat, score in ranked)

    @lc_tool
    def search_internet(query: str, category: str = "") -> str:
        """Search the internet for pages matching keywords. Optionally restrict to one category
        (from list_categories / classify_content). Returns matching page ids, titles and snippets."""
        results = db.search(query, category=category or None)
        if not results:
            scope = f" in category '{category}'" if category else ""
            return f"No results for '{query}'{scope}."
        return "\n".join(p.as_result() for p in results)

    @lc_tool
    def read_page(page_id: int) -> str:
        """Load the full content of a page by its id (from search_internet results)."""
        page = db.get_page(int(page_id))
        if not page:
            return f"No page with id {page_id}."
        return page.as_full()

    tools = [list_categories, classify_content, search_internet, read_page]
    return {t.name: t for t in tools}
