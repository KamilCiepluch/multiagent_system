"""Tests for the system/model knowledge base and the personalized TargetProfile it assembles."""

from __future__ import annotations

import pytest

from attack_forge.strategist import _render_target
from attack_forge.system_kb import (
    DEFAULT_MODEL_LIBRARY, DEFAULT_SYSTEM_LIBRARY, AgentProfile, ModelLibrary, ModelProfile,
    SystemLibrary, SystemProfile, build_target_profile,
)


def test_default_libraries_load():
    assert DEFAULT_SYSTEM_LIBRARY.get("agents_blocks") is not None
    assert DEFAULT_MODEL_LIBRARY.get("gpt-oss:20b") is not None


def test_agents_reference_known_models():
    for system in DEFAULT_SYSTEM_LIBRARY.list():
        for agent in system.agents:
            assert DEFAULT_MODEL_LIBRARY.get(agent.model) is not None, f"{agent.name} -> {agent.model}"


def _fixture_libs():
    models = ModelLibrary([
        ModelProfile(id="m1", vulnerabilities=["latent injection"], resistant_to=["plain DAN"]),
    ])
    systems = SystemLibrary([
        SystemProfile(id="sys", description="d", architecture="A -> B", agents=[
            AgentProfile(name="a1", role="does X", model="m1", channel="email body", defenses=["verify-first"],
                         vulnerabilities=["obeys P1 tags"]),
            AgentProfile(name="a2", role="does Y", model="m1", channel="chat"),
        ]),
    ])
    return models, systems


def test_build_target_profile_merges_agent_system_and_model():
    models, systems = _fixture_libs()
    target = build_target_profile(systems.get("sys"), "a1", models)

    assert target.name == "a1" and target.channel == "email body"
    assert target.known_defenses == ["verify-first"] and target.known_vulnerabilities == ["obeys P1 tags"]
    assert target.model == "m1"
    assert target.model_vulnerabilities == ["latent injection"]
    assert target.model_resistant_to == ["plain DAN"]
    # system context names the architecture and the SIBLING agent (a pivot), not the target itself.
    assert "A -> B" in target.system and "a2" in target.system


def test_build_target_profile_unknown_agent_raises():
    models, systems = _fixture_libs()
    with pytest.raises(KeyError):
        build_target_profile(systems.get("sys"), "nope", models)


def test_rendered_target_surfaces_model_intel_to_selector():
    models, systems = _fixture_libs()
    target = build_target_profile(systems.get("sys"), "a1", models)
    rendered = _render_target(target)
    assert "latent injection" in rendered          # lean-in intel is visible
    assert "AVOID" in rendered and "plain DAN" in rendered  # resistances flagged as avoid


def test_real_gpt_oss_profile_has_vulns_and_resistances():
    m = DEFAULT_MODEL_LIBRARY.get("gpt-oss:20b")
    assert m.vulnerabilities and m.resistant_to
