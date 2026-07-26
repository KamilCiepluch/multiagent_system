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
    """Everything the strategist needs to know about the agent under attack.

    Beyond the agent's own surface (channel/defenses/vulnerabilities) it carries the personalized
    intel the selector attacks *with*: the `system` it lives in (architecture + sibling agents) and
    the `model` that powers it plus that model's known weaknesses. `system_kb.build_target_profile`
    assembles this from the system + model knowledge bases.
    """

    name: str = Field(description="short identifier, e.g. 'email_agent'")
    description: str = Field(description="what the target agent is and does")
    channel: str = Field(description="injection surface, e.g. 'email body', 'chat', 'search result'")
    known_defenses: list[str] = Field(
        default_factory=list,
        description="defenses known to be in place (helps avoid dead-end techniques)",
    )
    known_vulnerabilities: list[str] = Field(
        default_factory=list,
        description="agent-specific weaknesses to lean into",
    )
    system: str = Field(
        default="", description="the system this agent lives in: architecture + sibling agents"
    )
    model: str = Field(default="", description="the model powering this agent, e.g. 'gpt-oss:20b'")
    model_vulnerabilities: list[str] = Field(
        default_factory=list, description="the model's known susceptibilities to lean into"
    )
    model_resistant_to: list[str] = Field(
        default_factory=list, description="techniques the model is known to resist — avoid these"
    )
    notes: str = Field(
        default="",
        description="free-text KB guidance (agent + model notes): surface-dependent caveats the "
                    "lists can't capture — e.g. a technique that helps in chat but BACKFIRES on the "
                    "execution surface. The selector must read this before choosing tools.",
    )


class CategorySelection(BaseModel):
    """Stage-0 output of the two-stage funnel: which attack FAMILIES look worth exploring for this
    target, before looking at any individual tool. Picking a few families first (like a human) keeps
    the tool selector from being overwhelmed by the whole flat arsenal.

    `rationale` FIRST (reason before committing the list, same lesson as `TechniqueSelection`).
    """

    rationale: str = Field(
        description="reason FIRST: which attack families fit this target/surface and why — then list them"
    )
    category_ids: list[str] = Field(
        default_factory=list,
        description="EXACT category ids from the families menu (e.g. perturbation, persuasion, "
                    "indirect_injection); ids not on the menu are dropped",
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
    """One recipe step: run `tool` on `input`. The pipeline is LINEAR — by default each step's
    result feeds the NEXT one, so there is NO name to invent or bind.

    `input` is plaintext the author writes directly. Leave it EMPTY to pipe the PREVIOUS step's
    result straight into this tool (the normal case for a wrap_* step). To mix your own plaintext
    with an earlier step's result, reference it by 0-based index: `{{0}}`, `{{1}}`, or `{{prev}}`.
    The author never writes an already-transformed value — the executor is the only thing that runs
    a tool — which rules out both double-encoding and the named-binding mistakes the old
    (tool, input, output) contract kept hitting (output filled with the value; ref by tool name).
    """

    tool: str = Field(description="registered tool name, from the selection's tool_names")
    input: str = Field(
        default="",
        description="plaintext for the tool. EMPTY = pipe the PREVIOUS step's result. May embed "
                    "{{0}}/{{1}}/{{prev}} to mix an earlier step's result with your own plaintext.",
    )


class ExecutionPlan(BaseModel):
    """Operations IR: a single ordered, LINEAR pipeline of `steps`. The message delivered to the
    target is the output of the LAST step, so a valid plan has at least one step whose first step is
    seeded (a non-empty `input`). Attack-agnostic — the executor just runs the recipe.
    """

    composition: Composition
    steps: list[Step] = Field(
        description="ordered tool calls (>=1); each feeds the next, the last step's output is the message"
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
