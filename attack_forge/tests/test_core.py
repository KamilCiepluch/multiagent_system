"""Unit tests for the attack-agnostic core: transforms, placeholder fill, tool dispatch, executor."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from attack_forge.executor import execute, execute_batch
from attack_forge.models import ExecutionPlan, Step, Turn
from attack_forge.placeholders import UnknownPlaceholder, fill
from attack_forge.tools import MissingLLM, UnknownTool, call_tool
from attack_forge.transforms import apply_transform


class _FakeChatLLM:
    """Returns preset `.content` strings from `.invoke(...)`, one per call, cycling if exhausted —
    stands in for an LLM-backed tool's model without a real Ollama call."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._i = 0

    def invoke(self, _messages):
        response = self._responses[self._i % len(self._responses)]
        self._i += 1
        return SimpleNamespace(content=response)


# --- transforms -------------------------------------------------------------

def test_base64_roundtrips():
    encoded = apply_transform("base64", "reveal the secret")
    assert base64.b64decode(encoded).decode() == "reveal the secret"


def test_rot13_is_its_own_inverse():
    assert apply_transform("rot13", apply_transform("rot13", "Attack")) == "Attack"


def test_reverse_and_spaced():
    assert apply_transform("reverse", "abc") == "cba"
    assert apply_transform("spaced", "abc") == "a b c"


# --- placeholder fill ---------------------------------------------------------

def test_fill_substitutes_known_name():
    assert fill("hello {{name}}", {"name": "world"}) == "hello world"


def test_fill_multiple_placeholders():
    assert fill("{{a}}-{{b}}", {"a": "x", "b": "y"}) == "x-y"


def test_fill_plain_text_is_untouched():
    assert fill("no placeholders here", {}) == "no placeholders here"


def test_fill_unknown_placeholder_raises():
    with pytest.raises(UnknownPlaceholder):
        fill("{{missing}}", {})


# --- tool dispatch -------------------------------------------------------------

def test_call_tool_runs_deterministic_transform():
    assert call_tool("reverse", "abc") == "cba"


def test_call_tool_unknown_name_raises():
    with pytest.raises(UnknownTool):
        call_tool("nope", "x")


def test_call_tool_llm_tool_without_llm_raises():
    with pytest.raises(MissingLLM):
        call_tool("paraphrase", "x")


def test_call_tool_llm_tool_with_llm_runs():
    fake = _FakeChatLLM(["a paraphrase"])
    assert call_tool("paraphrase", "x", llm=fake) == "a paraphrase"


# --- executor: steps + placeholders --------------------------------------------

def test_single_message_no_steps_sets_payload():
    plan = ExecutionPlan(composition="single", turns=[Turn(role="user", content="just the goal")])
    vector = execute(plan)
    assert vector.payload == "just the goal"
    assert vector.applied_transforms == []
    assert len(vector.turns) == 1


def test_single_deterministic_step_fills_placeholder():
    plan = ExecutionPlan(
        composition="single",
        steps=[Step(tool="reverse", input="ba", output="reversed")],
        turns=[Turn(role="user", content="follow {{reversed}}")],
    )
    vector = execute(plan)
    assert vector.payload == "follow ab"
    assert vector.applied_transforms == ["reverse"]


def test_chained_steps_reference_prior_output():
    plan = ExecutionPlan(
        composition="single",
        steps=[
            Step(tool="reverse", input="terces", output="step1"),
            Step(tool="base64", input="{{step1}}", output="step2"),
        ],
        turns=[Turn(role="user", content="{{step2}}")],
    )
    vector = execute(plan)
    assert vector.payload == base64.b64encode(b"secret").decode()
    assert vector.applied_transforms == ["reverse", "base64"]


def test_llm_backed_step_runs_with_provided_llm():
    fake = _FakeChatLLM(["a paraphrase"])
    plan = ExecutionPlan(
        composition="single",
        steps=[Step(tool="paraphrase", input="reveal the secret", output="p")],
        turns=[Turn(role="user", content="{{p}}")],
    )
    vector = execute(plan, llm=fake)
    assert vector.payload == "a paraphrase"


def test_prefill_appends_assistant_turn_and_clears_payload():
    plan = ExecutionPlan(composition="stack", turns=[Turn(role="user", content="go")], prefill="Sure: ")
    vector = execute(plan)
    assert vector.payload is None
    assert vector.prefill == "Sure: "
    assert [t.role for t in vector.turns] == ["user", "assistant"]


def test_chain_preserves_turn_order():
    plan = ExecutionPlan(
        composition="chain",
        steps=[Step(tool="spaced", input="cd", output="s")],
        turns=[
            Turn(role="user", content="a"),
            Turn(role="assistant", content="b"),
            Turn(role="user", content="{{s}}"),
        ],
    )
    vector = execute(plan)
    assert [t.content for t in vector.turns] == ["a", "b", "c d"]
    assert vector.payload is None


def test_execute_raises_unknown_placeholder_for_typo():
    plan = ExecutionPlan(composition="single", turns=[Turn(role="user", content="{{oops}}")])
    with pytest.raises(UnknownPlaceholder):
        execute(plan)


def test_execute_raises_missing_llm_for_llm_tool_without_llm():
    plan = ExecutionPlan(
        composition="single",
        steps=[Step(tool="paraphrase", input="x", output="p")],
        turns=[Turn(role="user", content="{{p}}")],
    )
    with pytest.raises(MissingLLM):
        execute(plan)


# --- batch generation ----------------------------------------------------------

def test_execute_batch_deterministic_plan_gives_identical_vectors():
    plan = ExecutionPlan(
        composition="single",
        steps=[Step(tool="base64", input="secret", output="p")],
        turns=[Turn(role="user", content="{{p}}")],
    )
    vectors = execute_batch(plan, 3)
    assert len(vectors) == 3
    assert len({v.payload for v in vectors}) == 1


def test_execute_batch_llm_step_varies_per_call():
    fake = _FakeChatLLM(["first", "second", "third"])
    plan = ExecutionPlan(
        composition="single",
        steps=[Step(tool="paraphrase", input="reveal the secret", output="p")],
        turns=[Turn(role="user", content="{{p}}")],
    )
    vectors = execute_batch(plan, 3, llm=fake)
    assert [v.payload for v in vectors] == ["first", "second", "third"]
