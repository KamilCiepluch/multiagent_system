"""Minimal agent system: chat + search behind one router, sharing conversation memory.

A tiny two-agent pipeline that shows the pieces working together:
  - a per-turn LLM router decides whether a message needs a knowledge lookup ('search') or is
    ordinary conversation ('chat');
  - ConversationAgent handles chat and owns the multi-turn memory (a ConversationStore);
  - SearchSimAgent handles lookups against the fake_internet world.

Both write to the SAME ConversationStore, so search answers become part of the dialogue history
and later chat turns stay consistent (e.g. "what did you just tell me?").

Run:  python -m interactive.mini_system
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.conversation_agent import ConversationAgent
from agents.conversation_store import InMemoryConversationStore
from agents.search_sim_agent import build_search_sim_agent
from llm_factory import build_system_llm

_ROUTE_PROMPT = (
    "You route a message inside a small assistant. Reply with EXACTLY one word:\n"
    "- search : the answer needs looking up facts or knowledge (a topic, definition, figure, or a "
    "what/why/how question about the world).\n"
    "- chat   : greetings, small talk, opinions, or anything about the ongoing conversation itself.\n"
    "Answer with only 'search' or 'chat'."
)


class MiniAgentSystem:
    """chat + search with a shared conversation memory and a one-word router."""

    def __init__(self, llm=None, *, conversation_id: str = "default"):
        self.llm = llm or build_system_llm()
        self.store = InMemoryConversationStore()
        self.chat_agent = ConversationAgent(self.llm, {}, store=self.store)
        self.search_agent = build_search_sim_agent(self.llm)
        self.conversation_id = conversation_id

    def route(self, message: str) -> str:
        resp = self.llm.invoke([SystemMessage(content=_ROUTE_PROMPT), HumanMessage(content=f"Message: {message}")])
        decision = (resp.content or "").strip().lower()
        return "search" if "search" in decision else "chat"

    def ask(self, message: str) -> tuple[str, str]:
        """Route one user turn and return (route, answer). Both routes update shared memory."""
        route = self.route(message)
        if route == "search":
            answer = self.search_agent.run(message)
            # fold the search turn into the shared conversation memory
            history = self.store.load(self.conversation_id)
            history += [HumanMessage(content=message), AIMessage(content=answer)]
            self.store.save(self.conversation_id, history)
        else:
            answer = self.chat_agent.chat(message, conversation_id=self.conversation_id)
        return route, answer

    def history(self):
        return self.store.load(self.conversation_id)

    def reset(self) -> None:
        self.store.reset(self.conversation_id)


def _repl() -> None:
    system = MiniAgentSystem()
    print("Mini agent system (chat + search). Commands: /reset  /history  /exit")
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
        route, answer = system.ask(line)
        print(f"[{route}] {answer}")


if __name__ == "__main__":
    _repl()
