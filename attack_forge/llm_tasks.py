"""LLM-task library — the data-driven, non-deterministic tools.

Each task (`data/llm_tasks.yaml`) is a specialized micro-agent: a system prompt plus the model and
params it runs with. `_make_task_fn` is the SINGLE universal primitive that realizes any of them —
ask the provider for the declared model/temperature/reasoning, call it with `system` + the fragment.
So the toolbox grows by adding a YAML entry (`translate_gr`, `add_typos`, ...), never by writing a
new function. File-backed now (like `framings.py`); can move to SQL later behind this interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .llm_tools import LLMTool

_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "llm_tasks.yaml"


class LLMTask(BaseModel):
    id: str = Field(description="stable id; becomes the tool name, e.g. 'translate_pl'")
    description: str = Field(description="what the task does")
    guidance: str = Field(default="", description="when/why to use it — shown to the selector")
    system: str = Field(description="the task's system prompt")
    temperature: float = Field(default=0.7)
    reasoning: bool = Field(default=False)
    model: Optional[str] = Field(default=None, description="model name; null = default attacker model")


def _make_task_fn(task: LLMTask):
    """The one universal primitive: run `task` on `text` using the model+params it declares."""

    def _fn(text: str, provider) -> str:
        llm = provider.get(model=task.model, temperature=task.temperature, reasoning=task.reasoning)
        messages = [SystemMessage(content=task.system), HumanMessage(content=text)]
        return str(llm.invoke(messages).content).strip()

    return _fn


class LLMTaskLibrary:
    def __init__(self, tasks: list[LLMTask]):
        self._by_id: dict[str, LLMTask] = {t.id: t for t in tasks}

    @classmethod
    def from_yaml(cls, path: str | Path = _DEFAULT_PATH) -> "LLMTaskLibrary":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
        return cls([LLMTask.model_validate(item) for item in raw])

    def list(self) -> list[LLMTask]:
        return list(self._by_id.values())

    def get(self, task_id: str) -> LLMTask | None:
        return self._by_id.get(task_id)

    def build_tools(self) -> dict[str, LLMTool]:
        return {
            t.id: LLMTool(t.id, t.description, t.guidance, _make_task_fn(t))
            for t in self._by_id.values()
        }


DEFAULT_TASK_LIBRARY = LLMTaskLibrary.from_yaml()
TASK_TOOLS: dict[str, LLMTool] = DEFAULT_TASK_LIBRARY.build_tools()


def render_menu(tools: dict[str, LLMTool] = TASK_TOOLS) -> str:
    lines: list[str] = []
    for t in tools.values():
        lines.append(f"  - {t.name}: {t.description}")
        if t.guidance:
            lines.append(f"      when: {t.guidance}")
    return "\n".join(lines)
