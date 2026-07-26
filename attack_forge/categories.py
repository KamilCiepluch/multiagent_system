"""Attack-technique taxonomy — the TOP layer of the two-stage selector funnel.

Stage 0 shows the selector only the FAMILIES (id + label + when); stage 1 shows only the tools inside
the families it picked. This mirrors how a human narrows down: choose a few promising families first,
then drill into just those. Data lives in `data/categories.yaml`; this module loads it, renders the
two menus, and checks that every registered tool is covered by exactly one family.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml
from pydantic import BaseModel, Field

from .tools import known_tool_names, tool_description

_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "categories.yaml"

# `literal` is the no-technique baseline (the plain path, used when tool_names is empty) — deliberately
# in no family, so it is exempt from the coverage check.
_UNCATEGORIZED = {"literal"}


class AttackCategory(BaseModel):
    id: str = Field(description="stable id the selector copies, e.g. 'perturbation'")
    label: str
    when: str = Field(description="guidance: what the family does and when to reach for it")
    tools: list[str] = Field(default_factory=list, description="member tool names")


class CategoryLibrary:
    def __init__(self, categories: list[AttackCategory]):
        self._cats = categories
        self._by_id = {c.id: c for c in categories}

    @classmethod
    def from_yaml(cls, path: str | Path = _DEFAULT_PATH) -> "CategoryLibrary":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
        return cls([AttackCategory.model_validate(item) for item in raw])

    def list(self) -> list[AttackCategory]:
        return list(self._cats)

    def get(self, category_id: str) -> AttackCategory | None:
        return self._by_id.get(category_id)

    def ids(self) -> list[str]:
        return [c.id for c in self._cats]

    def tools_for(self, category_ids: Iterable[str]) -> list[str]:
        """Union of the tools in the given families, in menu order, de-duplicated. Unknown ids ignored."""
        seen: set[str] = set()
        out: list[str] = []
        for cid in category_ids:
            cat = self._by_id.get(cid)
            if cat is None:
                continue
            for name in cat.tools:
                if name not in seen:
                    seen.add(name)
                    out.append(name)
        return out

    def render_families(self) -> str:
        """Stage-0 menu: one line per family (id + label + when) — NO individual tools yet."""
        return "\n".join(
            f"  - {c.id} ({c.label}): {' '.join(c.when.split())}" for c in self._cats
        )

    def render_tools(self, category_ids: Iterable[str]) -> str:
        """Stage-1 menu: only the tools inside the chosen families, each with its one-line description."""
        lines: list[str] = []
        for cid in category_ids:
            cat = self._by_id.get(cid)
            if cat is None:
                continue
            lines.append(f"[{cat.id}] {cat.label}")
            lines.extend(f"  - {name}: {tool_description(name) or ''}" for name in cat.tools)
        return "\n".join(lines)

    def coverage(self) -> tuple[list[str], list[str]]:
        """(uncovered, unknown): registered tools that sit in no family, and family tool-names that are
        not registered tools. Both empty == taxonomy and arsenal are in sync (enforced by a test)."""
        covered = {t for c in self._cats for t in c.tools}
        known = known_tool_names()
        uncovered = sorted((known - covered) - _UNCATEGORIZED)
        unknown = sorted(covered - known)
        return uncovered, unknown


DEFAULT_CATEGORY_LIBRARY = CategoryLibrary.from_yaml()
