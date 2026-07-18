"""attack_forge — a tool for composing attack vectors against an agentic system.

Architecture:
  strategist (attack-aware, LLM)  →  ExecutionPlan (operations IR)  →  executor (deterministic) → AttackVector

The executor is attack-agnostic: it only expands transform directives and assembles turns.
All strategy and creativity live in the strategist tier (built in later steps).

Deliberately isolated from `agents/` — this is offensive tooling (an authorized whitebox
benchmark of our OWN system), so it may have a lighter, different implementation.
"""

from __future__ import annotations

from .models import TargetProfile, TechniqueSelection, Turn, Composition, Role, ExecutionPlan, AttackVector
from .transforms import Transform, TRANSFORMS, apply_transform, transform_names
from .directives import expand, DirectiveError, UnknownTransform, MalformedDirective
from .executor import execute
from .framings import Framing, FramingLibrary, DEFAULT_LIBRARY
from .menu import render_menu
from .strategist import (
    Strategist, Selector, Author,
    HeuristicSelector, HeuristicAuthor, HeuristicStrategist,
    LLMSelector, LLMAuthor, LLMStrategist, TwoPhaseStrategist,
    RefusalGuard, RefusalVerdict,
)
from .target import TargetResponse, deliver

__all__ = [
    "TargetProfile", "TechniqueSelection", "Turn", "Composition", "Role", "ExecutionPlan", "AttackVector",
    "Transform", "TRANSFORMS", "apply_transform", "transform_names",
    "expand", "DirectiveError", "UnknownTransform", "MalformedDirective",
    "execute",
    "Framing", "FramingLibrary", "DEFAULT_LIBRARY", "render_menu",
    "Strategist", "Selector", "Author",
    "HeuristicSelector", "HeuristicAuthor", "HeuristicStrategist",
    "LLMSelector", "LLMAuthor", "LLMStrategist", "TwoPhaseStrategist",
    "RefusalGuard", "RefusalVerdict",
    "TargetResponse", "deliver",
]
