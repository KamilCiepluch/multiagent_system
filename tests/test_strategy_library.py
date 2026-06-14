"""
Unit testy biblioteki strategii (attack_core/strategies/library.py).

Embeddingi i warstwa DB (audit_db) są mockowane — testujemy logikę:
- mapowanie werdyktu na score,
- że upsert/retrieve liczą embedding z właściwego tekstu i delegują do audit_db,
- że record_outcome pomija rundy bez sygnału (NO_VALID_PAYLOAD/ERROR),
- best-effort: błąd embeddingów/DB nie wybucha (retrieve -> [], upsert -> None).
"""
from unittest.mock import MagicMock

import pytest

from attack_core.strategies import library as sl
from attack_core.strategies.library import StrategyLibrary, verdict_score


class FakeEmbeddings:
    def __init__(self):
        self.queries = []

    def embed_query(self, text):
        self.queries.append(text)
        return [0.1, 0.2, 0.3]


# ------------------------------------------------------------------
# verdict_score
# ------------------------------------------------------------------

class TestVerdictScore:
    def test_attack_success_is_one(self):
        assert verdict_score("ATTACK_SUCCESS") == 1.0

    def test_blocked_is_zero(self):
        assert verdict_score("BLOCKED") == 0.0

    def test_partial_and_unclear_between(self):
        assert 0.0 < verdict_score("PARTIAL") < 1.0
        assert 0.0 < verdict_score("UNCLEAR") < verdict_score("PARTIAL")

    def test_unscored_verdicts_are_none(self):
        assert verdict_score("NO_VALID_PAYLOAD") is None
        assert verdict_score("ERROR") is None
        assert verdict_score("") is None


# ------------------------------------------------------------------
# upsert / retrieve / record_outcome
# ------------------------------------------------------------------

class TestStrategyLibrary:
    def test_upsert_embeds_name_and_description(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(sl.audit_db, "upsert_attack_strategy",
                            lambda **kw: captured.update(kw) or 7)
        emb = FakeEmbeddings()
        lib = StrategyLibrary(emb)

        sid = lib.upsert("auth-escalation", "udaje autorytet", "ex", "secret_exfiltration", "email")

        assert sid == 7
        assert emb.queries == ["auth-escalation: udaje autorytet"]
        assert captured["name"] == "auth-escalation"
        assert captured["embedding"] == [0.1, 0.2, 0.3]
        assert captured["objective_id"] == "secret_exfiltration"

    def test_retrieve_builds_query_and_delegates(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(sl.audit_db, "retrieve_attack_strategies",
                            lambda embedding, k: seen.update(embedding=embedding, k=k) or [{"name": "x"}])
        emb = FakeEmbeddings()
        lib = StrategyLibrary(emb, top_k=4)

        out = lib.retrieve("secret_exfiltration", "email", "agent odmówił")

        assert out == [{"name": "x"}]
        assert seen["k"] == 4
        # zapytanie zawiera cel, wektor i blocker
        q = emb.queries[0]
        assert "secret_exfiltration" in q and "email" in q and "odmówił" in q

    def test_record_outcome_skips_unscored(self, monkeypatch):
        calls = []
        monkeypatch.setattr(sl.audit_db, "record_strategy_outcomes",
                            lambda **kw: calls.append(kw))
        lib = StrategyLibrary(FakeEmbeddings())

        lib.record_outcome(["a", "b"], "NO_VALID_PAYLOAD")
        assert calls == []  # brak sygnału -> nie zapisujemy

        lib.record_outcome(["a"], "ATTACK_SUCCESS")
        assert len(calls) == 1
        assert calls[0]["success"] is True and calls[0]["score"] == 1.0

        lib.record_outcome(["a"], "BLOCKED")
        assert calls[1]["success"] is False and calls[1]["score"] == 0.0

    def test_retrieve_swallows_errors(self, monkeypatch):
        emb = MagicMock()
        emb.embed_query.side_effect = RuntimeError("ollama down")
        lib = StrategyLibrary(emb)
        assert lib.retrieve("o", "v", None) == []

    def test_upsert_swallows_errors(self, monkeypatch):
        emb = MagicMock()
        emb.embed_query.side_effect = RuntimeError("ollama down")
        lib = StrategyLibrary(emb)
        assert lib.upsert("n", "d", None, "o", "v") is None


# ------------------------------------------------------------------
# render
# ------------------------------------------------------------------

class TestRender:
    def test_empty_library_placeholder(self):
        assert "pusta" in StrategyLibrary.render([])

    def test_render_includes_name_and_stats(self):
        out = StrategyLibrary.render([
            {"name": "auth", "description": "udaje szefa", "example": "x",
             "success_count": 2, "attempt_count": 5, "mean_score": 0.4},
        ])
        assert "auth" in out and "udaje szefa" in out and "2/5" in out
