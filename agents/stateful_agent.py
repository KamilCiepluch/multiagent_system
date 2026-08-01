"""StatefulAgent — a conversation-memory layer on top of BaseAgent.

It EXTENDS BaseAgent without modifying it: the base class (and every agent built on it —
email/search/terminal/supervisor) is left untouched. StatefulAgent reuses the base
construction (tools, skills, middleware, create_agent) and its inherited single-shot
`run(task)`, so it still drops into the workflow graph like any other agent. On top of that
it adds multi-turn conversation:

- `chat(message, conversation_id)` — seeds the graph with the prior history + the new turn,
  runs it, then persists the updated history to a swappable ConversationStore.
- `history(conversation_id)` / `reset(conversation_id)` — inspect / start a new conversation.

Any agent that needs a memory of the dialogue can subclass this instead of BaseAgent.
"""

from __future__ import annotations

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from agents.base_agent import BaseAgent, _RECURSION_NOTE, _extract_tool_calls
from agents.conversation_store import ConversationStore, InMemoryConversationStore
from config import settings
from database.db import create_agent_log
from database.models import AgentLog
from tracing.run_context import (
    get_run_id,
    get_run_logger,
    reset_current_agent_invocation,
    set_current_agent_invocation,
)

DEFAULT_CONVERSATION_ID = "default"


class StatefulAgent(BaseAgent):
    """BaseAgent + per-conversation memory. Concrete chat agents subclass this."""

    def __init__(self, llm, all_mcp_tools: dict, *, store: ConversationStore | None = None):
        super().__init__(llm, all_mcp_tools)
        self.store = store or InMemoryConversationStore()

    # ------------------------------------------------------------------
    # Public conversation API
    # ------------------------------------------------------------------

    def chat(self, message: str, *, conversation_id: str = DEFAULT_CONVERSATION_ID) -> str:
        """One dialogue turn: load history, run the graph over it, persist, return the reply."""
        history = self.store.load(conversation_id)
        output, messages = self._invoke_messages(history + [HumanMessage(content=message)], message)
        self.store.save(conversation_id, messages)
        return output

    def history(self, conversation_id: str = DEFAULT_CONVERSATION_ID) -> list[BaseMessage]:
        return self.store.load(conversation_id)

    def reset(self, conversation_id: str = DEFAULT_CONVERSATION_ID) -> None:
        self.store.reset(conversation_id)

    # ------------------------------------------------------------------
    # Graph run seeded with a full message list (mirrors BaseAgent.run's plumbing:
    # tracing + audit), but returns the resulting messages so we can persist them.
    # ------------------------------------------------------------------

    def _invoke_messages(self, input_messages: list[BaseMessage], task: str) -> tuple[str, list[BaseMessage]]:
        logger = get_run_logger()
        inv_id = logger.start_agent(self.NAME, task) if logger else None
        token = set_current_agent_invocation(inv_id)

        config: dict = {"recursion_limit": settings.agent_recursion_limit}
        if logger is not None:
            config["callbacks"] = [logger.handler]

        try:
            state, truncated = self._stream_collect(input_messages, config)
            messages = state.get("messages", [])
            tool_calls = _extract_tool_calls(messages)
            final_output = messages[-1].content if messages else "[no agent response]"
            if truncated:
                final_output = str(final_output) + _RECURSION_NOTE
            elif self.RESPONSE_SCHEMA is not None:
                structured = state.get("structured_response")
                if structured is not None:
                    self.last_structured = structured
                    final_output = self._render_structured(structured, str(final_output), tool_calls)

            if logger is not None:
                logger.finish_agent(inv_id, final_output)

            create_agent_log(
                AgentLog(
                    run_id=get_run_id(),
                    agent_name=self.NAME,
                    task=task,
                    tool_calls=tool_calls,
                    final_output=final_output,
                )
            )
            return final_output, messages
        except Exception as exc:
            if logger is not None:
                logger.finish_agent(inv_id, None, status="error", error=str(exc))
            raise
        finally:
            reset_current_agent_invocation(token)

    def _stream_collect(self, input_messages: list[BaseMessage], config: dict) -> tuple[dict, bool]:
        """Like base_agent.run_graph_collecting but seeded with a full message list instead of
        one task string (the base helper only accepts a single task)."""
        last_state: dict = {}
        try:
            for state in self._agent.stream(
                {"messages": input_messages},
                config=config,
                stream_mode="values",
            ):
                if isinstance(state, dict) and state.get("messages"):
                    last_state = state
            return last_state, False
        except GraphRecursionError:
            return last_state, True
        except StructuredOutputValidationError as e:
            ai = getattr(e, "ai_message", None)
            msgs = list(last_state.get("messages") or [])
            if ai is not None:
                msgs.append(ai)
            return ({**last_state, "messages": msgs} if msgs else last_state), False
