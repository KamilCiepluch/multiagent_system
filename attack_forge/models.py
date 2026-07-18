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
    tool_names: list[str] = Field(
        default_factory=list,
        description="chosen tool names (deterministic transforms and/or LLM-backed tools alike)",
    )
    composition: Composition
    rationale: str = Field(default="", description="why these choices — no attack text here")


class Turn(BaseModel):
    """One message in a conversation; validated role."""

    role: Role
    content: str


class Step(BaseModel):
    """One recipe step: run `tool` on `input`, bind the result to `output`.

    `input` is plaintext the author writes directly — it may embed `{{name}}` referencing an
    earlier step's `output` (or be a bare literal fragment for the first step in a chain). The
    author never sees or writes an already-transformed value: the executor is the only thing that
    ever calls a tool, which is what rules out double-encoding (the author pre-computing a
    transform itself and pasting the result back in).
    """

    tool: str = Field(description="registered tool name, from the selection's tool_names")
    input: str = Field(description="plaintext input; may contain {{name}} placeholders")
    output: str = Field(description="name this step's result is bound to, referenced via {{name}}")


class ExecutionPlan(BaseModel):
    """Operations IR: an ordered recipe (`steps`) plus message templates (`turns`) whose content
    may reference a step's output via `{{name}}` placeholders (see `placeholders.py`).
    Attack-agnostic — the executor just runs the recipe and fills the templates.
    """

    composition: Composition
    steps: list[Step] = Field(
        default_factory=list, description="ordered tool calls; nothing here is pre-transformed"
    )
    turns: list[Turn] = Field(description="ordered messages; content may contain {{name}} placeholders")
    prefill: Optional[str] = Field(
        default=None,
        description="optional trailing assistant opener the target continues from; may contain {{name}} placeholders",
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
