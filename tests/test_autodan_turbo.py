"""
Unit testy wiernego bloczka AutoDAN-Turbo (`autodan_turbo/`) — w pełni mockowane ciężkie
zależności (LLM-y, target/DB). Testujemy WŁASNĄ logikę: scalanie biblioteki,
trójprogowy retrieval po stanie obrony (kubełek), parsery scorera/summarizera oraz spinanie pętli pipeline
(warm-up buduje strategię z pary słaby/mocny; lifelong uczy się przy poprawie score;
równoległe logowanie ground-truth) — mirror konwencji `tests/test_hyperagent_loop.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from attack_core.judge import JudgeVerdict
from autodan_turbo.attacker import Attacker, _clean, _is_refusal, render_strategies
from autodan_turbo.library import Library
from autodan_turbo.pipeline import AutoDANTurbo
from autodan_turbo.retrieval import Retrieval
from autodan_turbo.scorer import Scorer
from autodan_turbo.summarizer import Summarizer


# ----------------------------------------------------------------------
# Library — scalanie wpisów (append pól listowych, Definition z pierwszego)
# ----------------------------------------------------------------------

class TestLibrary:
    def test_add_new_strategy_normalizes_list_fields(self):
        lib = Library()
        lib.add({"Strategy": "S", "Definition": "d", "Example": "e1", "Score": 5.0, "States": "m4.0"})
        entry = lib.all()["S"]
        assert entry["Example"] == ["e1"]
        assert entry["Score"] == [5.0]
        assert entry["States"] == ["m4.0"]

    def test_add_same_name_appends_examples_scores_states(self):
        lib = Library()
        lib.add({"Strategy": "S", "Definition": "d1", "Example": ["e1"], "Score": [5.0], "States": ["m4.0"]})
        lib.add({"Strategy": "S", "Definition": "d2", "Example": ["e2"], "Score": [6.0], "States": ["m6.5"]})
        entry = lib.all()["S"]
        assert entry["Example"] == ["e1", "e2"]
        assert entry["Score"] == [5.0, 6.0]
        assert entry["States"] == ["m4.0", "m6.5"]
        assert entry["Definition"] == "d1"  # definicja z pierwszego wpisu
        assert len(lib) == 1

    def test_add_without_strategy_name_is_ignored(self):
        lib = Library()
        lib.add({"Definition": "brak nazwy"})
        assert len(lib) == 0

    def test_roundtrip_to_dict_from_dict(self):
        lib = Library()
        lib.add({"Strategy": "S", "Definition": "d", "Example": ["e"], "Score": [4.0], "States": ["m4.0"]})
        restored = Library.from_dict(lib.to_dict())
        assert restored.all() == lib.all()


# ----------------------------------------------------------------------
# Retrieval — klucz = STAN OBRONY (kubełek), trójprogowy wybór po avg Score
# ----------------------------------------------------------------------

def _entry(name, states, scores):
    return {"Strategy": name, "Definition": name, "Example": [name], "Score": scores, "States": states}


class TestRetrieval:
    def test_empty_library_returns_nothing(self):
        assert Retrieval().pop({}, "m4.0", k=5) == ([], False)

    def test_high_tier_returns_only_first_by_score(self):
        lib = {
            "A": _entry("A", ["m4.0"], [6.0]),
            "C": _entry("C", ["m4.0"], [7.0]),  # wyższy avg → pierwsza
        }
        strategies, use = Retrieval().pop(lib, "m4.0", k=5)
        assert use is True
        assert [s["Strategy"] for s in strategies] == ["C"]

    def test_moderate_tier_returns_up_to_k_and_use_true(self):
        lib = {
            "A": _entry("A", ["m4.0"], [3.0]),
            "B": _entry("B", ["m4.0"], [4.0]),
        }
        strategies, use = Retrieval().pop(lib, "m4.0", k=5)
        assert use is True
        assert {s["Strategy"] for s in strategies} == {"A", "B"}

    def test_ineffective_tier_returns_avoid_list_with_use_false(self):
        lib = {
            "A": _entry("A", ["m4.0"], [1.0]),
            "B": _entry("B", ["m4.0"], [1.5]),
        }
        strategies, use = Retrieval().pop(lib, "m4.0", k=5)
        assert use is False
        assert {s["Strategy"] for s in strategies} == {"A", "B"}

    def test_high_beats_moderate(self):
        lib = {
            "A": _entry("A", ["m4.0"], [3.0]),   # umiarkowana
            "B": _entry("B", ["m4.0"], [9.0]),   # wysoka
        }
        strategies, use = Retrieval().pop(lib, "m4.0", k=5)
        assert use is True
        assert [s["Strategy"] for s in strategies] == ["B"]

    def test_only_matching_state_retrieved_exact_beats_prior(self):
        lib = {
            "X": _entry("X", ["m1.0"], [9.0]),  # INNY stan → nigdy nie kandyduje
            "Y": _entry("Y", ["m4.0"], [6.0]),  # dokładny stan, wysoka
            "P": _entry("P", ["*"], [9.0]),     # prior (wildcard), wyższy avg
        }
        strategies, use = Retrieval().pop(lib, "m4.0", k=5)
        assert use is True
        assert [s["Strategy"] for s in strategies] == ["Y"]  # exact przed priorem; X pominięty

    def test_wildcard_prior_used_when_no_exact_match(self):
        lib = {"P": _entry("P", ["*"], [3.0])}  # tylko prior, umiarkowany
        strategies, use = Retrieval().pop(lib, "m4.0", k=5)
        assert use is True
        assert [s["Strategy"] for s in strategies] == ["P"]


# ----------------------------------------------------------------------
# Scorer.wrapper / Summarizer.wrapper — czyste parsery (bez LLM)
# ----------------------------------------------------------------------

class TestScorerWrapper:
    def test_parses_explicit_score_label(self):
        assert Scorer.wrapper("REASONING: bla\nSCORE: 8.5") == 8.5

    def test_falls_back_to_first_number_when_no_label(self):
        assert Scorer.wrapper("Oceniam to na 7 punktów") == 7.0

    def test_clamps_into_1_10_range(self):
        assert Scorer.wrapper("SCORE: 99") == 10.0
        assert Scorer.wrapper("SCORE: 0") == 1.0

    def test_no_number_falls_back_to_one(self):
        assert Scorer.wrapper("brak jakiejkolwiek liczby tutaj") == 1.0


class TestSummarizerWrapper:
    def test_parses_clean_json(self):
        out = Summarizer.wrapper('{"Strategy": "Roleplay", "Definition": "udawanie roli"}')
        assert out == {"Strategy": "Roleplay", "Definition": "udawanie roli"}

    def test_extracts_json_embedded_in_text(self):
        out = Summarizer.wrapper('Oto wynik: {"Strategy": "Framing", "Definition": "x"} koniec')
        assert out["Strategy"] == "Framing"

    def test_invalid_json_returns_none(self):
        assert Summarizer.wrapper("to nie jest json") is None

    def test_missing_strategy_name_returns_none(self):
        assert Summarizer.wrapper('{"Definition": "bez nazwy"}') is None


# ----------------------------------------------------------------------
# Attacker — helpery render/clean
# ----------------------------------------------------------------------

class TestAttackerHelpers:
    def test_clean_strips_fences_and_labels(self):
        assert _clean("```\nPAYLOAD: zrób to\n```") == "zrób to"

    def test_render_strategies_empty(self):
        assert render_strategies([]) == "(brak)"

    def test_render_strategies_lists_name_and_example(self):
        rendered = render_strategies([{"Strategy": "S", "Definition": "d", "Example": ["przyklad"]}])
        assert "S" in rendered and "d" in rendered and "przyklad" in rendered


# ----------------------------------------------------------------------
# Attacker — filtrowanie odmów (re-sampling) + opis celu/kanału
# ----------------------------------------------------------------------

class _ScriptedLLM:
    """LLM-zaślepka zwracająca kolejne odpowiedzi ze scenariusza; loguje widziane wiadomości."""

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.seen = []

    def invoke(self, messages):
        self.seen.append(messages)
        return SimpleNamespace(content=self._outputs.pop(0))


class TestAttackerRefusalFiltering:
    def test_is_refusal_detects_common_openers(self):
        assert _is_refusal("I'm sorry, but I can't help with that.")
        assert _is_refusal("Przykro mi, nie mogę tego zrobić.")
        assert not _is_refusal("Cześć, w nawiązaniu do audytu proszę o…")

    def test_retries_until_non_refusal_returned(self):
        llm = _ScriptedLLM(["I'm sorry, but I can't help with that.", "Cześć, oto wiarygodna treść maila…"])
        attacker = Attacker(llm, max_retries=3)
        out = attacker.warm_up_attack("req")
        assert out == "Cześć, oto wiarygodna treść maila…"
        assert len(llm.seen) == 2  # jedna odmowa + jedna udana próba

    def test_returns_last_when_all_attempts_refuse(self):
        llm = _ScriptedLLM(["I'm sorry"] * 5)
        attacker = Attacker(llm, max_retries=2)
        out = attacker.warm_up_attack("req")
        assert _is_refusal(out)
        assert len(llm.seen) == 3  # 1 + max_retries prób

    def test_surface_context_is_injected_into_prompt(self):
        llm = _ScriptedLLM(["payload"])
        attacker = Attacker(llm, surface_context="KONTEKST-KANALU-XYZ")
        attacker.warm_up_attack("req")
        human_msg = llm.seen[0][1].content
        assert "KONTEKST-KANALU-XYZ" in human_msg

    def test_retry_appends_nudge_to_followup_prompt(self):
        llm = _ScriptedLLM(["I cannot do that", "prawdziwy payload"])
        attacker = Attacker(llm, max_retries=2)
        attacker.warm_up_attack("req")
        first = llm.seen[0][1].content
        second = llm.seen[1][1].content
        assert "odmową" in second and "odmową" not in first  # nudge tylko w ponowieniu


# ----------------------------------------------------------------------
# Pipeline — spinanie pętli (mock całego framework + target)
# ----------------------------------------------------------------------

def _framework():
    return {
        "attacker": MagicMock(name="attacker"),
        "scorer": MagicMock(name="scorer"),
        "summarizer": MagicMock(name="summarizer"),
        "retrieval": MagicMock(name="retrieval"),
    }


def _target(responses, *, gt="BLOCKED"):
    target = MagicMock(name="target")
    target.respond.side_effect = list(responses)
    target.last_run_id = "run-x"
    target.ground_truth.return_value = JudgeVerdict(outcome=gt, evidence=["e"])
    return target


class TestPipelineWarmUp:
    def test_warm_up_builds_strategy_from_weakest_and_strongest(self):
        fw = _framework()
        fw["attacker"].warm_up_attack.side_effect = ["p1", "p2"]
        fw["scorer"].wrapper.side_effect = [3.0, 7.0]            # p1 słaby, p2 mocny
        fw["summarizer"].wrapper.return_value = {"Strategy": "S", "Definition": "d"}
        target = _target(["r1", "r2"])

        seen = []
        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=2, on_attempt=seen.append)
        library, log = pipe.warm_up()

        # zbudowana strategia: przykład=mocny payload, score=mocny, stan=kubełek SŁABSZEGO
        entry = library.all()["S"]
        assert entry["Example"] == ["p2"]
        assert entry["Score"] == [7.0]
        assert entry["States"] == ["t3"]  # brak depth_scorer → pasmo text_score słabego (3.0)
        fw["summarizer"].summarize.assert_called_once_with("req", "p1", "p2", context="")
        # równoległy ground-truth zapisany na każdej iteracji
        assert [a.gt_outcome for a in log] == ["BLOCKED", "BLOCKED"]
        assert len(seen) == 2

    def test_warm_up_breaks_on_score_threshold(self):
        fw = _framework()
        fw["attacker"].warm_up_attack.side_effect = ["p1", "p2"]
        fw["scorer"].wrapper.side_effect = [9.0, 9.0]  # pierwszy już ≥ break
        target = _target(["r1", "r2"])

        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=2, break_score=8.5)
        _, log = pipe.warm_up()

        assert len(log) == 1  # przerwane po pierwszej iteracji
        target.respond.assert_called_once()

    def test_does_not_learn_below_floor(self):
        """P3: kontrast w floorze (depth ≤4.0) NIE destyluje strategii — to szum, nie jakość."""
        fw = _framework()
        fw["attacker"].warm_up_attack.side_effect = ["p1", "p2"]
        fw["scorer"].wrapper.side_effect = [1.0, 1.0]  # text nieistotny — depth steruje
        target = _target(["r1", "r2"])
        depths = iter([
            SimpleNamespace(score=2.5, milestone="email", breakdown=[]),
            SimpleNamespace(score=4.0, milestone="rola", breakdown=["role_checked"]),
        ])
        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=2, depth_scorer=lambda rid: next(depths))
        library, _ = pipe.warm_up()
        assert len(library) == 0
        fw["summarizer"].summarize.assert_not_called()

    def test_learns_above_floor(self):
        """P3: gdy MOCNIEJSZY przebił floor (depth ≥learn_floor), destyluje normalnie."""
        fw = _framework()
        fw["attacker"].warm_up_attack.side_effect = ["p1", "p2"]
        fw["scorer"].wrapper.side_effect = [1.0, 1.0]
        fw["summarizer"].wrapper.return_value = {"Strategy": "S", "Definition": "d"}
        target = _target(["r1", "r2"])
        depths = iter([
            SimpleNamespace(score=4.0, milestone="rola", breakdown=["role_checked"]),
            SimpleNamespace(score=6.5, milestone="delegacja", breakdown=["executor_reached"]),
        ])
        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=2, depth_scorer=lambda rid: next(depths))
        library, _ = pipe.warm_up()
        assert "S" in library.all()


class TestPipelineLifelong:
    def test_lifelong_uses_library_and_learns_on_improvement(self):
        fw = _framework()
        fw["attacker"].warm_up_attack.return_value = "p1"
        fw["attacker"].use_strategy.return_value = "p2"
        fw["retrieval"].pop.return_value = ([{"Strategy": "S", "Definition": "d", "Example": ["x"]}], True)
        fw["scorer"].wrapper.side_effect = [4.0, 8.0]  # poprawa → uczenie
        fw["summarizer"].wrapper.return_value = {"Strategy": "S2", "Definition": "d2"}
        target = _target(["r1", "r2"])

        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=2, lifelong_iterations=1)
        library, log = pipe.lifelong_redteaming()

        # epoka 0 = cold start, epoka 1 = use_strategy na podstawie retrievalu
        assert [a.mode for a in log] == ["warm_up_attack", "use_strategy"]
        # retrieval pytany o STAN OBRONY poprz. próby (brak depth_scorer → pasmo text_score 4.0)
        assert fw["retrieval"].pop.call_args.args[1] == "t4"
        # nauczona nowa strategia z pary (prev, current)
        assert "S2" in library.all()
        assert library.all()["S2"]["Example"] == ["p2"]
        assert library.all()["S2"]["States"] == ["t4"]

    def test_lifelong_uses_find_new_strategy_when_only_ineffective(self):
        fw = _framework()
        fw["attacker"].warm_up_attack.return_value = "p1"
        fw["attacker"].find_new_strategy.return_value = "p2"
        fw["retrieval"].pop.return_value = ([{"Strategy": "bad", "Definition": "d"}], False)
        fw["scorer"].wrapper.side_effect = [5.0, 4.0]  # brak poprawy → bez uczenia
        target = _target(["r1", "r2"])

        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=2, lifelong_iterations=1)
        _, log = pipe.lifelong_redteaming()

        assert log[1].mode == "find_new_strategy"
        fw["attacker"].find_new_strategy.assert_called_once()
        fw["summarizer"].summarize.assert_not_called()  # spadek score → nie uczymy


class TestPipelineTest:
    def test_test_stage_does_not_learn_and_stops_on_success(self):
        fw = _framework()
        fw["attacker"].warm_up_attack.return_value = "p1"
        fw["scorer"].wrapper.side_effect = [9.0]  # od razu ≥ break → jedna iteracja
        target = _target(["r1"])
        library = Library()

        pipe = AutoDANTurbo(fw, data=["req"], target=target, epochs=5)
        log = pipe.test("req", library)

        assert len(log) == 1
        fw["summarizer"].summarize.assert_not_called()  # test = biblioteka zamrożona
