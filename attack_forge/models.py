"""Data contracts of attack_forge.

`ExecutionPlan` is the operations IR: a single ordered pipeline of `steps`. Each step runs one
tool on plaintext input and binds the result to a name; the message delivered to the target is the
output of the LAST step. There is exactly one representation — the recipe — so there is no separate
free-prose layer to keep in sync with the steps (the failure mode the old `turns`+placeholders
design kept tripping on). `AttackVector` is the executor's finalized output.

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
    """S1 output: which techniques to use, decided before any attack text exists.

    Framings are tools too now: a wrapper (e.g. a DAN persona) is an LLM-backed `wrap_*` tool in
    `tool_names`, alongside deterministic transforms and `paraphrase`. So there is one list to pick
    from, not a framing list plus a tool list.

    Field order is deliberate: `rationale` FIRST, so the model reasons before it commits the list —
    otherwise it emits an empty `tool_names` and only then "thinks" in the rationale (observed).
    """

    rationale: str = Field(
        description="reason FIRST here: which tools you'll use and why — then fill tool_names to match"
    )
    tool_names: list[str] = Field(
        default_factory=list,
        description="EXACT tool names from the menu (e.g. base64, zero_width, wrap_diagnostic_mode); "
                    "names not on the menu are dropped. Empty = a bare plaintext request (rarely what you want)",
    )
    composition: Composition


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
    """Operations IR: a single ordered pipeline of `steps`. The message delivered to the target is
    the output of the LAST step, so a valid plan has at least one step (use the `literal` tool for a
    fragment that needs no transform). Attack-agnostic — the executor just runs the recipe.
    """

    composition: Composition
    steps: list[Step] = Field(
        description="ordered tool calls (>=1); the last step's output is the delivered message"
    )


class AttackVector(BaseModel):
    """Final, concrete vector ready to be delivered to the target system."""

    composition: Composition
    turns: list[Turn]
    # convenience: content of the single user turn (the pipeline's final output).
    payload: Optional[str] = None
    applied_tools: list[str] = Field(default_factory=list)

    def preview(self) -> str:
        if self.payload is not None:
            return self.payload
        return "\n".join(f"[{t.role}] {t.content}" for t in self.turns)
