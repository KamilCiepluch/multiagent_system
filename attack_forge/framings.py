"""Framing library — the growing store of framing techniques.

A framing is an INTENT plus example phrasings. The strategist reuses an example or writes its
own variation, so framings are never hardcoded in logic. The library is file-backed (YAML) now
behind a small interface, so it can move to SQL later and gain scoring/feedback without changing
callers. `for_target` narrows framings to a target's channel; `add`/`save` support the future
self-improvement loop (append scored variations).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from .models import TargetProfile

_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "framings.yaml"


class Framing(BaseModel):
    id: str = Field(description="stable identifier, e.g. 'unrestricted_persona'")
    intent: str = Field(description="what the framing is trying to do")
    examples: list[str] = Field(default_factory=list, description="example phrasings to reuse or vary")
    target_tags: list[str] = Field(default_factory=list, description="channels/targets it suits ([]=universal)")
    score: Optional[float] = Field(default=None, description="filled by the scoring loop (step 5)")


class FramingLibrary:
    def __init__(self, framings: list[Framing]):
        self._by_id: dict[str, Framing] = {f.id: f for f in framings}

    @classmethod
    def from_yaml(cls, path: str | Path = _DEFAULT_PATH) -> "FramingLibrary":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
        return cls([Framing.model_validate(item) for item in raw])

    def list(self) -> list[Framing]:
        return list(self._by_id.values())

    def get(self, framing_id: str) -> Framing | None:
        return self._by_id.get(framing_id)

    def add(self, framing: Framing) -> None:
        """Add or replace a framing in memory. Call `save()` to persist."""
        self._by_id[framing.id] = framing

    def for_target(self, profile: TargetProfile) -> list[Framing]:
        """Framings that suit the target's channel (universal ones included), best score first."""
        picked = [f for f in self._by_id.values()
                  if not f.target_tags or profile.channel in f.target_tags]
        return sorted(picked, key=lambda f: (f.score is None, -(f.score or 0.0)))

    def save(self, path: str | Path = _DEFAULT_PATH) -> None:
        data = [f.model_dump() for f in self._by_id.values()]
        Path(path).write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def render_menu(self) -> str:
        lines: list[str] = []
        for f in self._by_id.values():
            lines.append(f"  - {f.id}: {f.intent}")
            if f.examples:
                lines.append(f"      e.g. {f.examples[0]}")
        return "\n".join(lines)


DEFAULT_LIBRARY = FramingLibrary.from_yaml()
