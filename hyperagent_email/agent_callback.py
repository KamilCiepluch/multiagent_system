"""
Callback przechwytujący wnętrze agenta LangChain generującego payload
(`workspace/agent.py`) — best-effort warstwa obserwowalności, wpinana przez
HOSTA w obiekt `llm` PRZED przekazaniem go agentowi (patrz `loop.py`).

Dlaczego host, a nie agent: `workspace/agent.py` jest MODYFIKOWALNY (agent może
go przepisać między generacjami). Gdyby logowanie siedziało tam, jedna self-
modyfikacja mogłaby je usunąć. `llm` jest własnością hosta — callback wpięty na
jego instancji (`llm.callbacks = [...]`) jest dziedziczony przez każde wywołanie
`create_agent(llm, …)`, niezależnie od tego, jak agent przepisze swój kod.

Jedna tura = jedno wywołanie modelu. Wyjścia narzędzi agenta
(read_file/write_file/list_files) wracają jako ToolMessage w `input_messages`
KOLEJNEJ tury — dzięki temu cały wewnętrzny ReAct da się odtworzyć z samych tur
LLM, bez przechwytywania zdarzeń narzędziowych (które biegną poza obiektem llm).

Wszystko jest owinięte w try/except: logowanie NIGDY nie może wywrócić agenta.
`raise_error = False` — LangChain ma ignorować wyjątki tego handlera.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

_CONTENT_PREVIEW = 4000   # ile znaków treści wiadomości/odpowiedzi zachować
_MESSAGES_TAIL = 8        # ile ostatnich wiadomości wejściowych zrzucić


def _extract_reasoning(response: Any) -> str | None:
    """Wyciąga thinking/reasoning z LLMResult — best-effort, zależne od modelu
    (kalka tracing/run_logger._extract_reasoning)."""
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


def _truncate(text: str) -> str:
    return text if len(text) <= _CONTENT_PREVIEW else text[:_CONTENT_PREVIEW] + " […]"


def _serialize_messages(messages: list) -> list[dict]:
    """Kompaktowy, JSON-safe zrzut wiadomości wejściowych modelu — rola, treść
    (skrócona) i (dla ToolMessage) nazwa narzędzia, którego wynik niesie."""
    out: list[dict] = []
    for m in messages:
        entry: dict[str, Any] = {
            "role": getattr(m, "type", m.__class__.__name__),
            "content": _truncate(str(getattr(m, "content", ""))),
        }
        name = getattr(m, "name", None)
        if name:
            entry["name"] = name
        out.append(entry)
    return out


def _extract_output(response: Any) -> tuple[str | None, list | None]:
    """Z LLMResult zwraca (treść finalnej odpowiedzi, żądane tool-calle)."""
    try:
        gen = response.generations[0][0]
        msg = getattr(gen, "message", None)
        content = None
        if msg is not None and getattr(msg, "content", None) is not None:
            content = _truncate(str(msg.content))
        elif getattr(gen, "text", None):
            content = _truncate(str(gen.text))
        tool_calls = None
        raw_calls = getattr(msg, "tool_calls", None) if msg is not None else None
        if raw_calls:
            tool_calls = [
                {"name": tc.get("name"), "args": tc.get("args")}
                for tc in raw_calls
            ]
        return content, tool_calls
    except Exception:
        return None, None


class AgentTurnCallback(BaseCallbackHandler):
    """Most między zdarzeniami modelu a GenerationLoggerem. Paruje
    start (wiadomości wejściowe) z end (odpowiedź) po callbackowym run_id."""

    raise_error = False

    def __init__(self, logger):
        self._logger = logger
        self._pending: dict[UUID, list[dict]] = {}  # cb run_id -> input_messages

    # Modele czatowe wołają on_chat_model_start (nie on_llm_start).
    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        try:
            flat = messages[0] if messages and isinstance(messages[0], list) else messages
            self._pending[run_id] = _serialize_messages(list(flat)[-_MESSAGES_TAIL:])
        except Exception:
            self._pending[run_id] = []

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        try:
            self._pending[run_id] = [{"role": "prompt", "content": _truncate(p)} for p in prompts][-_MESSAGES_TAIL:]
        except Exception:
            self._pending[run_id] = []

    def on_llm_end(self, response, *, run_id, **kwargs):
        input_messages = self._pending.pop(run_id, None)
        try:
            content, tool_calls = _extract_output(response)
            thinking = _extract_reasoning(response)
            self._logger.record_agent_turn(
                input_messages=input_messages,
                output_content=content,
                thinking=thinking,
                tool_calls=tool_calls,
                is_error=False,
                error=None,
            )
        except Exception:
            pass

    def on_llm_error(self, error, *, run_id, **kwargs):
        input_messages = self._pending.pop(run_id, None)
        try:
            self._logger.record_agent_turn(
                input_messages=input_messages,
                output_content=None,
                thinking=None,
                tool_calls=None,
                is_error=True,
                error=str(error),
            )
        except Exception:
            pass
