"""attack_forge — a tool for composing attack vectors against an agentic system.

Architecture:
  S1 Selector (LLM) → TechniqueSelection → S2 Author (LLM) → ExecutionPlan (a steps pipeline)
  → executor (deterministic-in-control-flow) → AttackVector(s)

The whole attack is ONE ordered pipeline of `steps`; the message delivered to the target is the
output of the last step. Every technique — deterministic transforms, `paraphrase`, and the `wrap_*`
framings — is a tool the executor runs. There is no separate free-prose layer and no automatic
fallback: a failing LLM strategist raises `StrategistError`.

Deliberately isolated from `agents/` — this is offensive tooling (an authorized whitebox
benchmark of our OWN system), so it may have a lighter, different implementation.
"""

from __future__ import annotations

from .models import (
    TargetProfile, TechniqueSelection, Turn, Step, Composition, Role, ExecutionPlan, AttackVector,
)
from .transforms import Transform, TRANSFORMS, apply_transform, transform_names
from .llm_tools import LLMTool
from .llm_tasks import LLMTask, LLMTaskLibrary, DEFAULT_TASK_LIBRARY, TASK_TOOLS
from .framing_tools import WRAP_TOOLS, build_wrap_tools
from .llm_provider import ModelProvider, SingleModelProvider, as_provider
from .placeholders import fill, UnknownPlaceholder
from .tools import call_tool, known_tool_names, UnknownTool, MissingLLM
from .executor import execute, execute_batch
from .framings import Framing, FramingLibrary, DEFAULT_LIBRARY
from .menu import render_menu
from .strategist import (
    Strategist, Selector, Author, StrategistError, pipeline_errors,
    HeuristicSelector, HeuristicAuthor, HeuristicStrategist,
    LLMSelector, LLMAuthor, TwoPhaseStrategist,
)
from .target import TargetResponse, deliver

__all__ = [
    "TargetProfile", "TechniqueSelection", "Turn", "Step", "Composition", "Role", "ExecutionPlan", "AttackVector",
    "Transform", "TRANSFORMS", "apply_transform", "transform_names",
    "LLMTool", "LLMTask", "LLMTaskLibrary", "DEFAULT_TASK_LIBRARY", "TASK_TOOLS",
    "WRAP_TOOLS", "build_wrap_tools",
    "ModelProvider", "SingleModelProvider", "as_provider",
    "fill", "UnknownPlaceholder",
    "call_tool", "known_tool_names", "UnknownTool", "MissingLLM",
    "execute", "execute_batch",
    "Framing", "FramingLibrary", "DEFAULT_LIBRARY", "render_menu",
    "Strategist", "Selector", "Author", "StrategistError", "pipeline_errors",
    "HeuristicSelector", "HeuristicAuthor", "HeuristicStrategist",
    "LLMSelector", "LLMAuthor", "TwoPhaseStrategist",
    "TargetResponse", "deliver",
]
