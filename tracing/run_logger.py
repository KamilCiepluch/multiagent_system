"""
RunLogger — warstwa obserwowalności jednego przebiegu systemu agentowego.

Jeden RunLogger = jeden workflow.invoke. Trzyma run_id, liczniki kolejności i
callback LangChain (LogCallbackHandler), który ZDARZENIOWO przechwytuje:
  - on_tool_start/end/error  → tool_calls (input, output, flaga błędu)
                               lub loaded_skills (dla list_skills / load_skill)
  - on_llm_end               → thinking agenta (best-effort, reasoning_content)

Granice agentów (BaseAgent.run / Supervisor.run) jawnie otwierają i zamykają
agent_invocations — dzięki temu nazwa agenta i zagnieżdżenie (parent_id) są
znane wprost, bez zgadywania z drzewa run-id LangChaina. Callback przypisuje
zdarzenia do bieżącego wywołania agenta przez ContextVar
(get_current_agent_invocation) — w synchronicznym invoke jest to zawsze właściwy
agent.

Wszystkie zapisy są owinięte w try/except: logowanie NIGDY nie może wywrócić
działania agenta.
"""

from __future__ import annotations

import sys
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from database import logs_db
from tracing.run_context import (
    get_current_agent_invocation,
    set_run_logger,
)

_SKILL_TOOLS = {"list_skills": "list", "load_skill": "load"}

# Rejestr aktywnych loggerów per run_id. LangGraph uruchamia każdy węzeł w
# skopiowanym kontekście, więc ContextVar ustawiony w jednym węźle nie dociera
# do kolejnych. run_id płynie natomiast przez stan grafu — pozwala odzyskać
# logger w każdym węźle (patrz RunLogger.get / workflow._bind_logger).
_REGISTRY: dict[str, "RunLogger"] = {}


def _warn(where: str, exc: Exception) -> None:
    print(f"[logs] {where}: {exc}", file=sys.stderr)


def _to_text(value: Any) -> str:
    """Normalizuje output narzędzia/agenta do tekstu (ToolMessage → .content)."""
    content = getattr(value, "content", None)
    return str(content) if content is not None else str(value)


def _extract_reasoning(response: Any) -> str | None:
    """Wyciąga thinking/reasoning z LLMResult — best-effort, zależne od modelu."""
    try:
        gens = response.generations
        if not gens or not gens[0]:
            return None
        gen = gens[0][0]
        msg = getattr(gen, "message", None)
        if msg is not None:
            ak = getattr(msg, "additional_kwargs", None) or {}
            reasoning = ak.get("reasoning_content") or ak.get("reasoning")
            if reasoning:
                return str(reasoning).strip()
        gi = getattr(gen, "generation_info", None) or {}
        reasoning = gi.get("reasoning") or gi.get("thinking")
        return str(reasoning).strip() if reasoning else None
    except Exception:
        return None


