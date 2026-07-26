"""Tests for the attack-category taxonomy and the two-stage selector funnel.

The coverage tests are the important ones: they fail offline the moment a new tool is added to the
arsenal but not placed in a family (or a family lists a tool that no longer exists) — so the taxonomy
can't silently drift out of sync with the registries. The funnel is exercised behind fake LLMs."""

from __future__ import annotations

from collections import Counter

from attack_forge.categories import DEFAULT_CATEGORY_LIBRARY as LIB
from attack_forge.models import CategorySelection, TargetProfile, TechniqueSelection
from attack_forge.strategist import CategorySelector, select_two_stage

_TARGET = TargetProfile(name="secret_guard", description="d", channel="chat", model="qwen3.6:27b")


# --- taxonomy <-> arsenal in sync -------------------------------------------------------------

def test_every_tool_covered_and_no_dangling_refs():
    uncovered, unknown = LIB.coverage()
    assert uncovered == [], f"tools in no family: {uncovered}"
    assert unknown == [], f"family lists a non-existent tool: {unknown}"


def test_each_tool_in_exactly_one_family():
    counts = Counter(t for c in LIB.list() for t in c.tools)
    assert [t for t, n in counts.items() if n > 1] == []   # no tool double-listed


# --- rendering / filtering --------------------------------------------------------------------

def test_render_families_lists_all_ids():
    families = LIB.render_families()
    for c in LIB.list():
        assert c.id in families
    assert "random_caps" not in families   # stage-0 shows families, NOT individual tools


def test_tools_for_unions_dedups_and_ignores_unknown():
    tools = LIB.tools_for(["perturbation", "encoding", "not_a_family"])
    assert "random_caps" in tools and "base64" in tools
    assert len(tools) == len(set(tools))   # de-duplicated


def test_render_tools_shows_only_chosen_families():
    menu = LIB.render_tools(["perturbation"])
    assert "random_caps" in menu
    assert "base64" not in menu            # encoding wasn't chosen


# --- funnel behind fake LLMs ------------------------------------------------------------------

class _FakeStructured:
    def __init__(self, obj): self._obj = obj
    def invoke(self, _messages): return self._obj


class _FakeLLM:
    """Returns a preset structured-output object per requested model class (S0 vs S1)."""
    def __init__(self, by_model): self._by = by_model
    def with_structured_output(self, model, method=None): return _FakeStructured(self._by[model])


def test_category_selector_drops_unknown_ids():
    cats = CategorySelection(rationale="r", category_ids=["persuasion", "not_a_family"])
    out = CategorySelector(_FakeLLM({CategorySelection: cats})).select_categories("g", _TARGET)
    assert out.category_ids == ["persuasion"]


def test_two_stage_chains_s0_into_s1():
    cats = CategorySelection(rationale="r", category_ids=["perturbation", "bogus"])
    sel = TechniqueSelection(rationale="r2", tool_names=["random_caps", "not_a_tool"], composition="single")
    llm = _FakeLLM({CategorySelection: cats, TechniqueSelection: sel})

    chosen_cats, selection = select_two_stage("g", _TARGET, llm)
    assert chosen_cats.category_ids == ["perturbation"]     # S0 filtered
    assert selection.tool_names == ["random_caps"]          # S1 filtered to known tools


def test_two_stage_survives_empty_category_pick():
    cats = CategorySelection(rationale="r", category_ids=[])   # S0 picks nothing -> full-menu fallback
    sel = TechniqueSelection(rationale="r2", tool_names=["base64"], composition="single")
    llm = _FakeLLM({CategorySelection: cats, TechniqueSelection: sel})

    chosen_cats, selection = select_two_stage("g", _TARGET, llm)
    assert chosen_cats.category_ids == []
    assert selection.tool_names == ["base64"]
