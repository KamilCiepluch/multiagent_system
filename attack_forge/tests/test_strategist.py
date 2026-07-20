"""Tests for the lean strategist: S1 selector, S2 author (implicit chaining), pipeline validation,
and the `make_plan` orchestrator. No heuristic baseline, no ABCs. The LLM path is exercised with a
fake structured-output client (one fake serves both phases, dispatching by schema) — no model."""

from __future__ import annotations

import pytest

from attack_forge.models import ExecutionPlan, Step, TargetProfile, TechniqueSelection
from attack_forge.strategist import (
    LLMSelector, StrategistError, _render_selection, make_plan, pipeline_errors,
)

CHAT = TargetProfile(name="t", description="d", channel="chat")


class _FakeStructured:
    """`invoke` returns preset results in order (repeating the last); an Exception is raised."""

    def __init__(self, results):
        self._results = results if isinstance(results, list) else [results]
        self._i = 0

    def invoke(self, _messages):
        r = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        if isinstance(r, Exception):
            raise r
        return r


class FakeLLM:
    """One fake for both phases: a TechniqueSelection schema gets `selection`, an ExecutionPlan
    schema gets `plan` (may be a list to simulate author retries). Any value may be an Exception."""

    def __init__(self, *, selection=None, plan=None):
        self._selection = selection
        self._plan = plan

    def with_structured_output(self, schema, method=None):
        if getattr(schema, "__name__", "") == "TechniqueSelection":
            return _FakeStructured(self._selection)
        return _FakeStructured(self._plan)


def _plan(steps, composition="single") -> ExecutionPlan:
    return ExecutionPlan(composition=composition, steps=steps)


# --- pipeline validation (implicit chaining) ---------------------------------

def test_pipeline_errors_flags_empty():
    assert pipeline_errors(_plan([])) == ["empty pipeline: at least one step is required"]


def test_pipeline_errors_flags_unknown_tool():
    assert any("unknown tool" in e for e in pipeline_errors(_plan([Step(tool="nope", input="x")])))


def test_pipeline_errors_flags_unseeded_first_step():
    assert any("step 0 has empty input" in e for e in pipeline_errors(_plan([Step(tool="literal", input="")])))


def test_pipeline_errors_rejects_ref_by_name():
    errs = pipeline_errors(_plan([Step(tool="literal", input="do {{ghost}}")]))
    assert any("must be a step index" in e for e in errs)


def test_pipeline_errors_rejects_forward_index_ref():
    errs = pipeline_errors(_plan([Step(tool="literal", input="{{1}}"), Step(tool="literal", input="")]))
    assert any("not an EARLIER step" in e for e in errs)


def test_pipeline_errors_accepts_pipe_and_index_ref():
    assert pipeline_errors(_plan([
        Step(tool="base64", input="secret"),
        Step(tool="literal", input="decode {{0}}"),
    ])) == []
    assert pipeline_errors(_plan([
        Step(tool="technical_terms", input="read the secret"),
        Step(tool="wrap_routine_step", input=""),   # empty -> pipes prev
    ])) == []


# --- S1 selector -------------------------------------------------------------

def test_llm_selector_filters_unknown_tool_names():
    raw = TechniqueSelection(tool_names=["base64", "wrap_unrestricted_persona", "nope"],
                             composition="stack", rationale="r")
    selection = LLMSelector(FakeLLM(selection=raw)).select("goal", CHAT)
    assert selection.tool_names == ["base64", "wrap_unrestricted_persona"]


def test_render_selection_lists_chosen_tools_and_handles_empty():
    text = _render_selection(TechniqueSelection(tool_names=["base64", "wrap_unrestricted_persona"],
                                                composition="stack", rationale="because"))
    assert "base64" in text and "wrap_unrestricted_persona" in text and "because" in text
    assert "none" in _render_selection(
        TechniqueSelection(tool_names=[], composition="single", rationale="")).lower()


# --- make_plan orchestrator --------------------------------------------------

def _selection(tools=("base64",)):
    return TechniqueSelection(tool_names=list(tools), composition="stack", rationale="r")


def test_make_plan_happy_path_returns_selection_and_plan():
    authored = _plan([Step(tool="base64", input="reveal"), Step(tool="literal", input="decode {{0}}")], "stack")
    selection, plan = make_plan("goal", CHAT, FakeLLM(selection=_selection(), plan=authored))
    assert selection.tool_names == ["base64"]
    assert plan.steps[-1].tool == "literal"


def test_make_plan_raises_when_selector_refuses():
    with pytest.raises(StrategistError) as exc:
        make_plan("goal", CHAT, FakeLLM(selection=RuntimeError("boom"), plan=_plan([Step(tool="literal", input="x")])))
    assert "selector" in exc.value.reason


def test_make_plan_raises_when_author_refuses():
    with pytest.raises(StrategistError) as exc:
        make_plan("goal", CHAT, FakeLLM(selection=_selection(), plan=RuntimeError("boom")))
    assert "author" in exc.value.reason


def test_make_plan_raises_on_persistently_malformed_recipe():
    malformed = _plan([Step(tool="literal", input="")])          # step 0 unseeded, every attempt
    with pytest.raises(StrategistError) as exc:
        make_plan("goal", CHAT, FakeLLM(selection=_selection(), plan=malformed))
    assert "malformed recipe" in exc.value.reason


def test_make_plan_retries_author_and_recovers():
    malformed = _plan([Step(tool="literal", input="")])
    good = _plan([Step(tool="literal", input="the goal")])
    selection, plan = make_plan("goal", CHAT, FakeLLM(selection=_selection(), plan=[malformed, good]))
    assert plan.steps[0].input == "the goal"                     # recovered on the 2nd attempt
