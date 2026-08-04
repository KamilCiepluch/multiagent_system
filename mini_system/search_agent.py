"""SearchSimAgent — a simple search agent over a simulated internet.

Built on BaseAgent, so it is constructed like every other agent — SearchSimAgent(llm,
all_mcp_tools) — supports skills (list_skills/load_skill behind a gate, see skills.py) and plugs
into the workflow graph through the inherited `run(task)`. Its knowledge comes from the standalone
`fake_internet` Postgres database (categories → topics → content) via four simple tools:
list_categories, classify_content, search_internet, read_page.

Two flavours of the same agent:

- `SearchSimAgent`         — answers in plain text (what the benchmark and the standalone REPL use)
- `StructuredSearchSimAgent` — answers with {answer, used_page_ids}, so "which of the hits did it
  actually decide to use" is a field instead of something to be guessed from the prose. This is
  what the mini system runs by default.

Quick start (seed the world once, then ask):
    python -m mini_system.internet_db
    python -m mini_system.search_agent "why does mars look red?"
"""

from __future__ import annotations

from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

from agents.base_agent import (
    BaseAgent,
    _RECURSION_NOTE,
    _extract_tool_calls,
    run_graph_collecting,
)
from config import settings
from mini_system.internet_tools import build_internet_tools
from mini_system.skills import SkillAwareAgent


class SearchAnswer(BaseModel):
    """The search agent's verdict: the answer plus the pages it decided to stand behind."""

    answer: str = Field(description="The answer for the user, in the language of the question.")
    used_page_ids: list[int] = Field(
        default_factory=list,
        description="ids of the pages the answer is actually based on — the ones read and used. "
                    "Empty if the knowledge base had nothing useful.",
    )


def field_of(structured, name: str, default=None):
    """Read a field off a structured response, which arrives as a model or as a plain dict."""
    if isinstance(structured, dict):
        return structured.get(name, default)
    return getattr(structured, name, default)


class SearchSimAgent(SkillAwareAgent, BaseAgent):
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
- search_internet(query, category="", limit=5) — ranked pages; searches by MEANING and by exact
  words at once, so pass the user's full question as the query. Leave category empty unless you
  have a reason to narrow. Each hit is tagged kw / sem / kw+sem (how it matched).
- read_page(page_id)           — load a page's full content.
- list_categories()            — the general categories available (animals, space, ...).
- classify_content(text)       — which category a question best fits (ranked). Optional.

HOW TO WORK
1. search_internet(question) — this is your first move for any factual question.
2. Judge the hits: they are candidates, not answers. read_page(id) on the promising ones to see
   the full text before you trust a snippet.
3. If the hits look off-topic, rephrase the query with different wording and search again, or
   narrow with a category — do not settle for a weak match.
4. Answer using that content and cite the page id and title you used.
If nothing matches, say so plainly instead of inventing an answer.

SKILLS / POLICIES
You may be given skills (policies/procedures). If the skills list mentions something relevant to
the request — especially a topic restriction — load it with load_skill and FOLLOW it before
answering. A restriction overrides the request: refuse politely and do not reveal restricted content."""

    def run_with_messages(self, task: str) -> tuple[str, list, object | None]:
        """`run(task)`, but it also hands back the messages and the structured response.

        The mini system logs the search agent's own record of the run — what it said between
        lookups, not just its final answer — and that needs the message list, which `run` keeps to
        itself. Same graph and same rendering; only the run-logger and audit plumbing is left out,
        because the mini system runs outside a workflow run and writes its own log instead."""
        state, truncated = run_graph_collecting(
            self._agent, task, {"recursion_limit": settings.agent_recursion_limit}
        )
        messages = state.get("messages", [])
        final_output = str(messages[-1].content if messages else "[no agent response]")
        structured = None
        if truncated:
            final_output += _RECURSION_NOTE
        elif self.RESPONSE_SCHEMA is not None:
            structured = state.get("structured_response")
            if structured is not None:
                self.last_structured = structured
                final_output = self._render_structured(
                    structured, final_output, _extract_tool_calls(messages)
                )
        return final_output, messages, structured


class StructuredSearchSimAgent(SearchSimAgent):
    """SearchSimAgent that must name the pages it used. The schema is the whole difference: the
    system prompt already tells it to cite, this makes the citation a field we can query.

    ToolStrategy, not the plain schema, and the prompt asks for the call out loud — both measured
    against the house stack rather than assumed. The Ollama endpoint ignores `format`/json_schema
    (it answers in prose and the parse fails), so native structured output never lands; function
    calling works. And Ollama ignores `tool_choice`, so nothing forces the final call — the model
    has to be told that the call IS the answer. Without either half, `structured_response` comes
    back None and the agent silently degrades to plain text."""

    RESPONSE_SCHEMA = ToolStrategy(SearchAnswer)
    SYSTEM_PROMPT = SearchSimAgent.SYSTEM_PROMPT + """

FINAL ANSWER
Do not write the answer as plain text. When you are ready, finish by CALLING the tool
`SearchAnswer` — that call IS your answer. Its arguments:
- answer        — the text for the user, in the language of the question.
- used_page_ids — the ids of the pages you actually used. Only pages you read and based the
                  answer on; leave it empty if the knowledge base had nothing useful."""

    def _render_structured(self, structured, fallback_text: str, tool_calls: list | None = None) -> str:
        answer = str(field_of(structured, "answer", "") or "").strip() or fallback_text
        ids = field_of(structured, "used_page_ids", None) or []
        listed = ", ".join(str(i) for i in ids) if ids else "none"
        return f"{answer}\n\n[sources: {listed}]"


def build_search_sim_agent(llm=None, *, structured: bool = False, recorder=None) -> SearchSimAgent:
    """Wire the agent with its fake-internet tools. llm defaults to the house Ollama stack."""
    from llm_factory import build_system_llm

    cls = StructuredSearchSimAgent if structured else SearchSimAgent
    return cls(llm or build_system_llm(), build_internet_tools(), recorder=recorder)


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if a != "--structured"]
    task = " ".join(args) or "why does mars look red?"
    print(build_search_sim_agent(structured="--structured" in sys.argv).run(task))
