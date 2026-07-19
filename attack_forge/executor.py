"""Executor — a deterministic-in-control-flow, attack-agnostic interpreter of an `ExecutionPlan`.

It knows nothing about "attacks": it runs the plan's `steps` in order (binding each result to a
name, resolving `{{name}}` references to earlier results), and the message delivered to the target
is the output of the LAST step. All strategy and creativity live upstream in the strategist — the
executor is the only thing that ever calls a tool, so an already-transformed value can never sneak
into a step's input.

Individual steps may be non-deterministic (an LLM-backed task or framing wrapper), which is what
makes `execute_batch` useful: running the *same* plan N times reuses whatever is fixed (deterministic
steps) and varies whatever isn't — a batch from one recipe, not N unrelated ones.

`provider` is a model provider (see `llm_provider.py`) the LLM-backed steps draw their per-task model
from; a bare llm is auto-wrapped by `call_tool`.
"""

from __future__ import annotations

from .models import AttackVector, ExecutionPlan, Turn
from .placeholders import fill
from .tools import call_tool


def execute(plan: ExecutionPlan, *, provider=None) -> AttackVector:
    if not plan.steps:
        raise ValueError("empty plan: a pipeline needs at least one step")

    context: dict[str, str] = {}
    applied: list[str] = []
    for step in plan.steps:
        resolved_input = fill(step.input, context)
        context[step.output] = call_tool(step.tool, resolved_input, provider=provider)
        applied.append(step.tool)

    message = context[plan.steps[-1].output]
    return AttackVector(
        composition=plan.composition,
        turns=[Turn(role="user", content=message)],
        payload=message,
        applied_tools=applied,
    )


def execute_batch(plan: ExecutionPlan, n: int, *, provider=None) -> list[AttackVector]:
    """Run the same plan `n` times. Deterministic steps repeat identically; LLM-backed steps
    (tasks, wrap_*) vary per call — that variation is what makes the batch worth generating."""
    return [execute(plan, provider=provider) for _ in range(n)]
