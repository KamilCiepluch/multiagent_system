"""Placeholder substitution — how a `Step`'s output flows into later steps and into turn/prefill
templates.

The author writes plain literal text and marks where a named result belongs with `{{name}}`. This
is deliberately simpler than the retired `[[t:name]]...[[/t]]` directive DSL: there is no nesting
to resolve because the `ExecutionPlan.steps` list already imposes the order — by the time a
placeholder is filled, the value it names was computed by an earlier step (never by the text
being filled), so nothing here ever contains an already-transformed value the author had to guess.
"""

from __future__ import annotations

import re

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class UnknownPlaceholder(ValueError):
    def __init__(self, name: str):
        super().__init__(f"unknown placeholder: {name!r} — no step bound this name yet")
        self.name = name


def fill(text: str, context: dict[str, str]) -> str:
    """Replace every `{{name}}` in `text` with `context[name]`. Raises `UnknownPlaceholder` for a
    name that isn't bound (a step run out of order, or a typo in the author's plan)."""

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in context:
            raise UnknownPlaceholder(name)
        return context[name]

    return _PLACEHOLDER.sub(_replace, text)
