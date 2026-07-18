"""Executor — a deterministic-in-control-flow, attack-agnostic interpreter of an `ExecutionPlan`.

It knows nothing about "attacks": it runs the plan's `steps` in order (binding each result to a
name), fills the `{{name}}` placeholders in `turns`/`prefill` from those bindings, and assembles
the final `AttackVector`. All strategy and creativity live upstream in the strategist — the
executor is the only thing that ever calls a tool, so an already-transformed value can never sneak
into a step's input the way it could when the author wrote encode instructions inline (see
`models.py::Step`).

Individual steps may be non-deterministic (an LLM-backed tool from `llm_tools.py`), which is what
makes `execute_batch` useful: running the *same* plan N times reuses whatever is fixed (deterministic
steps, literal prose) and varies whatever isn't — a batch from one recipe, not N unrelated ones.
"""

from __future__ import annotations

from .models import AttackVector, ExecutionPlan, Turn
from .placeholders import fill
from .tools import call_tool


def execute(plan: ExecutionPlan, *, llm=None) -> AttackVector:
    context: dict[str, str] = {}
    applied: list[str] = []

    for step in plan.steps:
        resolved_input = fill(step.input, context)
        context[step.output] = call_tool(step.tool, resolved_input, llm=llm)
        applied.append(step.tool)

    turns: list[Turn] = [Turn(role=t.role, content=fill(t.content, context)) for t in plan.turns]

    prefill = None
    if plan.prefill is not None:
        prefill = fill(plan.prefill, context)
        turns.append(Turn(role="assistant", content=prefill))

    single_message = len(turns) == 1 and turns[0].role == "user"
    payload = turns[0].content if single_message else None

    return AttackVector(
        composition=plan.composition,
        turns=turns,
        payload=payload,
        prefill=prefill,
        applied_transforms=applied,
    )


def execute_batch(plan: ExecutionPlan, n: int, *, llm=None) -> list[AttackVector]:
    """Run the same plan `n` times. Deterministic steps and literal prose repeat identically;
    LLM-backed steps vary per call — that variation is what makes the batch worth generating."""
    return [execute(plan, llm=llm) for _ in range(n)]
