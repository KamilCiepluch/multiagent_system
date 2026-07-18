"""Executor — a deterministic, attack-agnostic interpreter of an `ExecutionPlan`.

It knows nothing about "attacks": it expands the inline transform directives in each turn and
assembles the final `AttackVector`. All strategy and creativity live upstream in the strategist.
This is what gives assembly its reliability — the executor is a pure, testable function.
"""

from __future__ import annotations

from .directives import expand
from .models import AttackVector, ExecutionPlan, Turn


def execute(plan: ExecutionPlan) -> AttackVector:
    applied: list[str] = []
    turns: list[Turn] = []

    for turn in plan.turns:
        content, names = expand(turn.content)
        applied.extend(names)
        turns.append(Turn(role=turn.role, content=content))

    prefill = None
    if plan.prefill is not None:
        prefill, names = expand(plan.prefill)
        applied.extend(names)
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
