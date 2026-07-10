"""
Fabryka LLM systemu docelowego (agenci/supervisor) — lokalny stack Ollama.

Budowa modelu w jednym miejscu: cały system testujemy zmieniając konfigurację
(model, temperatura, num_ctx), a nie logikę agentów.
"""

from __future__ import annotations

from config import settings


def build_system_llm(*, temperature: float | None = None, reasoning: bool | None = None):
    """Zwraca LLM agentów/supervisora (ChatOllama).

    temperature: None → `settings.agent_temperature`.
    reasoning:   None → `settings.capture_thinking`."""
    from langchain_ollama import ChatOllama

    temp = settings.agent_temperature if temperature is None else temperature
    reason = settings.capture_thinking if reasoning is None else reasoning
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        reasoning=reason,
        temperature=temp,
    )
