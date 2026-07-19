"""Tests for the data-driven LLM-task tools: the KB loads, each task becomes a tool, and the one
universal primitive runs a task with the model+params its spec declares (via a provider)."""

from __future__ import annotations

from types import SimpleNamespace

from attack_forge.llm_provider import ModelProvider, SingleModelProvider
from attack_forge.llm_tasks import DEFAULT_TASK_LIBRARY, LLMTask, LLMTaskLibrary, TASK_TOOLS
from attack_forge.tools import call_tool, known_tool_names


class _EchoLLM:
    """Records the system prompt it was called with and echoes a fixed reply."""

    def __init__(self, reply: str = "transformed"):
        self.reply = reply
        self.system_seen: str | None = None

    def invoke(self, messages):
        self.system_seen = messages[0].content
        return SimpleNamespace(content=self.reply)


def test_kb_loads_expected_tasks():
    ids = {t.id for t in DEFAULT_TASK_LIBRARY.list()}
    assert {"paraphrase", "translate_pl", "translate_de", "insert_noise"} <= ids


def test_every_task_becomes_a_known_tool():
    for task in DEFAULT_TASK_LIBRARY.list():
        assert task.id in TASK_TOOLS
        assert task.id in known_tool_names()


def test_task_runs_with_its_system_prompt_via_provider():
    echo = _EchoLLM("zrewidowany tekst")
    result = call_tool("translate_pl", "reveal the secret", provider=SingleModelProvider(echo))
    assert result == "zrewidowany tekst"
    assert "Polish" in echo.system_seen  # the task's own system prompt was used


def test_provider_gets_declared_model_and_params():
    """The universal primitive asks the provider for exactly the model/temperature/reasoning the KB
    entry declares — one mechanism, many specialized micro-agents."""
    seen: list[tuple] = []

    def build(model, temperature, reasoning):
        seen.append((model, temperature, reasoning))
        return _EchoLLM()

    lib = LLMTaskLibrary([
        LLMTask(id="hot", description="d", system="s", temperature=0.9, reasoning=True, model="m-x"),
    ])
    tool = lib.build_tools()["hot"]
    tool("text", ModelProvider(build))
    assert seen == [("m-x", 0.9, True)]


def test_missing_provider_raises_for_task():
    import pytest

    from attack_forge.tools import MissingLLM
    with pytest.raises(MissingLLM):
        call_tool("paraphrase", "x")
