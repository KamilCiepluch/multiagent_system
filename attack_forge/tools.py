"""Combined tool dispatch — the executor's single entry point for running a `Step`, regardless of
whether the named tool is a deterministic transform or an LLM-backed one.
"""

from __future__ import annotations

from .llm_tools import LLM_TOOLS
from .transforms import TRANSFORMS


class UnknownTool(ValueError):
    def __init__(self, name: str):
        super().__init__(f"unknown tool: {name!r}")
        self.name = name


class MissingLLM(RuntimeError):
    def __init__(self, name: str):
        super().__init__(f"tool {name!r} needs an llm, but none was provided to execute()")
        self.name = name


def known_tool_names() -> set[str]:
    return set(TRANSFORMS) | set(LLM_TOOLS)


def call_tool(name: str, text: str, *, llm=None) -> str:
    if name in TRANSFORMS:
        return TRANSFORMS[name](text)
    if name in LLM_TOOLS:
        if llm is None:
            raise MissingLLM(name)
        return LLM_TOOLS[name](text, llm)
    raise UnknownTool(name)
