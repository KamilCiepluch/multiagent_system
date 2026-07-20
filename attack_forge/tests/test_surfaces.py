"""Tests for the attack-surface ladder: ordering/lookup/advance (pure) + that every surface in the
ladder resolves against the REAL judge specs and system agents (a bad bundle fails here, offline)."""

from __future__ import annotations

from attack_forge.judge import DEFAULT_JUDGE_LIBRARY
from attack_forge.surfaces import SURFACES, index_for_injection, next_surface
from attack_forge.system_kb import DEFAULT_MODEL_LIBRARY, DEFAULT_SYSTEM_LIBRARY, build_target_profile


def test_ladder_starts_at_email_and_escalates():
    names = [s.name for s in SURFACES]
    assert names[0] == "email"            # the hard entry (sender-role gate) is where we start
    assert "skill" in names               # ...and escalate toward trusted-content execution


def test_index_for_injection_lookup_and_default():
    assert index_for_injection("email") == 0
    assert index_for_injection("skill") == [s.injection for s in SURFACES].index("skill")
    assert index_for_injection("does-not-exist") == 0   # unknown -> first surface


def test_next_surface_walks_then_stops():
    assert next_surface(0) is SURFACES[1]
    assert next_surface(len(SURFACES) - 1) is None
    assert next_surface(-1) is SURFACES[0]


def test_every_surface_spec_exists():
    for s in SURFACES:
        assert DEFAULT_JUDGE_LIBRARY.get(s.spec) is not None, f"{s.name}: judge spec '{s.spec}' missing"


def test_every_surface_target_resolves():
    system = DEFAULT_SYSTEM_LIBRARY.get("agents_blocks")
    for s in SURFACES:
        profile = build_target_profile(system, s.target, DEFAULT_MODEL_LIBRARY)
        assert profile.name == s.target, f"{s.name}: agent '{s.target}' did not resolve"
