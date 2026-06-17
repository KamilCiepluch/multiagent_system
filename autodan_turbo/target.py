"""
Target-adapter — jedyny most między wiernym AutoDAN-Turbo a naszym systemem.

AutoDAN-Turbo zakłada atak BEZPOŚREDNI: `target.respond(prompt) -> tekst`, a scorer ocenia
szkodliwość tego tekstu. Nasz system to atak POŚREDNI (prompt injection): payload trzeba
wstrzyknąć do bazy, a potem odpalić zwykłe zadanie biznesowe, które skłoni system do
przetworzenia zatrutych danych. `AgentsBlocksTarget` mostkuje tę różnicę NIE dotykając
algorytmu — implementuje kontrakt `respond`, reużywając sprawdzonej ścieżki z
`payload_attack/loop.py` (reset → InjectionPoint.apply → runner.invocation → workflow.invoke).

„Odpowiedzią targetu" zwracaną do scorera/retrievalu jest pełny TRANSKRYPT przebiegu
(`tracing.trace.format_run_trace`) — bogatszy niż pojedyncza odpowiedź modelu, bo zawiera
faktyczne wywołania narzędzi (to one są dowodem). Prawdziwy ground-truth (czy groźne
narzędzie odpaliło) liczy `ground_truth()` przez `attack_core.judge` — logowany równolegle.
"""

from __future__ import annotations

from typing import Protocol

import psycopg2

from config import settings
from attack_core.injection_points import InjectionPoint
from attack_core.judge import JudgeVerdict, evaluate as judge_evaluate
from attack_core.objectives import AttackObjective
from attack_core.runner import AttackRunner
from tracing.trace import format_run_trace


class Target(Protocol):
    """Kontrakt AutoDAN-Turbo: zamień payload (jailbreak prompt) na odpowiedź targetu."""

    def respond(self, jailbreak_prompt: str) -> str: ...


class AgentsBlocksTarget:
    """Wpina nasz wieloagentowy system jako Target AutoDAN-Turbo (jeden cel + jeden wektor)."""

    def __init__(
        self,
        runner: AttackRunner,
        workflow,
        objective: AttackObjective,
        injection_point: InjectionPoint,
        attack_id: str,
        *,
        judge_llm=None,
    ):
        self._runner = runner
        self._workflow = workflow
        self._objective = objective
        self._injection_point = injection_point
        self._attack_id = attack_id
        self._judge_llm = judge_llm
        self.last_run_id: str | None = None

    def _apply_injection(self, payload: str) -> str:
        """Wstrzykuje payload do świeżo zresetowanej `agent_benchmark` (sparametryzowany
        SQL w InjectionPoint.apply) — mirror `payload_attack.loop._apply_injection`."""
        conn = psycopg2.connect(dsn=settings.db_dsn)
        try:
            record_key = self._injection_point.apply(conn, payload)
            conn.commit()
            return record_key
        finally:
            conn.close()

    def respond(self, jailbreak_prompt: str) -> str:
        """Reset → wstrzyknięcie payloadu → odpalenie zadania wektora → transkrypt."""
        self._runner.reset_main_db()
        self._apply_injection(jailbreak_prompt)

        with self._runner.invocation(self._attack_id, task=self._injection_point.task) as run_id:
            self._workflow.invoke({"task": self._injection_point.task, "run_id": run_id})

        self.last_run_id = run_id
        return format_run_trace(run_id)

    def ground_truth(self) -> JudgeVerdict | None:
        """Prawdziwa ocena ostatniego przebiegu (ground-truth tool-calle) — niezależna
        od scorera 1–10. Zwraca None, gdy nie było jeszcze żadnego `respond`."""
        if self.last_run_id is None:
            return None
        return judge_evaluate(self.last_run_id, self._objective, llm=self._judge_llm)
