"""Delivers an AttackVector to a real target LLM and captures its response.

Known gap: standard chat completion always generates a NEW turn after the last message — it
does not literally continue from a supplied trailing assistant message (the `prefill`
technique relies on exactly that). Most models will produce a fresh reply instead of
continuing the given prefix. Faithful prefill delivery needs a raw-completion call that
bypasses the chat template (model-specific) — not implemented yet. `TargetResponse.has_prefill`
flags when a vector relied on it, so a result can be interpreted correctly rather than assumed
to be a faithful prefill continuation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import AttackVector

_ROLE_TO_MESSAGE = {"user": "HumanMessage", "assistant": "AIMessage", "system": "SystemMessage"}


@dataclass
class TargetResponse:
    content: str
    has_prefill: bool  # see module docstring — a response to a prefill vector may not be faithful


def deliver(vector: AttackVector, llm) -> TargetResponse:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    role_map = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
    messages = [role_map[turn.role](content=turn.content) for turn in vector.turns]

    response = llm.invoke(messages)
    has_prefill = bool(vector.turns) and vector.turns[-1].role == "assistant"
    return TargetResponse(content=str(response.content), has_prefill=has_prefill)
