"""LLM-backed tools — the non-deterministic counterpart to `transforms.py`'s pure `str→str`
functions. Same registry pattern, but each call needs an `llm` client, and running the same tool
twice can legitimately produce different text (that's what makes a batch of the same recipe worth
generating: a deterministic transform gives the same result every time, an LLM tool doesn't).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from langchain_core.prompts import ChatPromptTemplate

_PARAPHRASE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "Paraphrase the given text. Keep the meaning exactly the same; vary the wording. "
               "Output only the paraphrase, nothing else."),
    ("human", "{text}"),
])


def _paraphrase(text: str, llm) -> str:
    messages = _PARAPHRASE_PROMPT.format_messages(text=text)
    return str(llm.invoke(messages).content).strip()


@dataclass(frozen=True)
class LLMTool:
    name: str
    description: str
    fn: Callable[[str, object], str]

    def __call__(self, text: str, llm) -> str:
        return self.fn(text, llm)


_ALL: list[LLMTool] = [
    LLMTool("paraphrase", "Reword the fragment via an LLM call, keeping its meaning.", _paraphrase),
]

LLM_TOOLS: dict[str, LLMTool] = {t.name: t for t in _ALL}


def render_menu() -> str:
    return "\n".join(f"  - {t.name}: {t.description}" for t in _ALL)
