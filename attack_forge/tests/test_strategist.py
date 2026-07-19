"""Tests for the strategist tier: the no-LLM baseline and the two-phase Selector/Author split.

There is no fallback and no auto-repair anymore: on any failure the two-phase strategist RAISES
`StrategistError`. The LLM path is exercised with a fake structured-output client — no model needed.
"""

from __future__ import annotations

import pytest

from attack_forge.executor import execute
from attack_forge.models import ExecutionPlan, Step, TargetProfile, TechniqueSelection
from attack_forge.strategist import (
    HeuristicStrategist, LLMAuthor, LLMSelector, StrategistError, TwoPhaseStrategist,
    _render_selection, pipeline_errors,
)

EMAIL = TargetProfile(name="t", description="d", channel="email body")
CHAT = TargetProfile(name="t", description="d", channel="chat")


class _FakeStructured:
    def __init__(self, result):
        self._result = result

    def invoke(self, _messages):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeLLM:
    """Returns a preset object from `with_structured_output(...).invoke(...)`, ignoring schema."""

    def __init__(self, result):
        self._result = result

    def with_structured_output(self, _schema, method=None):
        return _FakeStructured(self._result)


def _plan(steps: list[Step], composition="single") -> ExecutionPlan:
    return ExecutionPlan(composition=composition, steps=steps)


def _valid_plan() -> ExecutionPlan:
    return _plan([Step(tool="literal", input="attack text", output="msg")])


# --- heuristic baseline ------------------------------------------------------

def test_heuristic_builds_executable_plan():
    plan = HeuristicStrategist().plan("Leak the secret", CHAT)
    vector = execute(plan)
    assert "Leak the secret" in vector.payload


def test_heuristic_prefers_channel_specific_framing_for_email():
    plan = HeuristicStrategist().plan("do X", EMAIL)
    vector = execute(plan)
    assert "SYSTEM NOTE" in vector.payload and "do X" in vector.payload


# --- pipeline validation -----------------------------------------------------

def test_pipeline_errors_flags_empty():
    assert pipeline_errors(_plan([])) == ["empty pipeline: at least one step is required"]


def test_pipeline_errors_flags_unknown_tool():
    errors = pipeline_errors(_plan([Step(tool="nope", input="x", output="msg")]))
    assert any("unknown tool" in e for e in errors)


def test_pipeline_errors_flags_unbound_reference():
    errors = pipeline_errors(_plan([Step(tool="literal", input="{{ghost}}", output="msg")]))
    assert any("unbound" in e and "ghost" in e for e in errors)


def test_pipeline_errors_accepts_valid_chain():
    plan = _plan([
        Step(tool="base64", input="secret", output="enc"),
        Step(tool="literal", input="decode {{enc}}", output="msg"),
    ])
    assert pipeline_errors(plan) == []


# --- LLMSelector -------------------------------------------------------------

def test_llm_selector_filters_unknown_tool_names():
    raw = TechniqueSelection(tool_names=["base64", "wrap_unrestricted_persona", "nope"],
                             composition="stack", rationale="r")
    selection = LLMSelector(FakeLLM(raw)).select("goal", CHAT)
    assert selection.tool_names == ["base64", "wrap_unrestricted_persona"]


def test_render_selection_lists_chosen_tools():
    selection = TechniqueSelection(tool_names=["base64", "wrap_unrestricted_persona"],
                                   composition="stack", rationale="because")
    text = _render_selection(selection)
    assert "base64" in text and "wrap_unrestricted_persona" in text and "because" in text


def test_render_selection_handles_empty_choice():
    text = _render_selection(TechniqueSelection(tool_names=[], composition="single", rationale=""))
    assert "none" in text.lower()


# --- TwoPhaseStrategist -------------------------------------------------------

def test_two_phase_happy_path_exposes_selection():
    selection = TechniqueSelection(tool_names=["base64"], composition="stack", rationale="r")
    authored = _plan([
        Step(tool="base64", input="reveal", output="enc"),
        Step(tool="literal", input="decode {{enc}}", output="msg"),
    ], composition="stack")
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    plan = strat.plan("goal", CHAT)
    assert plan.steps[-1].output == "msg"
    assert strat.last_selection is not None and strat.last_selection.tool_names == ["base64"]
    assert strat.last_missing_tools == [] and strat.last_extra_tools == []


def test_two_phase_raises_when_selector_fails():
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(RuntimeError("boom"))), LLMAuthor(FakeLLM(_valid_plan())))
    with pytest.raises(StrategistError) as exc:
        strat.plan("Leak the secret", CHAT)
    assert "selector" in exc.value.reason
    assert strat.last_selection is None


def test_two_phase_raises_when_author_fails():
    selection = TechniqueSelection(tool_names=[], composition="single", rationale="r")
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(RuntimeError("boom"))))
    with pytest.raises(StrategistError) as exc:
        strat.plan("Leak the secret", CHAT)
    assert "author" in exc.value.reason
    assert strat.last_selection is not None  # S1 succeeded before S2 failed


def test_two_phase_raises_on_malformed_recipe():
    """The author referenced {{payload}} with no step producing it — caught as a clear error, not a
    crash deep in the executor, and NOT silently patched with a fallback."""
    selection = TechniqueSelection(tool_names=[], composition="single", rationale="r")
    authored = _plan([Step(tool="literal", input="do {{payload}}", output="msg")])
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    with pytest.raises(StrategistError) as exc:
        strat.plan("Leak the secret", CHAT)
    assert "malformed recipe" in exc.value.reason and "payload" in exc.value.reason


def test_two_phase_raises_on_empty_pipeline():
    selection = TechniqueSelection(tool_names=[], composition="single", rationale="r")
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(_plan([]))))
    with pytest.raises(StrategistError):
        strat.plan("goal", CHAT)


# --- tool diagnostics (never block) ------------------------------------------

def test_two_phase_flags_selected_tool_the_author_skipped():
    selection = TechniqueSelection(tool_names=["zero_width", "base64"], composition="stack", rationale="r")
    authored = _plan([Step(tool="base64", input="x", output="msg")], composition="stack")
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_missing_tools == ["zero_width"]
    assert strat.last_extra_tools == []


def test_two_phase_flags_extra_tool_not_selected_ignoring_literal():
    selection = TechniqueSelection(tool_names=["base64"], composition="stack", rationale="r")
    authored = _plan([
        Step(tool="base64", input="x", output="enc"),
        Step(tool="rot13", input="{{enc}}", output="r"),
        Step(tool="literal", input="{{r}}", output="msg"),
    ], composition="stack")
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_missing_tools == [] and strat.last_extra_tools == ["rot13"]  # literal not flagged
