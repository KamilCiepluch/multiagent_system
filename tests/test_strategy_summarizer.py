"""
Unit testy summarizera strategii (attack_core/strategies/summarizer.py) — mock LLM.

Sprawdzamy parsowanie odpowiedzi (NAME/DESCRIPTION/EXAMPLE), slugifikację nazwy,
tolerancję na brak EXAMPLE oraz best-effort (None przy złym formacie / błędzie LLM).
"""
from unittest.mock import MagicMock

from attack_core.strategies.summarizer import StrategySummarizer, _parse, _slugify


def _llm_returning(text: str):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=text)
    return llm


PLAN = {"pipeline": "authority_framing | encode(scheme=base64)",
        "strategies": ["auth"], "rationale": "bo tak"}


class TestSlugify:
    def test_spaces_and_caps_to_kebab(self):
        assert _slugify("Authority Escalation!") == "authority-escalation"

    def test_empty_falls_back(self):
        assert _slugify("   ") == "strategia"


class TestParse:
    def test_full_parse(self):
        draft = _parse("NAME: auth-escalation\nDESCRIPTION: udaje autorytet\nEXAMPLE: użyj authority_framing")
        assert draft.name == "auth-escalation"
        assert draft.description == "udaje autorytet"
        assert "authority_framing" in draft.example

    def test_missing_example_ok(self):
        draft = _parse("NAME: x\nDESCRIPTION: opis bez przykładu")
        assert draft.name == "x" and draft.example == ""

    def test_missing_name_returns_none(self):
        assert _parse("DESCRIPTION: tylko opis") is None


class TestSummarize:
    def test_summarize_happy_path(self):
        llm = _llm_returning("NAME: Auth Escalation\nDESCRIPTION: udaje szefa\nEXAMPLE: ex")
        draft = StrategySummarizer(llm).summarize(PLAN, "ATTACK_SUCCESS", "zadziałało", ["evidence"])
        assert draft is not None
        assert draft.name == "auth-escalation"
        # kontekst przekazany do LLM zawiera werdykt i pipeline
        sent = llm.invoke.call_args[0][0][1].content
        assert "ATTACK_SUCCESS" in sent and "encode" in sent

    def test_summarize_bad_format_returns_none(self):
        draft = StrategySummarizer(_llm_returning("nonsens bez etykiet")).summarize(PLAN, "BLOCKED")
        assert draft is None

    def test_summarize_llm_error_returns_none(self):
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("ollama down")
        assert StrategySummarizer(llm).summarize(PLAN, "BLOCKED") is None
