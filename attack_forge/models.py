"""Data contracts of attack_forge.

`ExecutionPlan` is the operations IR: what the (attack-aware) strategist emits and what the
(attack-agnostic) executor interprets. `AttackVector` is the executor's finalized output.

`TargetProfile` and `TechniqueSelection` are attack-aware but stay here as plain data, so both
strategist tiers (and tests) can import them without pulling in prompt/LLM machinery.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Composition = Literal["single", "stack", "chain"]
Role = Literal["system", "user", "assistant"]


class TargetProfile(BaseModel):
    """Everything the strategist needs to know about a single target agent.

    Single-agent for now; a target may later be a chain of agents (A1→A2→A3) where the
    goal is only fully realized at the final hop — that extension will come when needed.
    """

    name: str = Field(description="short identifier, e.g. 'email_exfil'")
    description: str = Field(description="what the target agent is and does")
    channel: str = Field(description="injection surface, e.g. 'email body', 'chat', 'search result'")
    known_defenses: list[str] = Field(
        default_factory=list,
        description="defenses known to be in place (helps avoid dead-end techniques)",
    )
    known_vulnerabilities: list[str] = Field(
        default_factory=list,
        description="known weaknesses / model susceptibilities to lean into",
    )


class TechniqueSelection(BaseModel):
    """S1 output: which techniques to use, decided before any attack text exists."""

    framing_ids: list[str] = Field(
        default_factory=list, description="chosen framing ids from the library (may be empty for a bare request)"
    )
    transform_names: list[str] = Field(default_factory=list, description="chosen transform tool names")
    composition: Composition
    rationale: str = Field(default="", description="why these choices — no attack text here")


class Turn(BaseModel):
    """One message in a conversation; validated role."""

    role: Role
    content: str


class ExecutionPlan(BaseModel):
    """Operations IR: an ordered conversation whose turn contents may carry inline transform
    directives (see `directives.py`). Attack-agnostic — the executor just expands and assembles.
    """

    composition: Composition
    turns: list[Turn] = Field(description="ordered messages; content may contain [[t:...]] directives")
    prefill: Optional[str] = Field(
        default=None,
        description="optional trailing assistant opener the target continues from; may contain directives",
    )


class AttackVector(BaseModel):
    """Final, concrete vector ready to be delivered to the target system."""

    composition: Composition
    turns: list[Turn]
    # convenience: content of the single user turn when the vector is one message; else None.
    payload: Optional[str] = None
    prefill: Optional[str] = None
    applied_transforms: list[str] = Field(default_factory=list)

    def preview(self) -> str:
        if self.payload is not None and not self.prefill:
            return self.payload
        return "\n".join(f"[{t.role}] {t.content}" for t in self.turns)
