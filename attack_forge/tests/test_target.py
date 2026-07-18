"""Tests for delivering an AttackVector to a target LLM. No live model — a fake chat client."""

from __future__ import annotations

from types import SimpleNamespace

from attack_forge.models import AttackVector, Turn
from attack_forge.target import deliver


class FakeChatModel:
    def __init__(self, content: str):
        self._content = content
        self.received_messages: list | None = None

    def invoke(self, messages):
        self.received_messages = messages
        return SimpleNamespace(content=self._content)


def test_deliver_maps_roles_and_returns_content():
    llm = FakeChatModel("the target's reply")
    vector = AttackVector(
        composition="stack",
        turns=[Turn(role="system", content="sys"), Turn(role="user", content="hi")],
    )
    response = deliver(vector, llm)

    assert response.content == "the target's reply"
    from langchain_core.messages import HumanMessage, SystemMessage
    assert [type(m) for m in llm.received_messages] == [SystemMessage, HumanMessage]
    assert [m.content for m in llm.received_messages] == ["sys", "hi"]


def test_deliver_flags_prefill_when_last_turn_is_assistant():
    vector = AttackVector(
        composition="stack",
        turns=[Turn(role="user", content="go"), Turn(role="assistant", content="Sure: ")],
    )
    response = deliver(vector, FakeChatModel("anything"))
    assert response.has_prefill is True


def test_deliver_no_prefill_flag_when_last_turn_is_user():
    vector = AttackVector(composition="single", turns=[Turn(role="user", content="go")])
    response = deliver(vector, FakeChatModel("anything"))
    assert response.has_prefill is False
