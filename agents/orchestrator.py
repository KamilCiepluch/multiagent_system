"""Orchestrator — a simple LLM router (no MCP tools): picks an agent for a task."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

ROUTING_PROMPT = """Your only job is to decide which agent should handle the given task.
Available agents:
- terminal  : running system commands, scripts, processes, file operations
- email     : reading, sending, managing email
- search    : searching for information, research

Answer with EXACTLY one word: terminal, email or search.
Do not add any other words or characters."""

VALID_ROUTES = {"terminal", "email", "search"}


class Orchestrator:
    def __init__(self, llm: ChatOllama):
        self.llm = llm

    def route(self, task: str) -> str:
        """Returns the name of the agent that should handle the task."""
        messages = [
            SystemMessage(content=ROUTING_PROMPT),
            HumanMessage(content=f"Task: {task}"),
        ]
        response = self.llm.invoke(messages)
        decision = response.content.strip().lower().split()[0]

        if decision not in VALID_ROUTES:
            return "search"
        return decision
