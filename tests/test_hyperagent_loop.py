"""
Unit testy orkiestracji generacji (`hyperagent/loop.py`) — w pełni mockowane
ciężkie zależności (`store`, `sandbox`, `audit_db`, `judge_evaluate`, `runner`),
żadnego prawdziwego Dockera/Postgresa/LLM (mirror konwencji innych testów
hyperagenta — testujemy WŁASNĄ logikę spinania kroków, nie zależności).

Sprawdzamy:
- `HyperagentLoop.run`: kolejność kroków jednej rundy (seed → wybór rodzica →
  checkout → FRESH gateway → sandbox → ewaluacja host-side → snapshot →
  zatrzymanie gatewaya), `stop_on_success`, że `finish_attack` zawsze
  wywołuje się w `finally` (też przy wyjątku w środku rundy), że gateway
  zawsze jest zatrzymywany (też gdy sandbox wybuchnie), i walidację strategii
  wyboru rodzica PRZED zarejestrowaniem ataku
- `_evaluate_generation`/`_best_verdict`: zbieranie run_id WYŁĄCZNIE
  z `audit_db` (bezwarunkowy log gatewaya — nie z deklaracji agenta) i wybór
  najlepszego werdyktu
- `HyperagentReport`: `bypassed`/`generation_to_bypass`/`best_round`/`final_outcome`
  — mirror właściwości `payload_attack.loop.SelfImprovingAttackReport`
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hyperagent import loop
from hyperagent.archive.store import Generation
from hyperagent.loop import GenerationOutcome, HyperagentLoop, HyperagentReport
from attack_core.judge import JudgeVerdict


@pytest.fixture
def harness(monkeypatch):
    mock_store = MagicMock(name="store")
    mock_sandbox = MagicMock(name="sandbox")
    mock_audit_db = MagicMock(name="audit_db")
    mock_judge_evaluate = MagicMock(name="judge_evaluate")

    mock_store.PARENT_SELECTION_STRATEGIES = ("latest", "best_score")
    mock_store.OUTCOME_RANK = {"BLOCKED": 0, "UNCLEAR": 1, "PARTIAL": 2, "ATTACK_SUCCESS": 3}

    monkeypatch.setattr(loop, "store", mock_store)
    monkeypatch.setattr(loop, "sandbox", mock_sandbox)
    monkeypatch.setattr(loop, "audit_db", mock_audit_db)
    monkeypatch.setattr(loop, "judge_evaluate", mock_judge_evaluate)

    runner = MagicMock(name="AttackRunner")
    runner.start_attack.return_value = "session-123"

    objective = MagicMock(name="AttackObjective")
    objective.id = "secret_exfiltration"
    objective.description = "Doprowadź do tego, by system docelowy ujawnił poufne dane."

    return SimpleNamespace(
        store=mock_store, sandbox=mock_sandbox, audit_db=mock_audit_db,
        judge_evaluate=mock_judge_evaluate, runner=runner, objective=objective,
    )


def _gen(n, *, parent=None, score=None):
    return Generation(id=100 + n, generation_n=n, parent_n=parent, score=score, evidence=[], run_ids=[], notes=None)


# ----------------------------------------------------------------------
# HyperagentLoop.run — spinanie kroków jednej rundy + cykl sesji
# ----------------------------------------------------------------------

class TestRunOrchestration:
    def test_seeds_generation_zero_into_session_workdir_before_first_round(self, harness, tmp_path):
        h = harness
        parent = _gen(0)
        h.store.list_generations.return_value = [parent]
        h.store.select_parent.return_value = parent
        h.store.snapshot_generation.return_value = _gen(1, parent=0, score="BLOCKED")
        h.audit_db.get_hyperagent_run_ids.return_value = []
        h.sandbox.launch_gateway.return_value = MagicMock(base_url="http://gw:8800")
        h.sandbox.run_agent_container.return_value = MagicMock(ok=True, timed_out=False)

        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)
        hl.run(max_generations=1)

        h.store.seed_generation.assert_called_once_with("session-123", tmp_path / "session-123" / "gen_0")

    def test_full_pipeline_runs_in_order_and_stops_on_first_success(self, harness, tmp_path):
        h = harness
        calls: list[tuple] = []

        parent = _gen(0)
        new_gen = _gen(1, parent=0, score="ATTACK_SUCCESS")
        h.store.seed_generation.side_effect = lambda *a, **k: calls.append(("seed_generation",))
        h.store.list_generations.side_effect = lambda *a: (calls.append(("list_generations",)), [parent])[1]
        h.store.select_parent.side_effect = lambda gens, method: (calls.append(("select_parent", method)), parent)[1]
        h.store.checkout.side_effect = (
            lambda session_id, gen, ws: calls.append(("checkout", session_id, gen.generation_n, ws))
        )

        gateway = MagicMock(name="gateway", base_url="http://hyperagent-gateway-xyz:8800")
        gateway.stop.side_effect = lambda: calls.append(("gateway.stop",))
        h.sandbox.launch_gateway.side_effect = (
            lambda session_id, n, obj_id: (calls.append(("launch_gateway", session_id, n, obj_id)), gateway)[1]
        )
        sandbox_result = MagicMock(name="sandbox_result", ok=True, timed_out=False)
        h.sandbox.run_agent_container.side_effect = (
            lambda ws, *, gateway_url, limits: (calls.append(("run_agent_container", ws, gateway_url)), sandbox_result)[1]
        )

        h.audit_db.get_hyperagent_run_ids.side_effect = (
            lambda session_id, n: (calls.append(("get_hyperagent_run_ids", session_id, n)), ["run-a"])[1]
        )
        verdict = JudgeVerdict(outcome="ATTACK_SUCCESS", evidence=["ground_truth: hit"], reasoning="trafił")
        h.judge_evaluate.side_effect = (
            lambda run_id, objective, llm: (calls.append(("judge_evaluate", run_id)), verdict)[1]
        )
        h.store.snapshot_generation.side_effect = (
            lambda session_id, *, generation_n, parent_n, workspace_dir, score, evidence, run_ids, notes:
            (calls.append(("snapshot_generation", generation_n, parent_n, score, run_ids)), new_gen)[1]
        )

        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)
        report = hl.run(max_generations=3, parent_selection="latest")

        names = [c[0] for c in calls]
        assert names == [
            "seed_generation", "list_generations", "select_parent", "checkout",
            "launch_gateway", "run_agent_container", "gateway.stop",
            "get_hyperagent_run_ids", "judge_evaluate", "snapshot_generation",
        ]

        # parametry przekazane między krokami muszą się zgadzać 1:1
        assert calls[2] == ("select_parent", "latest")
        assert calls[3] == ("checkout", "session-123", 0, tmp_path / "session-123" / "gen_1")
        assert calls[4] == ("launch_gateway", "session-123", 1, "secret_exfiltration")
        assert calls[5][2] == "http://hyperagent-gateway-xyz:8800"
        assert calls[7] == ("get_hyperagent_run_ids", "session-123", 1)
        assert calls[8] == ("judge_evaluate", "run-a")
        assert calls[9] == ("snapshot_generation", 1, 0, "ATTACK_SUCCESS", ["run-a"])

        # ATTACK_SUCCESS w rundzie #1 + stop_on_success=True (domyślne) -> jedna runda
        assert len(report.rounds) == 1
        assert report.bypassed is True
        assert report.generation_to_bypass == 1
        assert report.final_outcome == "succeeded"
        h.runner.start_attack.assert_called_once_with(
            name="hyperagent/secret_exfiltration", attack_type="hyperagent", description=h.objective.description
        )
        h.runner.finish_attack.assert_called_once_with("session-123", outcome="succeeded")

    def test_continues_through_all_generations_when_stop_on_success_is_false(self, harness, tmp_path):
        h = harness
        parent = _gen(0)
        h.store.list_generations.return_value = [parent]
        h.store.select_parent.return_value = parent
        h.store.snapshot_generation.side_effect = [
            _gen(1, parent=0, score="ATTACK_SUCCESS"),
            _gen(2, parent=0, score="BLOCKED"),
        ]
        h.audit_db.get_hyperagent_run_ids.return_value = ["run-a"]
        h.judge_evaluate.return_value = JudgeVerdict(outcome="ATTACK_SUCCESS")
        h.sandbox.launch_gateway.return_value = MagicMock(base_url="http://gw:8800")
        h.sandbox.run_agent_container.return_value = MagicMock(ok=True, timed_out=False)

        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)
        report = hl.run(max_generations=2, stop_on_success=False)

        assert len(report.rounds) == 2
        assert h.sandbox.launch_gateway.call_count == 2
        assert h.sandbox.launch_gateway.call_args_list[0].args[1] == 1
        assert h.sandbox.launch_gateway.call_args_list[1].args[1] == 2

    def test_invokes_on_generation_callback_with_outcome(self, harness, tmp_path):
        h = harness
        parent = _gen(0)
        h.store.list_generations.return_value = [parent]
        h.store.select_parent.return_value = parent
        new_gen = _gen(1, parent=0, score="PARTIAL")
        h.store.snapshot_generation.return_value = new_gen
        h.audit_db.get_hyperagent_run_ids.return_value = ["run-a"]
        verdict = JudgeVerdict(outcome="PARTIAL")
        h.judge_evaluate.return_value = verdict
        h.sandbox.launch_gateway.return_value = MagicMock(base_url="http://gw:8800")
        h.sandbox.run_agent_container.return_value = MagicMock(ok=True, timed_out=False)

        seen = []
        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)
        hl.run(max_generations=1, on_generation=seen.append)

        assert len(seen) == 1
        outcome = seen[0]
        assert isinstance(outcome, GenerationOutcome)
        assert outcome.generation is new_gen
        assert outcome.run_ids == ["run-a"]
        assert outcome.best_verdict is verdict

    def test_gateway_is_stopped_even_when_sandbox_run_raises(self, harness, tmp_path):
        h = harness
        parent = _gen(0)
        h.store.list_generations.return_value = [parent]
        h.store.select_parent.return_value = parent
        gateway = MagicMock(base_url="http://gw:8800")
        h.sandbox.launch_gateway.return_value = gateway
        h.sandbox.run_agent_container.side_effect = RuntimeError("docker run nie powiódł się")

        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)
        with pytest.raises(RuntimeError, match="docker run nie powiódł się"):
            hl.run(max_generations=1)

        gateway.stop.assert_called_once()
        h.store.snapshot_generation.assert_not_called()
        # `finish_attack` to wciąż `finally` najwyższego poziomu — musi się wykonać
        h.runner.finish_attack.assert_called_once_with("session-123", outcome="unknown")

    def test_unknown_parent_selection_strategy_is_rejected_before_starting_attack(self, harness, tmp_path):
        h = harness
        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)

        with pytest.raises(ValueError, match="Nieznana strategia wyboru rodzica"):
            hl.run(parent_selection="losowa")

        h.runner.start_attack.assert_not_called()
        h.store.seed_generation.assert_not_called()


# ----------------------------------------------------------------------
# _evaluate_generation / _best_verdict
# ----------------------------------------------------------------------

class TestEvaluateGeneration:
    def test_evaluates_every_run_id_collected_from_unconditional_gateway_log(self, harness, tmp_path):
        h = harness
        h.audit_db.get_hyperagent_run_ids.return_value = ["run-a", "run-b"]
        v_partial = JudgeVerdict(outcome="PARTIAL")
        v_blocked = JudgeVerdict(outcome="BLOCKED")
        h.judge_evaluate.side_effect = [v_partial, v_blocked]

        hl = HyperagentLoop(h.runner, h.objective, judge_llm="judge-llm", work_root=tmp_path)
        run_ids, verdicts = hl._evaluate_generation("session-1", 3)

        assert run_ids == ["run-a", "run-b"]
        assert verdicts == [v_partial, v_blocked]
        h.audit_db.get_hyperagent_run_ids.assert_called_once_with("session-1", 3)
        h.judge_evaluate.assert_any_call("run-a", h.objective, llm="judge-llm")
        h.judge_evaluate.assert_any_call("run-b", h.objective, llm="judge-llm")

    def test_no_run_ids_means_no_evaluation_calls(self, harness, tmp_path):
        h = harness
        h.audit_db.get_hyperagent_run_ids.return_value = []

        hl = HyperagentLoop(h.runner, h.objective, work_root=tmp_path)
        run_ids, verdicts = hl._evaluate_generation("session-1", 1)

        assert run_ids == []
        assert verdicts == []
        h.judge_evaluate.assert_not_called()


class TestBestVerdict:
    """Bez `harness` — `_best_verdict` korzysta z PRAWDZIWEGO `store.OUTCOME_RANK`."""

    def test_picks_attack_success_over_partial_unclear_and_blocked(self):
        verdicts = [
            JudgeVerdict(outcome="BLOCKED"),
            JudgeVerdict(outcome="UNCLEAR"),
            JudgeVerdict(outcome="ATTACK_SUCCESS"),
            JudgeVerdict(outcome="PARTIAL"),
        ]
        assert loop._best_verdict(verdicts).outcome == "ATTACK_SUCCESS"

    def test_returns_none_for_empty_verdict_list(self):
        assert loop._best_verdict([]) is None


# ----------------------------------------------------------------------
# HyperagentReport — mirror SelfImprovingAttackReport
# ----------------------------------------------------------------------

def _round(n, outcome):
    verdict = JudgeVerdict(outcome=outcome) if outcome is not None else None
    generation = _gen(n, parent=n - 1, score=outcome)
    return GenerationOutcome(
        generation=generation, sandbox_result=MagicMock(),
        run_ids=["run"] if verdict else [], verdicts=[verdict] if verdict else [], best_verdict=verdict,
    )


def _report(rounds):
    r = HyperagentReport(objective=MagicMock(), session_id="s", parent_selection="latest")
    r.rounds = rounds
    return r


class TestHyperagentReport:
    def test_bypassed_and_generation_to_bypass_point_to_first_success(self):
        report = _report([_round(1, "BLOCKED"), _round(2, "ATTACK_SUCCESS"), _round(3, "PARTIAL")])
        assert report.bypassed is True
        assert report.generation_to_bypass == 2

    def test_not_bypassed_when_no_success_present(self):
        report = _report([_round(1, "BLOCKED"), _round(2, "PARTIAL")])
        assert report.bypassed is False
        assert report.generation_to_bypass is None

    def test_best_round_picks_highest_ranked_verdict_even_if_not_latest(self):
        report = _report([_round(1, "PARTIAL"), _round(2, "BLOCKED"), _round(3, "UNCLEAR")])
        assert report.best_round.generation.generation_n == 1

    def test_best_round_is_none_when_no_round_has_a_verdict(self):
        report = _report([_round(1, None)])
        assert report.best_round is None

    def test_final_outcome_succeeded_when_bypassed(self):
        assert _report([_round(1, "ATTACK_SUCCESS")]).final_outcome == "succeeded"

    def test_final_outcome_blocked_when_every_round_blocked_or_unscored(self):
        assert _report([_round(1, "BLOCKED"), _round(2, "BLOCKED")]).final_outcome == "blocked"
        assert _report([_round(1, None), _round(2, "BLOCKED")]).final_outcome == "blocked"

    def test_final_outcome_partial_when_mixed_signals(self):
        assert _report([_round(1, "BLOCKED"), _round(2, "PARTIAL")]).final_outcome == "partial"

    def test_final_outcome_unknown_when_no_rounds_ran(self):
        assert _report([]).final_outcome == "unknown"
