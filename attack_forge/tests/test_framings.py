"""Tests for the framing library and the strategist menu."""

from __future__ import annotations

from attack_forge.framings import DEFAULT_LIBRARY, Framing, FramingLibrary
from attack_forge.menu import render_menu
from attack_forge.models import TargetProfile


def test_default_library_loads_seed():
    ids = {f.id for f in DEFAULT_LIBRARY.list()}
    assert {"unrestricted_persona", "data_smuggle"} <= ids


def test_get_and_missing():
    assert DEFAULT_LIBRARY.get("unrestricted_persona") is not None
    assert DEFAULT_LIBRARY.get("nope") is None


def test_for_target_filters_by_channel():
    email = TargetProfile(name="t", description="d", channel="email body")
    chat = TargetProfile(name="t", description="d", channel="chat")
    email_ids = {f.id for f in DEFAULT_LIBRARY.for_target(email)}
    chat_ids = {f.id for f in DEFAULT_LIBRARY.for_target(chat)}
    # data_smuggle is tagged to 'email body' / 'search result', not 'chat'.
    assert "data_smuggle" in email_ids
    assert "data_smuggle" not in chat_ids
    # universal framings appear for both.
    assert "unrestricted_persona" in email_ids and "unrestricted_persona" in chat_ids


def test_for_target_orders_scored_first():
    lib = FramingLibrary([
        Framing(id="a", intent="x", score=None),
        Framing(id="b", intent="y", score=0.9),
        Framing(id="c", intent="z", score=0.3),
    ])
    profile = TargetProfile(name="t", description="d", channel="chat")
    assert [f.id for f in lib.for_target(profile)] == ["b", "c", "a"]


def test_add_and_save_roundtrip(tmp_path):
    path = tmp_path / "framings.yaml"
    lib = FramingLibrary([Framing(id="a", intent="x")])
    lib.add(Framing(id="b", intent="y", examples=["ex"], target_tags=["chat"], score=0.5))
    lib.save(path)

    reloaded = FramingLibrary.from_yaml(path)
    b = reloaded.get("b")
    assert b is not None and b.score == 0.5 and b.target_tags == ["chat"]


def test_menu_includes_all_tool_kinds():
    menu = render_menu()
    assert "STRUCTURES" in menu and "TRANSFORMS" in menu and "WRAPPERS" in menu
    assert "base64" in menu                       # a transform
    assert "paraphrase" in menu                   # an LLM rewrite tool
    assert "wrap_unrestricted_persona" in menu    # a framing, now a wrap tool
