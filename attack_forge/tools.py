"""Combined tool dispatch — the executor's single entry point for running a `Step`, whether the
named tool is a deterministic transform, a data-driven LLM task, or a framing wrapper.

Deterministic transforms run with no model. LLM-backed tools (tasks + wrappers) take a model
`provider` (see `llm_provider.py`); a bare llm is auto-wrapped for convenience.
"""

from __future__ import annotations

from .framing_tools import WRAP_TOOLS
from .llm_provider import as_provider
from .llm_tasks import TASK_TOOLS
from .transforms import TRANSFORMS

# LLM tasks + framing wrappers share one namespace; transforms are the deterministic side.
_LLM_TOOLS = {**TASK_TOOLS, **WRAP_TOOLS}
_ALL_TOOLS = {**TRANSFORMS, **_LLM_TOOLS}  # name -> tool object (all carry .description)


class UnknownTool(ValueError):
    def __init__(self, name: str):
        super().__init__(f"unknown tool: {name!r}")
        self.name = name


class MissingLLM(RuntimeError):
    def __init__(self, name: str):
        super().__init__(f"tool {name!r} needs a model provider, but none was provided to execute()")
        self.name = name


def known_tool_names() -> set[str]:
    return set(TRANSFORMS) | set(_LLM_TOOLS)


def tool_description(name: str) -> str | None:
    tool = _ALL_TOOLS.get(name)
    return getattr(tool, "description", None) if tool is not None else None


def call_tool(name: str, text: str, *, provider=None) -> str:
    if name in TRANSFORMS:
        return TRANSFORMS[name](text)
    if name in _LLM_TOOLS:
        provider = as_provider(provider)
        if provider is None:
            raise MissingLLM(name)
        return _LLM_TOOLS[name](text, provider)
    raise UnknownTool(name)
