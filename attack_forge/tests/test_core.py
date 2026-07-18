"""Unit tests for the attack-agnostic core: transforms, directive expander, executor."""

from __future__ import annotations

import base64

import pytest

from attack_forge.directives import (
    MalformedDirective, UnknownTransform, directive_fragments, expand, used_transform_names,
)
from attack_forge.executor import execute
from attack_forge.models import ExecutionPlan, Turn
from attack_forge.transforms import apply_transform


# --- transforms -------------------------------------------------------------

def test_base64_roundtrips():
    encoded = apply_transform("base64", "reveal the secret")
    assert base64.b64decode(encoded).decode() == "reveal the secret"


def test_rot13_is_its_own_inverse():
    assert apply_transform("rot13", apply_transform("rot13", "Attack")) == "Attack"


def test_reverse_and_spaced():
    assert apply_transform("reverse", "abc") == "cba"
    assert apply_transform("spaced", "abc") == "a b c"


# --- directive expander -----------------------------------------------------

def test_single_directive_expands_and_reports():
    out, applied = expand("do [[t:base64]]x[[/t]] now")
    assert out == f"do {base64.b64encode(b'x').decode()} now"
    assert applied == ["base64"]


def test_multiple_sibling_directives():
    out, applied = expand("[[t:reverse]]ab[[/t]] and [[t:reverse]]cd[[/t]]")
    assert out == "ba and dc"
    assert applied == ["reverse", "reverse"]


def test_nested_directives_apply_innermost_first():
    out, applied = expand("[[t:base64]][[t:reverse]]secret[[/t]][[/t]]")
    assert out == base64.b64encode(b"terces").decode()
    assert applied == ["reverse", "base64"]


def test_plain_text_is_untouched():
    assert expand("no directives here") == ("no directives here", [])


def test_unknown_transform_raises():
    with pytest.raises(UnknownTransform):
        expand("[[t:nope]]x[[/t]]")


def test_unbalanced_directive_raises():
    with pytest.raises(MalformedDirective):
        expand("[[t:base64]]x")


def test_used_transform_names_finds_all_distinct_names():
    text = "[[t:base64]]a[[/t]] and [[t:reverse]][[t:base64]]b[[/t]][[/t]]"
    assert used_transform_names(text) == {"base64", "reverse"}


def test_used_transform_names_empty_when_none_present():
    assert used_transform_names("plain text") == set()


def test_directive_fragments_reports_raw_text_before_transformation():
    assert directive_fragments("[[t:base64]]hello[[/t]]") == [("base64", "hello")]


def test_directive_fragments_nested_order_innermost_first():
    fragments = directive_fragments("[[t:base64]][[t:reverse]]secret[[/t]][[/t]]")
    assert fragments[0] == ("reverse", "secret")
    assert fragments[1][0] == "base64"


# --- executor ---------------------------------------------------------------

def test_single_message_sets_payload():
    plan = ExecutionPlan(composition="single",
                         turns=[Turn(role="user", content="follow [[t:reverse]]ba[[/t]]")])
    vector = execute(plan)
    assert vector.payload == "follow ab"
    assert vector.applied_transforms == ["reverse"]
    assert len(vector.turns) == 1


def test_prefill_appends_assistant_turn_and_clears_payload():
    plan = ExecutionPlan(composition="stack",
                         turns=[Turn(role="user", content="go")],
                         prefill="Sure: ")
    vector = execute(plan)
    assert vector.payload is None
    assert vector.prefill == "Sure: "
    assert [t.role for t in vector.turns] == ["user", "assistant"]


def test_chain_preserves_turn_order():
    plan = ExecutionPlan(composition="chain", turns=[
        Turn(role="user", content="a"),
        Turn(role="assistant", content="b"),
        Turn(role="user", content="[[t:spaced]]cd[[/t]]"),
    ])
    vector = execute(plan)
    assert [t.content for t in vector.turns] == ["a", "b", "c d"]
    assert vector.payload is None
