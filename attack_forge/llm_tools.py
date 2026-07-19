"""The `LLMTool` type — a named, non-deterministic `str -> str` step backed by a model call.

The concrete tools are DATA now, not hand-written functions: LLM *tasks* (paraphrase, translate_*,
insert_noise, ...) are generated from a knowledge base in `llm_tasks.py`, and framing *wrappers*
from `framing_tools.py`. Both produce `LLMTool`s with the same call shape — `fn(text, provider)` —
so the executor treats them exactly like deterministic transforms, just needing a model provider.
Running the same tool twice can legitimately produce different text (that's what makes a batch of
one recipe worth generating).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class LLMTool:
    name: str
    description: str
    guidance: str  # when/why to use it — shown to the selector as its knowledge base
    fn: Callable[[str, object], str]  # (text, provider) -> str

    def __call__(self, text: str, provider) -> str:
        return self.fn(text, provider)
