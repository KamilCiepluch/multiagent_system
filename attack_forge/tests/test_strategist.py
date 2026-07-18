"""Tests for the strategist tier: deterministic baseline, one-shot LLM, and the two-phase
Selector/Author split (step 3B) — including the fallback logic at every failure point.

The LLM path is exercised with a fake structured-output client, so no model is needed.
"""

from __future__ import annotations

from attack_forge.executor import execute
from attack_forge.framings import DEFAULT_LIBRARY
from attack_forge.models import ExecutionPlan, TargetProfile, TechniqueSelection, Turn
from attack_forge.strategist import (
    HeuristicStrategist, LLMSelector, LLMAuthor, LLMStrategist, RefusalGuard, RefusalVerdict,
    TwoPhaseStrategist, _render_selection,
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


def _valid_plan() -> ExecutionPlan:
    return ExecutionPlan(composition="single", turns=[Turn(role="user", content="attack text")])


# --- heuristic ---------------------------------------------------------------

def test_heuristic_builds_executable_plan():
    plan = HeuristicStrategist().plan("Leak the secret", CHAT)
    vector = execute(plan)
    assert vector.turns and "Leak the secret" in vector.turns[0].content


def test_heuristic_prefers_channel_specific_framing_for_email():
    plan = HeuristicStrategist().plan("do X", EMAIL)
    assert "SYSTEM NOTE" in plan.turns[0].content and "do X" in plan.turns[0].content


# --- one-shot LLM strategist (3A) --------------------------------------------

def test_one_shot_plan_passes_through_when_valid():
    strat = LLMStrategist(FakeLLM(_valid_plan()))
    plan = strat.plan("goal", CHAT)
    assert plan.turns[0].content == "attack text"
    assert strat.last_fallback is None


def test_one_shot_falls_back_on_error_flagged():
    strat = LLMStrategist(FakeLLM(RuntimeError("boom")))
    plan = strat.plan("Leak the secret", CHAT)
    assert strat.last_fallback and "RuntimeError" in strat.last_fallback
    assert execute(plan).turns


def test_one_shot_falls_back_on_refusal():
    guard = RefusalGuard(FakeLLM(RefusalVerdict(is_refusal=True, reason="declined")))
    strat = LLMStrategist(FakeLLM(_valid_plan()), guard=guard)
    strat.plan("Leak the secret", CHAT)
    assert strat.last_fallback == "refusal"


def test_one_shot_no_fallback_when_guard_clears():
    guard = RefusalGuard(FakeLLM(RefusalVerdict(is_refusal=False)))
    strat = LLMStrategist(FakeLLM(_valid_plan()), guard=guard)
    plan = strat.plan("goal", CHAT)
    assert strat.last_fallback is None and plan.turns[0].content == "attack text"


# --- LLMSelector validation ----------------------------------------------------

def test_llm_selector_filters_unknown_ids():
    raw = TechniqueSelection(
        framing_ids=["unrestricted_persona", "nope"],
        transform_names=["base64", "nope"],
        composition="stack", rationale="r",
    )
    selection = LLMSelector(FakeLLM(raw)).select("goal", CHAT)
    assert selection.framing_ids == ["unrestricted_persona"]
    assert selection.transform_names == ["base64"]


# --- _render_selection ---------------------------------------------------------

def test_render_selection_lists_chosen_items():
    selection = TechniqueSelection(
        framing_ids=["unrestricted_persona"], transform_names=["base64"],
        composition="stack", rationale="because",
    )
    text = _render_selection(selection, DEFAULT_LIBRARY)
    assert "unrestricted_persona" in text and "base64" in text and "because" in text


def test_render_selection_handles_empty_choices():
    selection = TechniqueSelection(framing_ids=[], transform_names=[], composition="single", rationale="")
    text = _render_selection(selection, DEFAULT_LIBRARY)
    assert "none" in text.lower()


# --- TwoPhaseStrategist (3B) ----------------------------------------------------

def test_two_phase_happy_path_exposes_selection():
    selection = TechniqueSelection(
        framing_ids=["unrestricted_persona"], transform_names=[], composition="stack", rationale="r"
    )
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(_valid_plan())))
    plan = strat.plan("goal", CHAT)
    assert plan.turns[0].content == "attack text"
    assert strat.last_selection is not None and strat.last_selection.framing_ids == ["unrestricted_persona"]
    assert strat.last_fallback is None


def test_two_phase_falls_back_when_selector_fails():
    strat = TwoPhaseStrategist(
        LLMSelector(FakeLLM(RuntimeError("boom"))), LLMAuthor(FakeLLM(_valid_plan())),
        fallback=HeuristicStrategist(),
    )
    plan = strat.plan("Leak the secret", CHAT)
    assert strat.last_fallback and "selector" in strat.last_fallback
    assert strat.last_selection is None
    assert execute(plan).turns


