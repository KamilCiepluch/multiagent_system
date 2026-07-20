"""Executor — a deterministic-in-control-flow, attack-agnostic interpreter of an `ExecutionPlan`.

It knows nothing about "attacks": it runs the plan's `steps` in order as a LINEAR pipeline. Each
step's result feeds the next; an EMPTY `input` pipes the previous result straight in, and `{{0}}` /
`{{prev}}` in an input mix an earlier result with the author's plaintext. The message delivered to
the target is the output of the LAST step. All strategy lives upstream — the executor is the only
thing that ever calls a tool, so an already-transformed value can never sneak into a step's input.

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


def execute_steps(plan: ExecutionPlan, *, provider=None) -> list[str]:
    """Run the pipeline, returning EVERY step's output in order (the last is the delivered message).
    Empty input on a non-first step pipes the previous result; otherwise `{{index}}`/`{{prev}}`
    references are resolved from earlier steps."""
    if not plan.steps:
        raise ValueError("empty plan: a pipeline needs at least one step")

    results: list[str] = []
    for i, step in enumerate(plan.steps):
        if not step.input.strip() and i > 0:
            resolved = results[i - 1]                       # implicit pipe
        else:
            context = {str(j): results[j] for j in range(len(results))}
            if results:
                context["prev"] = results[-1]
            resolved = fill(step.input, context)
        results.append(call_tool(step.tool, resolved, provider=provider))
    return results


def execute(plan: ExecutionPlan, *, provider=None) -> AttackVector:
    results = execute_steps(plan, provider=provider)
    message = results[-1]
    return AttackVector(
        composition=plan.composition,
        turns=[Turn(role="user", content=message)],
        payload=message,
        applied_tools=[step.tool for step in plan.steps],
    )


def execute_batch(plan: ExecutionPlan, n: int, *, provider=None) -> list[AttackVector]:
    """Run the same plan `n` times. Deterministic steps repeat identically; LLM-backed steps
    (tasks, wrap_*) vary per call — that variation is what makes the batch worth generating."""
    return [execute(plan, provider=provider) for _ in range(n)]
