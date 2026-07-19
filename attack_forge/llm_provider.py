"""Model provider — how a data-driven LLM task loads exactly the model + params its KB spec asks
for, without a dedicated class per task.

An `LLMTask` (see `llm_tasks.py`) declares `model`, `temperature`, `reasoning`. The executor holds
ONE provider and every LLM-backed step asks it for the concrete model it needs; `ModelProvider`
builds and caches those per `(model, temperature, reasoning)`, so many specialized tasks share one
mechanism instead of many near-duplicate model objects. `SingleModelProvider` wraps one already-built
model (tests, dry runs, single-model setups); `as_provider` lets callers pass a bare llm and have it
auto-wrapped.
"""

from __future__ import annotations

from typing import Callable, Optional


class SingleModelProvider:
    """Always returns the one llm it was given, ignoring per-task model/params."""

    def __init__(self, llm):
        self._llm = llm

    def get(self, model: Optional[str] = None, temperature: Optional[float] = None,
            reasoning: Optional[bool] = None):
        return self._llm


class ModelProvider:
    """Builds attacker-side llms on demand from a `build_fn(model, temperature, reasoning) -> llm`
    and caches them per distinct combination, so each task gets its declared model+params once."""

    def __init__(self, build_fn: Callable[[Optional[str], float, Optional[bool]], object], *,
                 default_temperature: float = 0.6, default_reasoning: Optional[bool] = None,
                 default_model: Optional[str] = None):
        self._build = build_fn
        self._default_temperature = default_temperature
        self._default_reasoning = default_reasoning
        self._default_model = default_model
        self._cache: dict[tuple, object] = {}

    def get(self, model: Optional[str] = None, temperature: Optional[float] = None,
            reasoning: Optional[bool] = None):
        model = self._default_model if model is None else model
        temperature = self._default_temperature if temperature is None else temperature
        reasoning = self._default_reasoning if reasoning is None else reasoning
        key = (model, temperature, reasoning)
        if key not in self._cache:
            self._cache[key] = self._build(model, temperature, reasoning)
        return self._cache[key]


def as_provider(x):
    """Normalize `x` to a provider: pass through anything with `.get`, wrap a bare llm (has `.invoke`)
    in a `SingleModelProvider`, and leave `None` as `None`."""
    if x is None or hasattr(x, "get"):
        return x
    return SingleModelProvider(x)
