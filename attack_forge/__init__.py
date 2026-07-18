"""attack_forge — a tool for composing attack vectors against an agentic system.

Architecture:
  strategist (attack-aware, LLM)  →  ExecutionPlan (steps recipe + turn templates)  →  executor
  (deterministic-in-control-flow) → AttackVector(s)

The executor is attack-agnostic: it only runs the plan's `steps` (deterministic transforms and/or
LLM-backed tools) and fills `{{name}}` placeholders in turns/prefill. All strategy and creativity
live in the strategist tier.

Deliberately isolated from `agents/` — this is offensive tooling (an authorized whitebox
benchmark of our OWN system), so it may have a lighter, different implementation.
"""

from __future__ import annotations

from .models import (
    TargetProfile, TechniqueSelection, Turn, Step, Composition, Role, ExecutionPlan, AttackVector,
)
from .transforms import Transform, TRANSFORMS, apply_transform, transform_names
from .llm_tools import LLMTool, LLM_TOOLS
from .placeholders import fill, UnknownPlaceholder
from .tools import call_tool, known_tool_names, UnknownTool, MissingLLM
from .executor import execute, execute_batch
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
    "TargetProfile", "TechniqueSelection", "Turn", "Step", "Composition", "Role", "ExecutionPlan", "AttackVector",
    "Transform", "TRANSFORMS", "apply_transform", "transform_names",
    "LLMTool", "LLM_TOOLS",
    "fill", "UnknownPlaceholder",
    "call_tool", "known_tool_names", "UnknownTool", "MissingLLM",
    "execute", "execute_batch",
    "Framing", "FramingLibrary", "DEFAULT_LIBRARY", "render_menu",
    "Strategist", "Selector", "Author",
    "HeuristicSelector", "HeuristicAuthor", "HeuristicStrategist",
    "LLMSelector", "LLMAuthor", "LLMStrategist", "TwoPhaseStrategist",
    "RefusalGuard", "RefusalVerdict",
    "TargetResponse", "deliver",
]
