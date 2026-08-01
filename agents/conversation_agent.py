"""ConversationAgent — a multi-turn chat agent.

Built by extending StatefulAgent (BaseAgent + conversation memory), so it is constructed and
wired exactly like the other agents — `ConversationAgent(llm, all_mcp_tools)` — and its
inherited `run(task)` plugs straight into the workflow graph. Interactively it exposes
`chat()` / `history()` / `reset()` over a swappable conversation source.

Plain chat for now: no domain tools and no forced skill-gate. It can grow tools (via
TOOL_NAMES + MCP) or skills (re-enable the gate in _build_middleware) without further changes.
"""

from __future__ import annotations

from agents.stateful_agent import StatefulAgent


class ConversationAgent(StatefulAgent):
    NAME = "chat_agent"
    DESCRIPTION = (
        "Conversational assistant that holds a multi-turn dialogue with the user and remembers "
        "the conversation so far. General-purpose chat — it does not run commands, email or search."
    )
    SYSTEM_PROMPT = (
        "You are a helpful conversational assistant operating within a multi-agent system. "
        "You hold a multi-turn conversation with the user and remember what was said earlier in "
        "this dialogue. Answer in the user's language, concisely and to the point. If a request "
        "needs actions outside plain conversation (running commands, email, searching sources), "
        "say so plainly instead of pretending to perform them."
    )
    TOOL_NAMES: list[str] = []  # extend to give the chat agent MCP tools

    def _build_middleware(self) -> list:
        # Plain chat has no skills, so we skip the skill-gate that the task agents enforce.
        # Give this agent skills later? Return `super()._build_middleware()` to re-enable it.
        return []
