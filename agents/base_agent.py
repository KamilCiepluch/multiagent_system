"""
BaseAgent — klasa bazowa agentów.

Podklasa definiuje NAME, DESCRIPTION, SYSTEM_PROMPT, TOOL_NAMES i opcjonalnie RESPONSE_SCHEMA.
"""

from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as lc_tool, InjectedToolCallId
from langchain.agents import create_agent
from langchain.agents.structured_output import StructuredOutputValidationError
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import InjectedState

from config import settings
from database.db import create_agent_log, get_skill as db_get_skill, list_skills as db_list_skills
from database.models import AgentLog
from tracing.run_context import (
    get_run_id,
    get_run_logger,
    set_current_agent_invocation,
    reset_current_agent_invocation,
)


def _extract_tool_calls(messages: list) -> list[dict]:
    """Paruje AIMessage.tool_calls z ToolMessage po tool_call_id → [{tool_name, input, output}]."""
    pending: dict[str, dict] = {}
    result: list[dict] = []

    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                pending[tc["id"]] = {
                    "tool_name": tc["name"],
                    "input": tc["args"],
                }
        elif type(msg).__name__ == "ToolMessage":
            call_id = getattr(msg, "tool_call_id", None)
            if call_id and call_id in pending:
                entry = pending.pop(call_id)
                entry["output"] = str(msg.content)
                result.append(entry)

    return result


def _called_before(
    messages: list,
    tool_name: str,
    current_id: str,
    match_name: str | None = None,
) -> bool:
    """Czy `tool_name` było już wywołane w tej inwokacji (liczone z historii wiadomości,
    bez checkpointera). `match_name` dodatkowo dopasowuje argument `name` (dedup po skillu)."""
    for msg in messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("name") != tool_name:
                continue
            if tc.get("id") == current_id:
                continue
            if match_name is not None and (tc.get("args") or {}).get("name") != match_name:
                continue
            return True
    return False


_RECURSION_NOTE = (
    "\n\n[uwaga: przerwano po osiągnięciu recursion_limit — agent zapętlił się, "
    "ale faktycznie wykonane akcje zostały zarejestrowane]"
)


def run_graph_collecting(agent, task: str, config: dict) -> tuple[dict, bool]:
    """Uruchamia graf ReAct strumieniowo (stream, nie invoke), akumulując snapshoty stanu.

    Przy przekroczeniu recursion_limit zwraca ostatni stan + truncated=True zamiast rzucać
    GraphRecursionError — zachowuje ground-truth (faktycznie wykonane tool-calle). Ostatni
    stan niesie 'messages' oraz (gdy jest response_format) 'structured_response'."""
    last_state: dict = {}
    try:
        for state in agent.stream(
            {"messages": [HumanMessage(content=task)]},
            config=config,
            stream_mode="values",
        ):
            if isinstance(state, dict) and state.get("messages"):
                last_state = state
        return last_state, False
    except GraphRecursionError:
        return last_state, True
    except StructuredOutputValidationError as e:
        # structured output niezgodny ze schematem — nie crashujemy: dołączamy surową finalną
        # wiadomość jako fallback (supervisor odczyta rolę/prośbę z treści).
        ai = getattr(e, "ai_message", None)
        msgs = list(last_state.get("messages") or [])
        if ai is not None:
            msgs.append(ai)
        return ({**last_state, "messages": msgs} if msgs else last_state), False


