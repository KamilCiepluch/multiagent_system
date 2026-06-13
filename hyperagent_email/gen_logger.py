"""
GenerationLogger — host-side warstwa obserwowalności pętli `hyperagent_email`.

Jeden GenerationLogger = jedna sesja (jedno uruchomienie `loop.main`). Rozsyła
do DWÓCH kanałów:
  - DB (dedykowana baza hyperagent_logs) — strukturalny, przeszukiwalny zapis,
  - PLIK/KONSOLA (logger `hyperagent_email`) — czytelny ślad na żywo.

Dwie warstwy odporności (patrz docstring schema_hyperagent_logs.sql):
  - W PEŁNI ODPORNE na self-modyfikację (host-side): cykl życia generacji oraz
    `call_primitive` — owinięcie KAŻDEGO wywołania niemodyfikowalnego prymitywu
    ataku (reset_target/inject_email/run_target_task). Wołane wyłącznie z
    `loop.py`, agent nie ma jak ich ominąć ani sfałszować. To odpowiedź na
    pytanie operatora: czy do deterministycznego narzędzia trafiły poprawne dane
    i co zwróciło.
  - BEST-EFFORT (host-bound callback): `record_agent_turn`, wołane przez
    AgentTurnCallback wpięty w obiekt `llm` (patrz `agent_callback.py`).

Wszystkie zapisy DB są owinięte w try/except + graceful degradation
(`is_available`) — logowanie NIGDY nie może wywrócić pętli hyperagenta.
Wzorzec: tracing/run_logger.py:RunLogger nad database/logs_db.py.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable

from database import hyperagent_logs_db as db
from logging_setup import get_logger

from agent_callback import AgentTurnCallback

_log = get_logger("gen_logger")
_KWARG_PREVIEW = 300  # ile znaków wartości argumentu pokazać w kanale plikowym


def _warn(where: str, exc: Exception) -> None:
    print(f"[hyperagent_logs] {where}: {exc}", file=sys.stderr)


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= _KWARG_PREVIEW else text[:_KWARG_PREVIEW] + " […]"


class GenerationLogger:
    """Logger jednej sesji. Trzyma bieżący stan generacji (id + liczniki
    sekwencji), żeby `call_primitive` i `record_agent_turn` mogły przypisać
    zdarzenia do właściwej generacji bez przekazywania kontekstu w kółko."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.enabled = db.is_available()

        self._gen_id: int | None = None       # id bieżącej generacji w DB
        self._gen_n: int | None = None        # numer bieżącej generacji (do logu)
        self._primitive_seq = 0               # licznik wywołań prymitywów (per generacja)
        self._turn_seq = 0                    # licznik tur LLM agenta (per generacja)

    # ------------------------------------------------------------------
    # Sesja
    # ------------------------------------------------------------------

    def start_session(
        self,
        attack_id: str | None,
        model: str | None,
        objective: str | None,
        start_gen: int,
        planned_generations: int,
    ) -> None:
        if not self.enabled:
            print(
                "[hyperagent_logs] Baza hyperagent_logs niedostępna — sesja nie "
                "będzie logowana do DB (zostaje kanał plikowy). Utwórz bazę: "
                "createdb hyperagent_logs && psql -d hyperagent_logs -f "
                "database/schema_hyperagent_logs.sql",
                file=sys.stderr,
            )
            return
        try:
            db.create_session(self.session_id, attack_id, model, objective, start_gen, planned_generations)
        except Exception as exc:
            _warn("create_session", exc)
            self.enabled = False

    def finish_session(self, status: str, final_outcome: str | None) -> None:
        if not self.enabled:
            return
        try:
            db.finish_session(self.session_id, status, final_outcome)
        except Exception as exc:
            _warn("finish_session", exc)

    # ------------------------------------------------------------------
    # Generacja
    # ------------------------------------------------------------------

    def start_generation(self, generation_n: int) -> None:
        self._gen_n = generation_n
        self._primitive_seq = 0
        self._turn_seq = 0
        self._gen_id = None
        if not self.enabled:
            return
        try:
            self._gen_id = db.start_generation(self.session_id, generation_n)
        except Exception as exc:
            _warn("start_generation", exc)

    def log_self_mod(self, adopted: bool, rejection_reason: str | None) -> None:
        if not self.enabled or self._gen_id is None:
            return
        try:
            db.update_generation_self_mod(self._gen_id, adopted, rejection_reason)
        except Exception as exc:
            _warn("update_generation_self_mod", exc)

    def log_payload(self, result: dict, gate_problem: str | None) -> None:
        """Zapisuje wygenerowany payload + werdykt bramki hosta."""
        if not self.enabled or self._gen_id is None:
            return
        try:
            db.update_generation_payload(
                self._gen_id,
                parse_ok=result.get("parse_ok"),
                parse_error=result.get("parse_error"),
                attempts=result.get("attempts"),
                refusal=result.get("refusal"),
                sender=result.get("sender"),
                subject=result.get("subject"),
                body=result.get("body"),
                rationale=result.get("rationale"),
                raw_response=result.get("raw_response"),
                gate_problem=gate_problem,
            )
        except Exception as exc:
            _warn("update_generation_payload", exc)

    def log_judgement(
        self, run_id: str | None, verdict: str | None,
        judge_reasoning: str | None, evidence: list | None,
    ) -> None:
        if not self.enabled or self._gen_id is None:
            return
        try:
            db.update_generation_judgement(self._gen_id, run_id, verdict, judge_reasoning, evidence)
        except Exception as exc:
            _warn("update_generation_judgement", exc)

    def finish_generation(
        self, status: str, verdict: str | None,
        host_notice: str | None, error: str | None,
    ) -> None:
        if not self.enabled or self._gen_id is None:
            return
        try:
            db.finish_generation(self._gen_id, status, verdict, host_notice, error)
        except Exception as exc:
            _warn("finish_generation", exc)

    # ------------------------------------------------------------------
    # Prymitywy ataku — w pełni odporne (host-side)
    # ------------------------------------------------------------------

    def call_primitive(self, name: str, fn: Callable, **kwargs):
        """Wywołuje niemodyfikowalny prymityw ataku, logując DOKŁADNIE co do
        niego trafiło i co zwrócił. Wpis powstaje PO wywołaniu (z `finished_at`),
        a przy wyjątku — z `is_error=True` i re-raise (pętla dostaje wyjątek).

        To jedyny punkt, przez który `loop.py` woła prymitywy — agent nie ma
        żadnej drogi, by to obejść."""
        self._primitive_seq += 1
        seq = self._primitive_seq
        gen = self._gen_n if self._gen_n is not None else -1
        _log.info("[gen %d] → %s(%s)", gen, name, ", ".join(f"{k}={_short(v)}" for k, v in kwargs.items()))
        t0 = time.perf_counter()
        try:
            result = fn(**kwargs)
        except Exception as exc:
            dur = int((time.perf_counter() - t0) * 1000)
            _log.error("[gen %d] ✗ %s rzucił wyjątek po %dms: %s", gen, name, dur, exc)
            self._record_primitive(seq, name, kwargs, None, True, f"{type(exc).__name__}: {exc}", dur)
            raise
        dur = int((time.perf_counter() - t0) * 1000)
        _log.info("[gen %d] ← %s → %s (%dms)", gen, name, _short(result), dur)
        self._record_primitive(seq, name, kwargs, result, False, None, dur)
        return result

    def _record_primitive(self, seq, name, kwargs, output, is_error, error, dur) -> None:
        if not self.enabled or self._gen_id is None:
            return
        try:
            db.log_primitive_call(self._gen_id, seq, name, kwargs, output, is_error, error, dur)
        except Exception as exc:
            _warn("log_primitive_call", exc)

    # ------------------------------------------------------------------
    # Wnętrze agenta — best-effort (wołane przez AgentTurnCallback)
    # ------------------------------------------------------------------

    def agent_callback(self) -> AgentTurnCallback:
        """Handler do wpięcia w obiekt `llm` przez hosta (`loop.py`)."""
        return AgentTurnCallback(self)

    def record_agent_turn(
        self,
        input_messages: list | None,
        output_content: str | None,
        thinking: str | None,
        tool_calls: list | None,
        is_error: bool,
        error: str | None,
    ) -> None:
        self._turn_seq += 1
        if tool_calls:
            _log.debug("[gen %s] tura LLM #%d → tool_calls=%s", self._gen_n, self._turn_seq,
                       [tc.get("name") for tc in tool_calls])
        if not self.enabled or self._gen_id is None:
            return
        try:
            db.add_agent_llm_turn(
                self._gen_id, self._turn_seq, None,
                input_messages, output_content, thinking, tool_calls, is_error, error,
            )
        except Exception as exc:
            _warn("add_agent_llm_turn", exc)
