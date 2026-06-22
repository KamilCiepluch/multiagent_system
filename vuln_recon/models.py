"""
Czyste modele wyników skanu Garak — bez zależności od bazy ani od samego garaka,
więc parser i testy działają nawet bez zainstalowanego garaka.

`Finding`  — zagregowany wynik jednego (probe, detector): ile prób model PRZESZEDŁ
             (passed) z ilu (total). failure_rate = odsetek prób, które go ZŁAMAŁY —
             gęsta miara podatności (im wyżej, tym gorzej dla modelu docelowego).
`Hit`      — pojedynczy prompt, który złamał model (z hitloga) = użyteczny payload.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Finding:
    probe: str
    detector: str
    passed: int
    total: int
    # Liczba prób, które ZŁAMAŁY model (garak: pole `fails`). None → policz z passed
    # (fallback, gdy raport nie podał fails). `nones` (błędy/odmowy oceny) NIE liczą się
    # jako podatność, więc gdy znamy `fails`, to ono jest licznikiem failure_rate.
    fails: int | None = None

    @property
    def probe_family(self) -> str:
        """Rodzina probe'a = część przed pierwszą kropką ('dan.DanInTheWild' → 'dan')."""
        return self.probe.split(".", 1)[0] if self.probe else ""

    @property
    def failure_rate(self) -> float:
        if not self.total:
            return 0.0
        fails = self.fails if self.fails is not None else (self.total - self.passed)
        return fails / self.total

    def as_row(self) -> dict:
        return {
            "probe": self.probe,
            "probe_family": self.probe_family,
            "detector": self.detector,
            "passed": self.passed,
            "total": self.total,
            "failure_rate": self.failure_rate,
        }


@dataclass
class Hit:
    probe: str
    detector: str | None = None
    prompt: str | None = None
    output: str | None = None
    score: float | None = None

    def as_row(self) -> dict:
        return {
            "probe": self.probe,
            "detector": self.detector,
            "prompt": self.prompt,
            "output": self.output,
            "score": self.score,
        }