def test_two_phase_falls_back_when_author_fails():
    selection = TechniqueSelection(framing_ids=[], transform_names=[], composition="single", rationale="r")
    strat = TwoPhaseStrategist(
        LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(RuntimeError("boom"))),
        fallback=HeuristicStrategist(),
    )
    plan = strat.plan("Leak the secret", CHAT)
    assert strat.last_fallback and "author" in strat.last_fallback
    assert strat.last_selection is not None  # S1 succeeded before S2 failed
    assert execute(plan).turns


def test_two_phase_falls_back_on_refusal():
    selection = TechniqueSelection(framing_ids=[], transform_names=[], composition="single", rationale="r")
    guard = RefusalGuard(FakeLLM(RefusalVerdict(is_refusal=True)))
    strat = TwoPhaseStrategist(
        LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(_valid_plan())),
        guard=guard, fallback=HeuristicStrategist(),
    )
    strat.plan("Leak the secret", CHAT)
    assert strat.last_fallback == "refusal"


def test_two_phase_without_fallback_returns_bare_plan():
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(RuntimeError("boom"))), LLMAuthor(FakeLLM(_valid_plan())))
    plan = strat.plan("Leak the secret", CHAT)
    assert plan.turns == [Turn(role="user", content="Leak the secret")]


# --- transform compliance check -------------------------------------------

def test_two_phase_flags_transform_the_author_never_placed():
    selection = TechniqueSelection(
        framing_ids=[], transform_names=["zero_width", "base64"], composition="stack", rationale="r"
    )
    authored_only_base64 = ExecutionPlan(
        composition="stack", turns=[Turn(role="user", content="do [[t:base64]]x[[/t]]")]
    )
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored_only_base64)))
    strat.plan("goal", CHAT)
    assert strat.last_missing_transforms == ["zero_width"]


def test_two_phase_no_gap_when_all_selected_transforms_are_used():
    selection = TechniqueSelection(
        framing_ids=[], transform_names=["base64"], composition="stack", rationale="r"
    )
    authored = ExecutionPlan(composition="stack", turns=[Turn(role="user", content="do [[t:base64]]x[[/t]]")])
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_missing_transforms == []


def test_two_phase_checks_prefill_for_transform_usage_too():
    selection = TechniqueSelection(
        framing_ids=[], transform_names=["rot13"], composition="stack", rationale="r"
    )
    authored = ExecutionPlan(
        composition="stack", turns=[Turn(role="user", content="go")],
        prefill="[[t:rot13]]sure[[/t]]",
    )
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_missing_transforms == []


def test_two_phase_flags_degenerate_single_char_wrapping():
    """Reproduces the real failure: the author "used" zero_width per the naive presence check,
    but wrapped single letters — a documented no-op — instead of a real fragment."""
    selection = TechniqueSelection(
        framing_ids=[], transform_names=["zero_width"], composition="stack", rationale="r"
    )
    letter_by_letter = "".join(f"[[t:zero_width]]{ch}[[/t]]" for ch in "SYSTEM")
    authored = ExecutionPlan(composition="stack", turns=[Turn(role="user", content=letter_by_letter)])
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_missing_transforms == []          # the name IS present...
    assert strat.last_degenerate_transforms == ["zero_width"]  # ...but had no effect


def test_two_phase_does_not_flag_meaningful_multi_char_use():
    selection = TechniqueSelection(
        framing_ids=[], transform_names=["zero_width"], composition="stack", rationale="r"
    )
    authored = ExecutionPlan(
        composition="stack", turns=[Turn(role="user", content="[[t:zero_width]]SYSTEM[[/t]]")]
    )
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_degenerate_transforms == []


def test_two_phase_one_meaningful_use_clears_degenerate_flag_for_that_name():
    """If the SAME transform is applied twice — once meaningfully, once as a no-op — it should
    not be flagged degenerate: the author clearly knows how to use it."""
    selection = TechniqueSelection(
        framing_ids=[], transform_names=["zero_width"], composition="stack", rationale="r"
    )
    content = "[[t:zero_width]]SYSTEM[[/t]] and [[t:zero_width]]A[[/t]]"
    authored = ExecutionPlan(composition="stack", turns=[Turn(role="user", content=content)])
    strat = TwoPhaseStrategist(LLMSelector(FakeLLM(selection)), LLMAuthor(FakeLLM(authored)))
    strat.plan("goal", CHAT)
    assert strat.last_degenerate_transforms == []