class RunLogger:
    """Logger jednego przebiegu. Patrz docstring modułu."""

    def __init__(self, run_id: str, enabled: bool):
        self.run_id = run_id
        self.enabled = enabled
        self.handler = LogCallbackHandler(self)

        self._agent_seq = 0           # licznik wywołań agentów (run-level)
        self._dbchange_seq = 0        # licznik zmian DB (run-level)
        self._tool_seq: dict[int, int] = {}   # invocation_id -> licznik tool calli
        self._skill_seq: dict[int, int] = {}  # invocation_id -> licznik skilli
        self._pending: dict[UUID, dict] = {}  # callback run_id -> bufor start→end
        self._seen_llm: set[UUID] = set()      # dedup on_llm_end

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def start(cls, run_id: str, task: str, mode: str | None) -> "RunLogger":
        """Tworzy rekord runu, ustawia logger w ContextVar, zwraca instancję."""
        enabled = logs_db.is_available()
        logger = cls(run_id, enabled)
        if enabled:
            try:
                logs_db.create_run(run_id, task, mode)
            except Exception as exc:
                _warn("create_run", exc)
                logger.enabled = False
        else:
            print(
                "[logs] Baza agent_logs niedostępna — przebieg nie będzie logowany. "
                "Utwórz bazę: createdb agent_logs && psql -d agent_logs -f database/schema_logs.sql",
                file=sys.stderr,
            )
        _REGISTRY[run_id] = logger
        set_run_logger(logger)
        return logger

    @classmethod
    def get(cls, run_id: str | None) -> "RunLogger | None":
        """Odzyskuje logger przebiegu z rejestru po run_id (między węzłami grafu)."""
        return _REGISTRY.get(run_id) if run_id else None

    def finish(self, status: str, result: str | None, error: str | None) -> None:
        _REGISTRY.pop(self.run_id, None)
        if not self.enabled:
            return
        try:
            logs_db.finish_run(self.run_id, status, result, error)
        except Exception as exc:
            _warn("finish_run", exc)

    # ------------------------------------------------------------------
    # Granice agentów
    # ------------------------------------------------------------------

    def start_agent(self, agent_name: str, input_text: str | None) -> int | None:
        if not self.enabled:
            return None
        self._agent_seq += 1
        parent = get_current_agent_invocation()
        try:
            return logs_db.start_invocation(
                self.run_id, parent, self._agent_seq, agent_name, input_text
            )
        except Exception as exc:
            _warn("start_invocation", exc)
            return None

    def finish_agent(
        self, invocation_id: int | None, output: str | None,
        status: str = "completed", error: str | None = None,
    ) -> None:
        if not self.enabled or invocation_id is None:
            return
        try:
            logs_db.finish_invocation(invocation_id, output, status, error)
        except Exception as exc:
            _warn("finish_invocation", exc)

    def log_simple_invocation(
        self, agent_name: str, input_text: str | None, output: str | None
    ) -> None:
        """Wywołanie bez narzędzi (np. router orchestratora) — start+finish naraz."""
        inv = self.start_agent(agent_name, input_text)
        self.finish_agent(inv, output)

    # ------------------------------------------------------------------
    # Zmiany w bazie agent_benchmark (wołane z database.db._audit_change)
    # ------------------------------------------------------------------

    def log_db_change(
        self, table_name: str, operation: str, record_key: str | None,
        old_value: dict | None, new_value: dict | None,
    ) -> None:
        if not self.enabled:
            return
        self._dbchange_seq += 1
        try:
            logs_db.log_db_change(
                self.run_id, get_current_agent_invocation(), self._dbchange_seq,
                table_name, operation, record_key, old_value, new_value,
            )
        except Exception as exc:
            _warn("log_db_change", exc)

    # ------------------------------------------------------------------
    # Wewnętrzne — wołane przez LogCallbackHandler
    # ------------------------------------------------------------------

    def _next_tool_seq(self, inv_id: int) -> int:
        self._tool_seq[inv_id] = self._tool_seq.get(inv_id, 0) + 1
        return self._tool_seq[inv_id]

    def _next_skill_seq(self, inv_id: int) -> int:
        self._skill_seq[inv_id] = self._skill_seq.get(inv_id, 0) + 1
        return self._skill_seq[inv_id]

    def tool_start(self, cb_run_id: UUID, tool_name: str, input_args: dict | None) -> None:
        if not self.enabled or cb_run_id in self._pending:
            return  # dedup: ten sam event może przyjść dwa razy (dziedziczenie callbacków)
        inv_id = get_current_agent_invocation()
        if inv_id is None:
            return

        skill_action = _SKILL_TOOLS.get(tool_name)
        if skill_action is not None:
            # skill: rekord powstaje dopiero na końcu (potrzebujemy treści/wyniku)
            skill_name = (input_args or {}).get("name") if skill_action == "load" else None
            self._pending[cb_run_id] = {
                "kind": "skill", "inv_id": inv_id,
                "action": skill_action, "skill_name": skill_name,
            }
            return

        try:
            tc_id = logs_db.start_tool_call(
                inv_id, self._next_tool_seq(inv_id), tool_name, input_args
            )
            self._pending[cb_run_id] = {"kind": "tool", "tc_id": tc_id, "inv_id": inv_id}
        except Exception as exc:
            _warn("start_tool_call", exc)

    def tool_end(self, cb_run_id: UUID, output: Any, *, is_error: bool, error: str | None) -> None:
        pending = self._pending.pop(cb_run_id, None)
        if pending is None or not self.enabled:
            return
        try:
            if pending["kind"] == "skill":
                logs_db.add_loaded_skill(
                    pending["inv_id"], self._next_skill_seq(pending["inv_id"]),
                    pending["action"], pending["skill_name"],
                    None if output is None else _to_text(output), is_error,
                )
            else:
                logs_db.finish_tool_call(
                    pending["tc_id"],
                    None if output is None else _to_text(output), is_error, error,
                )
        except Exception as exc:
            _warn("tool_end", exc)

    def llm_end(self, cb_run_id: UUID, response: Any) -> None:
        if not self.enabled or cb_run_id in self._seen_llm:
            return
        self._seen_llm.add(cb_run_id)
        inv_id = get_current_agent_invocation()
        if inv_id is None:
            return
        reasoning = _extract_reasoning(response)
        if reasoning:
            try:
                logs_db.append_thinking(inv_id, reasoning)
            except Exception as exc:
                _warn("append_thinking", exc)


class LogCallbackHandler(BaseCallbackHandler):
    """
    Callback LangChain — most między zdarzeniami agenta a RunLoggerem.

    Atrybucja zdarzeń do agenta odbywa się w momencie zdarzenia przez
    get_current_agent_invocation() (ustawiany na granicy agenta). Dedup po
    callback run_id chroni przed podwójnym wywołaniem przy dziedziczeniu
    callbacków między supervisorem a agentami podrzędnymi.
    """

    # Pozwalamy LangChainowi wołać handler na wszystkich poziomach drzewa.
    raise_error = False

    def __init__(self, logger: RunLogger):
        self._logger = logger

    def on_tool_start(
        self, serialized, input_str, *, run_id, parent_run_id=None,
        tags=None, metadata=None, inputs=None, **kwargs,
    ):
        try:
            name = (serialized or {}).get("name") or kwargs.get("name") or "?"
            if isinstance(inputs, dict):
                args = inputs
            elif input_str:
                args = {"input": input_str}
            else:
                args = None
            self._logger.tool_start(run_id, name, args)
        except Exception as exc:
            _warn("on_tool_start", exc)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        try:
            self._logger.tool_end(run_id, output, is_error=False, error=None)
        except Exception as exc:
            _warn("on_tool_end", exc)

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        try:
            self._logger.tool_end(run_id, None, is_error=True, error=str(error))
        except Exception as exc:
            _warn("on_tool_error", exc)

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        try:
            self._logger.llm_end(run_id, response)
        except Exception as exc:
            _warn("on_llm_end", exc)
