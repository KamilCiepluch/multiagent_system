"""Orchestrator — prosty router z LLM (bez narzędzi MCP): wybiera agenta dla zadania."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

ROUTING_PROMPT = """Twoim jedynym zadaniem jest zdecydować, który agent powinien obsłużyć podane zadanie.
Dostępni agenci:
- terminal  : wykonywanie poleceń systemowych, skrypty, procesy, operacje na plikach
- email     : czytanie, wysyłanie, zarządzanie pocztą
- search    : wyszukiwanie informacji, research

Odpowiedz TYLKO jednym słowem: terminal, email lub search.
Nie dodawaj żadnych innych słów ani znaków."""

VALID_ROUTES = {"terminal", "email", "search"}


class Orchestrator:
    def __init__(self, llm: ChatOllama):
        self.llm = llm

    def route(self, task: str) -> str:
        """Zwraca nazwę agenta który powinien obsłużyć zadanie."""
        messages = [
            SystemMessage(content=ROUTING_PROMPT),
            HumanMessage(content=f"Zadanie: {task}"),
        ]
        response = self.llm.invoke(messages)
        decision = response.content.strip().lower().split()[0]

        if decision not in VALID_ROUTES:
            return "search"
        return decision
