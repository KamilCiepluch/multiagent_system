"""Minimal agent system: a chat agent with the research agent wired in AS A TOOL.

The chat agent is the host and owns the multi-turn memory. The search/research agent is exposed
to it as a single `research` tool; the chat model itself decides when a turn needs a lookup and
calls it (agent-as-tool — like a supervisor, but direct). No router, no skill-gate, no roles: this
is deliberately a bare agentic system, so it exercises the agent's own decision to search without
any infrastructure-security layer in the way.

Run:  python -m interactive.mini_system
"""

from __future__ import annotations

from langchain_core.tools import tool as lc_tool

from agents.conversation_agent import ConversationAgent
from agents.search_sim_agent import SearchSimAgent, build_search_sim_agent
from llm_factory import build_system_llm


def build_research_tool(search_agent: SearchSimAgent, call_log: list | None = None):
    """Wrap the search agent as a `research` tool. Each call optionally records its query in
    `call_log` so callers can see when the chat agent decided to look something up."""

    @lc_tool
    def research(query: str) -> str:
        """Look up factual information in the knowledge base (a simulated internet of general
        topics: animals, space, technology, history, plants, geography, and more). Use this
        whenever the user asks about facts, topics, definitions or data you should verify rather
        than guess. Returns a written answer with the sources it used."""
        if call_log is not None:
            call_log.append(query)
        return search_agent.run(query)

    return research


class ChatWithResearchAgent(ConversationAgent):
    """Chat agent whose only tool is `research` (the search agent). No skill tools, no gate —
    just conversation + the ability to look things up."""

    TOOL_NAMES = ["research"]
    SYSTEM_PROMPT = (
        "You are a helpful conversational assistant with a `research` tool that looks up facts in "
        "a knowledge base. Hold a multi-turn conversation and remember what was said earlier.\n"
        "When the user asks about facts, topics, definitions or anything you should verify rather "
        "than guess, call research(query) and answer using its result, keeping the sources it "
        "returns. For greetings, opinions, or talk about the conversation itself, just reply "
        "directly without the tool. Answer in the user's language, concisely."
    )

    def _build_skill_tools(self) -> list:
        # bare system: the only tool is `research`, no skills/skill-gate infrastructure
        return []


class MiniAgentSystem:
    """A chat agent that can call the research (search) agent as a tool. One shared history."""

    def __init__(self, llm=None, *, conversation_id: str = "default"):
        self.llm = llm or build_system_llm()
        self.search_agent = build_search_sim_agent(self.llm)
        self.research_log: list[str] = []
        research = build_research_tool(self.search_agent, self.research_log)
        self.chat_agent = ChatWithResearchAgent(self.llm, {"research": research})
        self.conversation_id = conversation_id

    def ask(self, message: str) -> tuple[str, list[str]]:
        """Send one turn. Returns (answer, research_queries) — the queries list is non-empty when
        the chat agent chose to call the research tool this turn."""
        self.research_log.clear()
        answer = self.chat_agent.chat(message, conversation_id=self.conversation_id)
        return answer, list(self.research_log)

    def history(self):
        return self.chat_agent.history(self.conversation_id)

    def reset(self) -> None:
        self.chat_agent.reset(self.conversation_id)


def _repl() -> None:
    system = MiniAgentSystem()
    print("Mini agent system — chat with a research tool. Commands: /reset  /history  /exit")
    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        if line == "/reset":
            system.reset()
            print("[new conversation]")
            continue
        if line == "/history":
            for m in system.history():
                print(f"  {type(m).__name__}: {m.content}")
            continue
        answer, researched = system.ask(line)
        tag = f" [researched: {researched}]" if researched else ""
        print(f"bot>{tag} {answer}")


if __name__ == "__main__":
    _repl()
