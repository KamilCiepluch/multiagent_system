"""Tools for search_sim_agent — thin LangChain wrappers over the fake_internet database.

Returned as a dict {name: tool}, the same shape BaseAgent expects for `all_mcp_tools`, so the
agent picks them up by TOOL_NAMES exactly like MCP tools. Kept separate from mcp/client.py so
this quick search-world rig does not touch the shared MCP surface.
"""

from __future__ import annotations

import re
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool as lc_tool
from langgraph.prebuilt import InjectedState

from mini_system import internet_db as db

# A model that finds nothing useful tends to rephrase and search again, forever. These are the
# stops. Counted from the message history (the same trick BaseAgent uses for skills), so they
# need no external state and reset with every agent run.
MAX_SEARCHES = 4
# Containment, not Jaccard: a paraphrase loop swaps a couple of words while keeping the core
# ("… common reactions FOR EXAM PREPARATION" -> "… common reactions STUDY GUIDE"), which drags
# Jaccard down to ~0.5 even though it is plainly the same search. Measured against the shorter
# query, that pair scores 0.75.
SIMILAR_ENOUGH = 0.75
MIN_TOKENS_FOR_FUZZY = 3  # below this, only an identical query counts as a repeat


def _tokens(query: str) -> set[str]:
    return set(re.findall(r"\w+", query.lower()))


def _earlier_queries(messages: list, current_id: str) -> list[str]:
    out = []
    for msg in messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("name") == "search_internet" and tc.get("id") != current_id:
                out.append(str((tc.get("args") or {}).get("query", "")))
    return out


def _repeat_of(query: str, earlier: list[str]) -> str | None:
    """The earlier query this one is a rewording of, if any. Paraphrase loops rewrite a few
    words at a time, so exact matching would not catch them — compare token overlap."""
    now = _tokens(query)
    if not now:
        return None
    for prev in earlier:
        before = _tokens(prev)
        if not before:
            continue
        if min(len(now), len(before)) < MIN_TOKENS_FOR_FUZZY:
            # too short to judge by overlap — narrowing to one keyword is a real refinement
            if now == before:
                return prev
            continue
        if len(now & before) / min(len(now), len(before)) >= SIMILAR_ENOUGH:
            return prev
    return None


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
    def search_internet(
        query: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list, InjectedState("messages")],
        category: str = "",
        limit: int = 5,
    ) -> str:
        """Search the internet, best matches first. Understands meaning, not just exact words —
        ask it a full question in natural language. Category is an optional narrowing and is
        rarely needed. Returns ranked page ids, titles and snippets; each hit is tagged with how
        it matched: kw (exact words), sem (meaning), kw+sem (both — the strongest signal)."""
        earlier = _earlier_queries(messages, tool_call_id)
        if len(earlier) >= MAX_SEARCHES:
            return (
                f"Search limit reached ({MAX_SEARCHES} searches in this run). The knowledge base "
                f"has been queried enough. Answer from what you already found, or tell the user "
                f"the knowledge base has nothing on this topic. Do not search again."
            )
        repeated = _repeat_of(query, earlier)
        if repeated is not None:
            return (
                f"This is the same search as {repeated!r}, which you already ran — rewording it "
                f"returns the same pages. Either read_page(id) one of the hits you already have, "
                f"or conclude that the knowledge base does not cover this topic."
            )
        resolved = db.resolve_category(category)
        results = db.search(query, category=resolved, limit=max(1, min(int(limit), 10)))
        if not results:
            hints = []
            if category and resolved is None:
                hints.append(f"category '{category}' does not exist, so the whole world was searched")
            elif resolved:
                hints.append(f"searched only '{resolved}' — try again without a category")
            if any(ord(ch) > 127 for ch in query):
                hints.append("the pages are written in English — try an English query")
            hint = f" ({'; '.join(hints)})" if hints else " Try different wording."
            return f"No results for '{query}'.{hint}"
        if resolved:
            note = f"(narrowed to category '{resolved}')\n"
        elif category:
            note = f"(no such category '{category}' — searched every category instead)\n"
        else:
            note = ""
        return note + "\n".join(f"{i}. {p.as_result()}" for i, p in enumerate(results, 1))

    @lc_tool
    def read_page(page_id: int) -> str:
        """Load the full content of a page by its id (from search_internet results)."""
        page = db.get_page(int(page_id))
        if not page:
            return f"No page with id {page_id}."
        return page.as_full()

    tools = [list_categories, classify_content, search_internet, read_page]
    return {t.name: t for t in tools}
