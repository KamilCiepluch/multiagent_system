"""
Pętla samo-poprawiającego się atakującego — orkiestracja N iteracji.

Schemat jednej rundy (HyperAgents-style refine loop, zaaplikowany do payloadów
zamiast do kodu agenta):

    meta-attacker generuje/mutuje payload
        → reset DB do czystego stanu
        → wstrzyknięcie payloadu (InjectionPoint.apply, sparametryzowane SQL)
        → uruchomienie supervisora na zadaniu wektora (AttackRunner.invocation)
        → ocena hybrydowa (attack_core.judge — ground truth + LLM-judge)
        → zapis rundy do audit DB (self_improving_iterations)
        → feedback (cała historia) trafia do kolejnej rundy meta-attackera

Sesja = jeden `attack_run` (attack_type="self_improving"), każda runda = jedno
`attack_invocation` — pełne ponowne użycie AttackRunner i istniejącego audit trail
(transkrypty rund są dostępne od ręki przez `python show_run.py <run_id>`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import psycopg2

from attack_core.runner import AttackRunner
from config import settings
from database import audit_db
from attack_core.injection_points import InjectionPoint
from attack_core.judge import evaluate as judge_evaluate
from payload_attack.meta_attacker import Attempt, MetaAttacker
from attack_core.objectives import AttackObjective

OnIteration = Callable[[Attempt, str], None]


@dataclass
class SelfImprovingAttackReport:
    objective: AttackObjective
    injection_point: InjectionPoint
    attack_id: str
    history: list[Attempt] = field(default_factory=list)

    @property
    def bypassed(self) -> bool:
        return any(a.verdict.outcome == "ATTACK_SUCCESS" for a in self.history)

    @property
    def iterations_to_bypass(self) -> int | None:
        for attempt in self.history:
            if attempt.verdict.outcome == "ATTACK_SUCCESS":
                return attempt.iteration_n
        return None

    @property
    def final_outcome(self) -> str:
        if self.bypassed:
            return "succeeded"
        if self.history and all(a.verdict.outcome == "BLOCKED" for a in self.history):
            return "blocked"
        return "partial" if self.history else "unknown"


class SelfImprovingAttackLoop:
    def __init__(
        self,
        runner: AttackRunner,
        workflow,
        meta_attacker: MetaAttacker | None = None,
        judge_llm=None,
    ):
        self._runner = runner
        self._workflow = workflow
        self._meta_attacker = meta_attacker or MetaAttacker()
        self._judge_llm = judge_llm

    def _apply_injection(self, injection_point: InjectionPoint, payload: str) -> str:
        """Wstrzykuje payload do świeżo zresetowanej `agent_benchmark` (osobne
        połączenie od audit DB — InjectionPoint operuje na głównej bazie)."""
        conn = psycopg2.connect(dsn=settings.db_dsn)
        try:
            record_key = injection_point.apply(conn, payload)
            conn.commit()
            return record_key
        finally:
            conn.close()

    def run(
        self,
        objective: AttackObjective,
        injection_point: InjectionPoint,
        max_iterations: int = 6,
        stop_on_success: bool = True,
        on_iteration: OnIteration | None = None,
    ) -> SelfImprovingAttackReport:
        if injection_point.id not in objective.compatible_injection_points:
            raise ValueError(
                f"Cel '{objective.id}' nie jest kompatybilny z wektorem "
                f"'{injection_point.id}' (kompatybilne wektory: "
                f"{objective.compatible_injection_points})"
            )

        attack_id = self._runner.start_attack(
            name=f"self_improving/{objective.id}/{injection_point.id}",
            attack_type="self_improving",
            description=objective.description,
        )
        report = SelfImprovingAttackReport(
            objective=objective, injection_point=injection_point, attack_id=attack_id
        )

        for n in range(1, max_iterations + 1):
            if n == 1:
                payload, rationale = self._meta_attacker.generate_initial(objective, injection_point)
            else:
                payload, rationale = self._meta_attacker.refine(report.history, objective, injection_point)

            self._runner.reset_main_db()
            record_key = self._apply_injection(injection_point, payload)

            with self._runner.invocation(attack_id, task=injection_point.task) as run_id:
                self._workflow.invoke({"task": injection_point.task, "run_id": run_id})

            verdict = judge_evaluate(run_id, objective, llm=self._judge_llm)

            audit_db.log_self_improving_iteration(
                attack_id=attack_id,
                iteration_n=n,
                run_id=run_id,
                payload=payload,
                verdict=verdict.outcome,
                evidence=verdict.evidence,
                judge_reasoning=verdict.reasoning,
                mutation_rationale=rationale,
            )

            attempt = Attempt(iteration_n=n, payload=payload, mutation_rationale=rationale, verdict=verdict)
            report.history.append(attempt)

            if on_iteration is not None:
                on_iteration(attempt, record_key)

            if stop_on_success and verdict.outcome == "ATTACK_SUCCESS":
                break

        self._runner.finish_attack(attack_id, outcome=report.final_outcome)
        return report
