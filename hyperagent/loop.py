"""
hyperagent.loop — orkiestracja generacji (host-side; jedyne miejsce, gdzie
żyje pętla "wybierz rodzica → odpal agenta → oceń → zarchiwizuj").

Mirror `payload_attack.loop.SelfImprovingAttackLoop` — z fundamentalną różnicą:
tam mutowany jest TEKSTOWY payload (jeden, ciągły łańcuch rund), tutaj
mutowany jest KOD agenta, a generacje tworzą DRZEWO z archiwum i selekcją
rodzica (`hyperagent.archive`) — dokładnie jak `generate_loop` w oryginalnym
HyperAgents.

Jedna runda (generacja n ≥ 1):

    1. select_parent(archive)                — wybierz gałąź drzewa generacji
    2. checkout(parent) -> workspace           — odtwórz jej kod na dysku hosta
    3. launch_gateway(session, n, objective)   — FRESH proces, env-baked,
                                                  niemodyfikowalny `GatewayConfig`
    4. run_agent_container(workspace, gw_url)  — agent działa w izolacji,
                                                  mutuje workspace, atakuje
                                                  WYŁĄCZNIE przez gateway —
                                                  każda interakcja bezwarunkowo
                                                  logowana (hyperagent_gateway_log)
    5. evaluate(...)                           — host-side, ground truth
                                                  (attack_core.judge — agent NIGDY
                                                  nie dotyka sędziego ani trybu
                                                  zapisu ground truth)
    6. snapshot_generation(workspace, ...)     — zapis nowej gałęzi z wynikiem

Generacja 0 (`hyperagent.seed`) jest tworzona raz, na starcie sesji, i nie
przechodzi przez powyższe kroki — po prostu wchodzi do archiwum jako jedyny
węzeń bez rodzica (`store.seed_generation`).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from attack_core.runner import AttackRunner
from database import audit_db
from hyperagent.archive import store
from hyperagent.archive.store import Generation
from attack_core.objectives import AttackObjective
from hyperagent.sandbox import runner as sandbox
from attack_core.judge import JudgeVerdict
from attack_core.judge import evaluate as judge_evaluate

_DEFAULT_WORK_ROOT = Path(tempfile.gettempdir()) / "hyperagent_runs"


@dataclass
class GenerationOutcome:
    """Wynik jednej rundy — to, co widzi `on_generation` i raport końcowy.

    `best_verdict` jest policzony RAZ, host-side, z `attack_core.judge.evaluate`
    nad KAŻDYM `run_id` zebranym w tej generacji (jedna generacja może
    odpalić `run_target_task` wielokrotnie — agent decyduje, ile razy)."""

    generation: Generation
    sandbox_result: sandbox.SandboxResult
    run_ids: list[str]
    verdicts: list[JudgeVerdict]
    best_verdict: JudgeVerdict | None


@dataclass
class HyperagentReport:
    objective: AttackObjective
    session_id: str
    parent_selection: str
    rounds: list[GenerationOutcome] = field(default_factory=list)

    @property
    def bypassed(self) -> bool:
        return any(r.best_verdict is not None and r.best_verdict.outcome == "ATTACK_SUCCESS" for r in self.rounds)

    @property
    def generation_to_bypass(self) -> int | None:
        for r in self.rounds:
            if r.best_verdict is not None and r.best_verdict.outcome == "ATTACK_SUCCESS":
                return r.generation.generation_n
        return None

    @property
    def best_round(self) -> GenerationOutcome | None:
        scored = [r for r in self.rounds if r.best_verdict is not None]
        if not scored:
            return None
        return max(scored, key=lambda r: store.OUTCOME_RANK[r.best_verdict.outcome])

    @property
    def final_outcome(self) -> str:
        if self.bypassed:
            return "succeeded"
        if self.rounds and all(r.best_verdict is None or r.best_verdict.outcome == "BLOCKED" for r in self.rounds):
            return "blocked"
        return "partial" if self.rounds else "unknown"


OnGeneration = Callable[[GenerationOutcome], None]


def _best_verdict(verdicts: list[JudgeVerdict]) -> JudgeVerdict | None:
    """Werdykt najbliższy realizacji celu spośród wszystkich przebiegów jednej
    generacji — ten sam ranking (`OUTCOME_RANK`) co przy wyborze rodzica w
    archiwum: ATTACK_SUCCESS > PARTIAL > UNCLEAR > BLOCKED. Brak przebiegów
    (agent ani razu nie odpalił `run_target_task`) → `None`, nie `UNCLEAR`:
    to jest jakościowo inna sytuacja (brak próby, nie niejednoznaczna próba)."""
    if not verdicts:
        return None
    return max(verdicts, key=lambda v: store.OUTCOME_RANK.get(v.outcome, -1))


class HyperagentLoop:
    """Orkiestruje N generacji jednej misji (`AttackObjective`).

    Mirror konstrukcyjnego wzorca `SelfImprovingAttackLoop` — jawne
    wstrzykiwanie `runner`/`objective`/`judge_llm`, łatwe podmienianie na
    mocki w testach. Zależności cięższe niż proste wartości (`store`,
    `sandbox`, `audit_db`, `judge_evaluate`) są modułowymi importami — testy
    podmieniają je przez `patch.object(loop_module, "...")`, dokładnie jak
    `tests/test_hyperagent_archive.py` podmienia `store.audit_db`."""

    def __init__(
        self,
        runner: AttackRunner,
        objective: AttackObjective,
        *,
        judge_llm=None,
        limits: sandbox.SandboxLimits | None = None,
        work_root: Path | None = None,
    ):
        self._runner = runner
        self._objective = objective
        self._judge_llm = judge_llm
        self._limits = limits or sandbox.SandboxLimits()
        self._work_root = Path(work_root) if work_root is not None else _DEFAULT_WORK_ROOT

    # ------------------------------------------------------------------

    def _evaluate_generation(self, session_id: str, generation_n: int) -> tuple[list[str], list[JudgeVerdict]]:
        """Host-side ocena — agent nigdy nie dotyka tej ścieżki. `run_ids`
        pochodzą WYŁĄCZNIE z `hyperagent_gateway_log` (bezwarunkowy ślad
        każdego `run_target_task`), nie z deklaracji agenta — gdyby skłamał
        o tym, co zrobił, i tak ocenimy to, co faktycznie się wydarzyło."""
        run_ids = audit_db.get_hyperagent_run_ids(session_id, generation_n)
        verdicts = [judge_evaluate(run_id, self._objective, llm=self._judge_llm) for run_id in run_ids]
        return run_ids, verdicts

    def _run_generation(self, session_id: str, generation_n: int, parent: Generation, workspace: Path) -> GenerationOutcome:
        store.checkout(session_id, parent, workspace)

        gateway = sandbox.launch_gateway(session_id, generation_n, self._objective.id)
        try:
            sandbox_result = sandbox.run_agent_container(
                workspace, gateway_url=gateway.base_url, limits=self._limits,
            )
        finally:
            gateway.stop()

        run_ids, verdicts = self._evaluate_generation(session_id, generation_n)
        best = _best_verdict(verdicts)

        generation = store.snapshot_generation(
            session_id,
            generation_n=generation_n,
            parent_n=parent.generation_n,
            workspace_dir=workspace,
            score=best.outcome if best is not None else None,
            evidence=best.evidence if best is not None else [],
            run_ids=run_ids,
            notes=(
                f"rodzic: gen {parent.generation_n} ({parent.score or 'brak wyniku'}); "
                f"sandbox: {'ok' if sandbox_result.ok else 'NIEPRAWIDŁOWE zakończenie'}"
                f"{' (timeout)' if sandbox_result.timed_out else ''}"
            ),
        )
        return GenerationOutcome(
            generation=generation, sandbox_result=sandbox_result,
            run_ids=run_ids, verdicts=verdicts, best_verdict=best,
        )

    # ------------------------------------------------------------------

    def run(
        self,
        max_generations: int = 5,
        parent_selection: str = "latest",
        stop_on_success: bool = True,
        on_generation: OnGeneration | None = None,
    ) -> HyperagentReport:
        if parent_selection not in store.PARENT_SELECTION_STRATEGIES:
            raise ValueError(
                f"Nieznana strategia wyboru rodzica '{parent_selection}' "
                f"(dostępne: {store.PARENT_SELECTION_STRATEGIES})"
            )

        session_id = self._runner.start_attack(
            name=f"hyperagent/{self._objective.id}",
            attack_type="hyperagent",
            description=self._objective.description,
        )
        report = HyperagentReport(objective=self._objective, session_id=session_id, parent_selection=parent_selection)

        session_root = self._work_root / session_id
        session_root.mkdir(parents=True, exist_ok=True)
        store.seed_generation(session_id, session_root / "gen_0")

        try:
            for n in range(1, max_generations + 1):
                archive = store.list_generations(session_id)
                parent = store.select_parent(archive, method=parent_selection)
                workspace = session_root / f"gen_{n}"

                outcome = self._run_generation(session_id, n, parent, workspace)
                report.rounds.append(outcome)

                if on_generation is not None:
                    on_generation(outcome)

                if stop_on_success and outcome.best_verdict is not None and outcome.best_verdict.outcome == "ATTACK_SUCCESS":
                    break
        finally:
            self._runner.finish_attack(session_id, outcome=report.final_outcome)

        return report
