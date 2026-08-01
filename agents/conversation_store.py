"""Conversation history storage — a swappable source of conversation for the chat agent.

The agent depends only on the ConversationStore interface, never on a concrete backend, so
the source of a conversation can be replaced later (a DB-, Redis- or file-backed store) by
implementing the same three methods — without touching the agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.messages import BaseMessage


class ConversationStore(ABC):
    """Loads and persists per-conversation message history, keyed by conversation_id."""

    @abstractmethod
    def load(self, conversation_id: str) -> list[BaseMessage]:
        """Full message history of a conversation (empty list if unknown)."""

    @abstractmethod
    def save(self, conversation_id: str, messages: list[BaseMessage]) -> None:
        """Replace the stored history of a conversation with `messages`."""

    @abstractmethod
    def reset(self, conversation_id: str) -> None:
        """Forget a conversation entirely (start a new one)."""


class InMemoryConversationStore(ConversationStore):
    """Default backend — history lives in process memory, lost on restart."""

    def __init__(self):
        self._data: dict[str, list[BaseMessage]] = {}

    def load(self, conversation_id: str) -> list[BaseMessage]:
        return list(self._data.get(conversation_id, []))

    def save(self, conversation_id: str, messages: list[BaseMessage]) -> None:
        self._data[conversation_id] = list(messages)

    def reset(self, conversation_id: str) -> None:
        self._data.pop(conversation_id, None)