class BaseAgent:
    NAME = "base_agent"
    DESCRIPTION = "Ogólny agent pomocniczy."
    SYSTEM_PROMPT = "Jesteś pomocnym asystentem."
    TOOL_NAMES: list[str] = []  # nadpisz w podklasie — nazwy narzędzi MCP dla tego agenta
    # Opcjonalny schemat Pydantic do ustrukturyzowanej FINALNEJ odpowiedzi (None = wyłączone).
    # Domyślnie None → zachowanie agentów bez tej funkcji jest niezmienione.
    RESPONSE_SCHEMA: type | None = None

    def __init__(self, llm, all_mcp_tools: dict):
        """
        llm           — ChatOllama (lub inny model z tool-callingiem)
        all_mcp_tools — dict {name: tool} z build_langchain_tools(server);
                        agent sam filtruje przez TOOL_NAMES
        """
        self.llm = llm
        self.last_structured = None  # ostatni structured output (debug); run() zwraca string
        skill_tools = self._build_skill_tools()
        mcp_tools = [all_mcp_tools[n] for n in self.TOOL_NAMES if n in all_mcp_tools]
        self.tools = mcp_tools + skill_tools
        kwargs: dict = {}
        middleware = self._build_middleware()
        if middleware:
            kwargs["middleware"] = middleware
        # natywny structured output w jednym przebiegu (state['structured_response'])
        if self.RESPONSE_SCHEMA is not None:
            kwargs["response_format"] = self.RESPONSE_SCHEMA
        self._agent = create_agent(
            llm,
            self.tools,
            system_prompt=self.SYSTEM_PROMPT,
            **kwargs,
        )

    def _build_middleware(self) -> list:
        """Middleware dla create_agent. Domyślnie SkillGate (wymusza list_skills). Nadpisz w podklasie."""
        from agents.skill_gate import make_skill_gate
        return [make_skill_gate(self.NAME)]

    def _render_structured(self, structured, fallback_text: str, tool_calls: list | None = None) -> str:
        """Zamienia obiekt RESPONSE_SCHEMA na tekst. Nadpisz w podklasie. `tool_calls` pozwala
        uzupełnić pola deterministycznie z wyników narzędzi."""
        return fallback_text

    def _build_skill_tools(self) -> list:
        agent_name = self.NAME

        @lc_tool
        def list_skills(
            tool_call_id: Annotated[str, InjectedToolCallId],
            messages: Annotated[list, InjectedState("messages")],
        ) -> str:
            """Wylistuj dostępne procedury obsługi zadań (skille). Użyj gdy zadanie pasuje do złożonego scenariusza."""
            if _called_before(messages, "list_skills", tool_call_id):
                return (
                    "list_skills zostało już wywołane w tym przebiegu. "
                    "Użyj wcześniejszej listy zamiast wołać ponownie."
                )
            skills = db_list_skills(agent_name)
            if not skills:
                return "Brak dostępnych skillów."
            return "\n".join(f"{s.name} — {s.description}" for s in skills)

        @lc_tool
        def load_skill(
            name: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
            messages: Annotated[list, InjectedState("messages")],
        ) -> str:
            """Wczytaj pełną treść skilla: kroki, narzędzia i ograniczenia."""
            # dedup: powtórne wczytanie tego samego skilla nic nie wnosi
            if _called_before(messages, "load_skill", tool_call_id, match_name=name):
                return (
                    f"Skill '{name}' został już wczytany w tym przebiegu. "
                    "Użyj wcześniej zwróconej treści zamiast wołać ponownie."
                )
            skill = db_get_skill(name, agent_name)
            if not skill:
                return f"Skill '{name}' nie istnieje lub jest niedostępny."
            return skill.content

        return [list_skills, load_skill]

    def run(self, task: str) -> str:
        logger = get_run_logger()
        inv_id = logger.start_agent(self.NAME, task) if logger else None
        token = set_current_agent_invocation(inv_id)

        config: dict = {"recursion_limit": settings.agent_recursion_limit}
        if logger is not None:
            config["callbacks"] = [logger.handler]

        try:
            state, truncated = run_graph_collecting(self._agent, task, config)
            messages = state.get("messages", [])
            tool_calls = _extract_tool_calls(messages)
            final_output = messages[-1].content if messages else "[brak odpowiedzi agenta]"
            if truncated:
                final_output = str(final_output) + _RECURSION_NOTE
            elif self.RESPONSE_SCHEMA is not None:
                # render deterministyczny z obiektu (bez 2. wywołania LLM); tool_calls uzupełniają pola
                structured = state.get("structured_response")
                if structured is not None:
                    self.last_structured = structured
                    final_output = self._render_structured(structured, str(final_output), tool_calls)

            if logger is not None:
                logger.finish_agent(inv_id, final_output)

            # audyt (agent_audit) — forensika/show_run.py
            create_agent_log(
                AgentLog(
                    run_id=get_run_id(),
                    agent_name=self.NAME,
                    task=task,
                    tool_calls=tool_calls,
                    final_output=final_output,
                )
            )
            return final_output
        except Exception as exc:
            if logger is not None:
                logger.finish_agent(inv_id, None, status="error", error=str(exc))
            raise
        finally:
            reset_current_agent_invocation(token)
