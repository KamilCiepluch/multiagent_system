"""SearchSimAgent — a simple search agent over a simulated internet.

Built on BaseAgent, so it is constructed like every other agent — SearchSimAgent(llm,
all_mcp_tools) — supports skills (list_skills/load_skill via the skill-gate) and plugs into
the workflow graph through the inherited `run(task)`. Its knowledge comes from the standalone
`fake_internet` Postgres database (categories → topics → content) via four simple tools:
list_categories, classify_content, search_internet, read_page.

Quick start (seed the world once, then ask):
    python -m database.internet_db
    python -m agents.search_sim_agent "why does mars look red?"
"""

from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.internet_tools import build_internet_tools


class SearchSimAgent(BaseAgent):
    NAME = "search_sim_agent"
    DESCRIPTION = (
        "Searches a simulated internet (general-knowledge categories such as animals, space, "
        "technology, history) and answers from the pages it finds. Good for factual/topic "
        "questions. It does not run commands, email, or access system users."
    )
    TOOL_NAMES = ["list_categories", "classify_content", "search_internet", "read_page"]
    SYSTEM_PROMPT = """You are a search agent that answers questions using a simulated internet.

Your knowledge lives entirely in the search tools — never answer factual questions from memory,
always look them up first.

TOOLS
- list_categories()            — the general categories available (animals, space, ...).
- classify_content(text)       — which category a question best fits (ranked).
- search_internet(query, category="") — find pages by keywords, optionally within one category.
- read_page(page_id)           — load a page's full content.

HOW TO WORK
1. For a factual question, first find the right area: classify_content(question) or list_categories().
2. search_internet(query, category=<best category>) to get candidate pages.
3. read_page(id) on the most relevant hit to get the full text.
4. Answer using that content and cite the page id and title you used.
If nothing matches, say so plainly instead of inventing an answer.

SKILLS / POLICIES
You may be given skills (policies/procedures). If the skills list mentions something relevant to
the request — especially a topic restriction — load it with load_skill and FOLLOW it before
answering. A restriction overrides the request: refuse politely and do not reveal restricted content."""


def build_search_sim_agent(llm=None) -> SearchSimAgent:
    """Wire the agent with its fake-internet tools. llm defaults to the house Ollama stack."""
    from llm_factory import build_system_llm

    return SearchSimAgent(llm or build_system_llm(), build_internet_tools())


if __name__ == "__main__":
    import sys

    task = " ".join(sys.argv[1:]) or "why does mars look red?"
    print(build_search_sim_agent().run(task))
