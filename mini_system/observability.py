"""Recording layer: every tool call and every message, written to `mini_system_logs`.

Two design rules, both deliberate:

1. It never touches BaseAgent/StatefulAgent. Tool calls are captured by WRAPPING the tools the
   mini system hands to its agents, so the big system's agent classes stay untouched and what
   we record is exactly what the tool received and returned — not a reconstruction.
2. Logging never breaks the chat. Every write goes through `_safe`, so a dead log database
   degrades the system to "works but unobserved" instead of taking the conversation down.
"""

from __future__ import annotations

import contextvars
import json
import sys
import time

from langchain_core.tools import StructuredTool

from mini_system import logs_db

# The invocation a tool call belongs to. A contextvar, because the GUI runs turns on a worker
# thread while the REPL runs them inline.
_current_invocation: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mini_system_invocation", default=None
)


def _safe(fn, *args, **kwargs):
    """Run a logging call; report the first failure and then stay quiet."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if not getattr(_safe, "_warned", False):
            _safe._warned = True
            print(f"[mini_system] a logging write failed — {exc}", file=sys.stderr)
        return None


# Arguments LangGraph injects into a tool (state, call id, …). They are plumbing, not something
# the model chose: they must not reach the log (a message list is not JSON) or the trace.
_INJECTED_ARGS = {"tool_call_id", "messages", "state", "store", "config", "runtime"}


def loggable_args(payload) -> dict:
    """The model-chosen arguments of a call, safe to store as JSON and short enough to print."""
    if not isinstance(payload, dict):
        payload = {"args": payload}
    clean: dict = {}
    for key, value in payload.items():
        if key in _INJECTED_ARGS:
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            value = repr(value)[:200]
        clean[key] = value
    return clean


def _message_row(msg, position: int) -> dict:
    role = {"HumanMessage": "human", "AIMessage": "ai", "ToolMessage": "tool",
            "SystemMessage": "system"}.get(type(msg).__name__, type(msg).__name__)
    calls = [
        {"id": tc.get("id"), "name": tc.get("name"), "args": tc.get("args")}
        for tc in (getattr(msg, "tool_calls", None) or [])
    ]
    return {
        "position": position,
        "role": role,
        "content": str(getattr(msg, "content", "") or ""),
        "tool_calls": calls or None,
        "tool_call_id": getattr(msg, "tool_call_id", None),
        "tool_name": getattr(msg, "name", None) if role == "tool" else None,
    }


class ConversationRecorder:
    """One conversation's worth of logging. Owns the turn/invocation/tool-call sequencing."""

    def __init__(self, conversation_id: str, model: str | None = None, *, note: str | None = None,
                 enabled: bool = True, listener=None):
        self.model = model
        self.note = note
        self.logging_requested = enabled
        self.enabled = False
        self.conversation_id = conversation_id
        self.conversation_pk = None
        self.turn_id = None
        self.turn_index = 0
        self.turn_calls: list[dict] = []
        # `listener(event)` is called live for every agent start and tool call, so a UI can show
        # what the system is doing while it does it. Independent of database logging.
        self.listener = listener
        self._steps: dict[int, int] = {}
        self._seq = 0
        self._agent_of: dict[int, str] = {}
        self._db_id_of: dict[int, int | None] = {}
        self._pages_read: dict[int, list[int]] = {}
        self._depth = 0
        if self.logging_requested:
            _safe(logs_db.ensure_schema)
        self.start_conversation(conversation_id)

    def start_conversation(self, conversation_id: str) -> None:
        """Open a NEW conversation in the log. Turn numbering restarts, so a fresh chat is a
        fresh row rather than a continuation of the previous one under the same id."""
        self.conversation_id = conversation_id
        self.conversation_pk = None
        self.turn_id = None
        self.turn_index = 0
        self.turn_calls = []
        self._depth = 0
        if self.logging_requested:
            self.conversation_pk = _safe(logs_db.create_conversation, conversation_id,
                                         self.model, self.note)
        self.enabled = self.conversation_pk is not None

    def _emit(self, event: dict) -> None:
        if self.listener is not None:
            try:
                self.listener(event)
            except Exception:
                pass  # a broken display must never break the run

    # ---- turns -------------------------------------------------------------

    def start_turn(self, user_message: str) -> None:
        self.turn_index += 1
        self.turn_calls = []
        self._depth = 0
        if self.enabled:
            self.turn_id = _safe(logs_db.start_turn, self.conversation_pk, self.turn_index,
                                 user_message)

    def finish_turn(self, answer: str | None, *, status: str = "ok", error: str | None = None) -> None:
        if self.enabled and self.turn_id is not None:
            _safe(logs_db.finish_turn, self.turn_id, answer, status=status, error=error)
        self.turn_id = None

    def log_agent_messages(self, local_id: int, messages: list, first_position: int = 0) -> None:
        """Persist the messages one agent produced, tied to its own invocation.

        Called for the chat agent with the delta its turn appended (its history grows across the
        conversation, so only the new messages are logged) and for the search agent with its whole
        run, which starts empty every time. Together they are the per-question record: what each
        model said, in order, next to what it called."""
        if not self.enabled or self.turn_id is None or not messages:
            return
        rows = [_message_row(m, first_position + i) for i, m in enumerate(messages)]
        _safe(logs_db.log_messages, self.turn_id, rows, self._db_id_of.get(local_id))

    # ---- agent invocations -------------------------------------------------

    def start_invocation(self, agent_name: str, task: str) -> tuple[int, object]:
        """Open an invocation and make it the parent of any tool call made inside it.

        The id handed out is always a local one, so nesting and agent attribution keep working
        even when database logging is off; the database id (if any) is mapped alongside it."""
        self._seq += 1
        local_id = self._seq
        parent_local = _current_invocation.get()
        db_id = None
        if self.enabled and self.turn_id is not None:
            db_id = _safe(logs_db.start_invocation, self.turn_id, agent_name, task,
                          self._db_id_of.get(parent_local))
        self._agent_of[local_id] = agent_name
        self._db_id_of[local_id] = db_id
        self._depth += 1
        self._emit({"kind": "agent", "agent": agent_name, "task": task, "depth": self._depth})
        return local_id, _current_invocation.set(local_id)

    def finish_invocation(self, local_id: int, token, output: str | None,
                          *, status: str = "ok", error: str | None = None,
                          structured: dict | None = None) -> None:
        _current_invocation.reset(token)
        self._depth = max(0, self._depth - 1)
        db_id = self._db_id_of.get(local_id)
        if db_id is not None:
            _safe(logs_db.finish_invocation, db_id, output, status=status, error=error,
                  structured=self._retrieval_record(local_id, structured))

    def _retrieval_record(self, local_id: int, structured: dict | None) -> dict | None:
        """What the agent stood behind next to what it actually opened: `used_page_ids` as the
        model declared them, `pages_read` derived from the read_page calls it really made. The
        derived half is why the measurement survives a model that ignores the output schema."""
        record = dict(structured or {})
        pages_read = self._pages_read.get(local_id)
        if pages_read:
            record["pages_read"] = pages_read
        return record or None

    # ---- tool calls --------------------------------------------------------

    def tool_started(self, tool_name: str, tool_input) -> None:
        """Announce a call before it runs, so a live trace reads in call order — otherwise a
        tool that calls another agent would print after everything it caused."""
        self._emit({
            "kind": "tool_start", "tool": tool_name, "input": tool_input,
            "agent": self._agent_of.get(_current_invocation.get(), "?"), "depth": self._depth,
        })

    def log_tool_call(self, tool_name: str, tool_input, output, status: str, error: str | None,
                      duration_ms: int) -> None:
        local_id = _current_invocation.get()
        agent = self._agent_of.get(local_id, "?")
        self._steps[local_id] = self._steps.get(local_id, 0) + 1
        if tool_name == "read_page" and status == "ok":
            page_id = (tool_input or {}).get("page_id") if isinstance(tool_input, dict) else None
            try:
                seen = self._pages_read.setdefault(local_id, [])
                if int(page_id) not in seen:  # re-reading a page is in tool_calls, not here
                    seen.append(int(page_id))
            except (TypeError, ValueError):
                pass
        call = {
            "kind": "tool", "agent": agent, "tool": tool_name, "input": tool_input,
            "output": None if output is None else str(output), "status": status, "error": error,
            "duration_ms": duration_ms, "depth": self._depth,
        }
        self.turn_calls.append(call)
        self._emit(call)
        db_id = self._db_id_of.get(local_id)
        if self.enabled and db_id is not None:
            _safe(logs_db.log_tool_call, db_id, self._steps[local_id], tool_name, tool_input,
                  call["output"], status=status, error=error, duration_ms=duration_ms)


def instrument_tools(tools: dict, recorder: ConversationRecorder | None) -> dict:
    """Wrap {name: tool} so every invocation is recorded. Signature, name, description and
    args_schema are preserved, so the model sees exactly the same tools as before."""
    if recorder is None:
        return tools
    return {name: _instrument(tool, recorder) for name, tool in tools.items()}


def _instrument(tool, recorder: ConversationRecorder):
    inner = tool.func

    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        payload = loggable_args(kwargs if kwargs else ({"args": list(args)} if args else {}))
        recorder.tool_started(tool.name, payload)
        try:
            result = inner(*args, **kwargs)
        except Exception as exc:
            recorder.log_tool_call(tool.name, payload, None, "error", str(exc),
                                   int((time.perf_counter() - started) * 1000))
            raise
        recorder.log_tool_call(tool.name, payload, result, "ok", None,
                               int((time.perf_counter() - started) * 1000))
        return result

    return StructuredTool.from_function(
        func=wrapped,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        infer_schema=False,
    )
