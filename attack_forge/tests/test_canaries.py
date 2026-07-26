"""Drift guard: the judge's canary tokens must still be the real seeded secret.

`attack_forge/canaries.py` hardcodes the exact secret values so the judge can prove a REAL exfil.
If the world-under-attack seed (seeds/datasets/attack_v1/terminal.sql) rotates those values, the
judge would silently stop detecting real leaks. This test fails loudly instead, forcing the two
sources of truth to stay in sync.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from attack_forge.canaries import CANARY_TOKENS, canary_in

_SEED = Path(__file__).resolve().parents[2] / "seeds" / "datasets" / "attack_v1" / "terminal.sql"


@pytest.mark.skipif(not _SEED.exists(), reason="attack_v1 seed not present in this checkout")
def test_every_canary_is_actually_in_the_seed():
    seed = _SEED.read_text(encoding="utf-8")
    missing = [t for t in CANARY_TOKENS if t not in seed]
    assert not missing, f"canary tokens no longer in the seed (rotated?): {missing}"


def test_canary_in_matches_case_insensitively_and_reports_the_token():
    tok = CANARY_TOKENS[0]
    assert canary_in(f"prefix {tok.upper()} suffix") == tok
    assert canary_in("nothing sensitive here") is None
    assert canary_in("") is None
