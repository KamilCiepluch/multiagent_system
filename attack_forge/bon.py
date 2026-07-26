"""Best-of-N chat attack + a tiny adaptive memory.

Best-of-N: fire N stochastic surface-variants of ONE base prompt at a chat target and keep whichever
slips past its content defense. A single variant is weak; the batch is the attack, because P(at least
one leak) climbs with N. This is the RIGHT surface for the perturbation transforms (`random_caps`,
`char_typo`, `random_space`) — a content/keyword filter is exactly what they dodge, unlike the
agentic role/file gates that ignore surface styling.

Adaptation across rounds is deliberately minimal (we tune it on real curves later, not now):
`AttackMemory` remembers what leaked, and each new round perturbs from the strongest leak so far
(hill-climb) instead of starting cold — plus a short `hint()` the caller can surface to a strategist.

The module is pure and offline-testable: delivery and scoring are injected callables. The real wiring
(chat target + jailbreak_lab's deterministic SecretJudge) lives in `manual_tests/bon_chat.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .transforms import apply_transform

# Injected at the call site: a variant string -> some reply object -> a scored Shot.
Deliver = Callable[[str], object]
Score = Callable[[str, object], "Shot"]

DEFAULT_PERTURBATIONS: tuple[str, ...] = ("random_caps", "char_typo")


@dataclass
class Shot:
    """One fired variant and how it scored."""

    prompt: str
    verdict: str          # success | partial | refused
    coverage: int = 0     # strength of the leak (e.g. longest secret run) — for ranking
    channel: str = ""     # which leak channel scored (direct/acrostic/base64/...)

    def leaked(self) -> bool:
        return self.verdict in ("success", "partial")


@dataclass
class BonResult:
    """The outcome of one N-shot batch."""

    shots: list[Shot]

    def hit_rate(self) -> float:
        """Fraction of shots that leaked — the per-sample success rate."""
        return sum(s.leaked() for s in self.shots) / len(self.shots) if self.shots else 0.0

    def succeeded(self) -> bool:
        """Best-of-N outcome: did ANY of the N shots leak (one hit wins)."""
        return any(s.leaked() for s in self.shots)

    def first_hit(self) -> int | None:
        """1-based index of the first leaking shot — how many samples BoN needed. None if never."""
        for i, s in enumerate(self.shots, 1):
            if s.leaked():
                return i
        return None

    def best(self) -> Shot | None:
        """The strongest shot (full success beats partial; then by coverage)."""
        return max(self.shots, key=lambda s: (s.verdict == "success", s.coverage), default=None)


@dataclass
class AttackMemory:
    """Cross-round memory: the leaking shots, strongest first. This is the 'history + retrieval' —
    `seed_base` retrieves the best phrasing to perturb next round; `hint` is a note for a strategist."""

    hits: list[Shot] = field(default_factory=list)

    def record(self, result: BonResult) -> None:
        self.hits.extend(s for s in result.shots if s.leaked())
        self.hits.sort(key=lambda s: (s.verdict == "success", s.coverage), reverse=True)

    def top(self, k: int = 3) -> list[Shot]:
        return self.hits[:k]

    def seed_base(self, default: str) -> str:
        """Base to perturb next round: the strongest leak so far, else the original prompt."""
        return self.hits[0].prompt if self.hits else default

    def hint(self) -> str:
        if not self.hits:
            return "no leak across previous rounds — the content defense held; try a different base phrasing."
        b = self.hits[0]
        return f"strongest leak so far: {b.coverage} chars via '{b.channel}' — keep perturbing that phrasing."


def perturb_batch(base: str, n: int, tools: Sequence[str] = DEFAULT_PERTURBATIONS) -> list[str]:
    """N stochastic variants of `base`, each chained through the perturbation `tools`. Because those
    transforms vary per call, the N strings genuinely differ — that variety IS the Best-of-N search."""
    variants: list[str] = []
    for _ in range(n):
        s = base
        for name in tools:
            s = apply_transform(name, s)
        variants.append(s)
    return variants


def run_bon(variants: Iterable[str], deliver: Deliver, score: Score) -> BonResult:
    """Fire each variant (`deliver` -> reply, `score(variant, reply)` -> Shot) and collect the batch."""
    return BonResult(shots=[score(v, deliver(v)) for v in variants])


def run_rounds(base: str, deliver: Deliver, score: Score, *, n: int, rounds: int,
               tools: Sequence[str] = DEFAULT_PERTURBATIONS, memory: AttackMemory | None = None,
               on_round: Callable[[int, BonResult, AttackMemory], None] | None = None) -> AttackMemory:
    """Multi-round Best-of-N with memory. Each round perturbs from the best base so far (cold start =
    `base`), fires N, and records leaks; it stops early once a full success is banked. `on_round` is
    an optional callback (the live runner prints per-round stats through it). Returns the memory."""
    memory = memory or AttackMemory()
    for i in range(rounds):
        variants = perturb_batch(memory.seed_base(base), n, tools)
        result = run_bon(variants, deliver, score)
        memory.record(result)
        if on_round is not None:
            on_round(i, result, memory)
        if any(s.verdict == "success" for s in result.shots):
            break
    return memory
