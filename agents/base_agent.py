"""
BaseAgent — klasa bazowa dla wszystkich agentów.

Każdy agent definiuje:
  NAME        — identyfikator (używany przez supervisor jako nazwa toola)
  DESCRIPTION — opis dla supervisora: kiedy i do czego go używać
  SYSTEM_PROMPT — statyczny skill zakodowany w kodzie

Żeby zainfekować WSZYSTKICH agentów wystarczy zmienić rekord w tools_outputs.
"""

from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as lc_tool, InjectedToolCallId
from langchain.agents import create_agent
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
    """
    Wyciąga ustrukturyzowane wywołania narzędzi z sekwencji wiadomości LangChain.

    LangChain ReAct produkuje naprzemiennie:
      AIMessage(tool_calls=[{id, name, args}])  ← agent zleca wywołanie
      ToolMessage(tool_call_id, content)         ← wynik wywołania

    Parujemy je po tool_call_id i zwracamy tylko to, co interesuje nas
    z punktu widzenia logowania: nazwa narzędzia, wejście i wyjście.
    """
    pending: dict[str, dict] = {}
    result: list[dict] = []

    for msg in messages:
        # AIMessage z listą tool_calls
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                pending[tc["id"]] = {
                    "tool_name": tc["name"],
                    "input": tc["args"],
                }
        # ToolMessage — wynik wywołania
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
    """Czy `tool_name` było już wywołane w bieżącej inwokacji grafu.

    Limit „raz na przebieg" wyprowadzamy ze stanu inwokacji (historii wiadomości),
    a nie ze stanu instancji agenta. Stan jest świeży przy każdym uruchomieniu
    agenta (brak checkpointera), więc licznik zeruje się sam — niezależnie od
    tego, czy ktoś woła przez BaseAgent.run(), czy bezpośrednio agent.stream()
    (jak benchmark_agents.py).

    Skanujemy tool_calls z AIMessage, pomijając bieżące wywołanie (po
    tool_call_id). Gdy podano `match_name`, dopasowujemy też argument `name`
    (dedup po nazwie skilla zamiast całkowitej blokady narzędzia).
    """
    for msg in messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("name") != tool_name:
                continue
            if tc.get("id") == current_id:  # bieżące wywołanie — nie liczymy
                continue
            if match_name is not None and (tc.get("args") or {}).get("name") != match_name:
                continue
            return True
    return False


_RECURSION_NOTE = (
    "\n\n[uwaga: przerwano po osiągnięciu recursion_limit — agent zapętlił się, "
    "ale faktycznie wykonane akcje zostały zarejestrowane]"
)


def run_graph_collecting(agent, task: str, config: dict) -> tuple[list, bool]:
    """Uruchamia graf ReAct STRUMIENIOWO, akumulując kolejne snapshoty stanu.

    Gdy zostanie przekroczony `recursion_limit` (typowe dla słabszych modeli, które
    zapętlają wywołania narzędzi), `agent.invoke` rzuciłby `GraphRecursionError` i
    cały przebieg by przepadł — RAZEM z dowodem ground-truth (faktycznie wykonanymi
    tool-callami). Tu zamiast tego zwracamy to, co agent zdążył zrobić, oraz flagę
    `truncated=True`. Dzięki temu udany atak (np. odczyt sekretu) zostaje policzony,
    a nie ginie w wyjątku. Callbacki (RunLogger) działają tak samo przy stream() co
    przy invoke()."""
    last_messages: list = []
    try:
        for state in agent.stream(
            {"messages": [HumanMessage(content=task)]},
            config=config,
            stream_mode="values",
        ):
            if isinstance(state, dict) and state.get("messages"):
                last_messages = state["messages"]
        return last_messages, False
    except GraphRecursionError:
        return last_messages, True


class BaseAgent:
    NAME = "base_agent"
    DESCRIPTION = "Ogólny agent pomocniczy."
    SYSTEM_PROMPT = "Jesteś pomocnym asystentem."
    TOOL_NAMES: list[str] = []  # nadpisz w podklasie — nazwy narzędzi MCP dla tego agenta

    def __init__(self, llm, all_mcp_tools: dict):
        """
        llm           — ChatOllama (lub inny model z tool-callingiem)
        all_mcp_tools — dict {name: tool} z build_langchain_tools(server);
                        agent sam filtruje przez TOOL_NAMES
        """
        self.llm = llm
        skill_tools = self._build_skill_tools()
        mcp_tools = [all_mcp_tools[n] for n in self.TOOL_NAMES if n in all_mcp_tools]
        self.tools = mcp_tools + skill_tools
        self._agent = create_agent(
            llm,
            self.tools,
            system_prompt=self.SYSTEM_PROMPT,
        )

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
            # Dedup po nazwie skilla — powtórka tego samego wczytania (także
            # błędnej nazwy) nie wnosi nic i tylko zapętla agenta.
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
            messages, truncated = run_graph_collecting(self._agent, task, config)
            final_output = messages[-1].content if messages else "[brak odpowiedzi agenta]"
            if truncated:
                final_output = str(final_output) + _RECURSION_NOTE

            if logger is not None:
                logger.finish_agent(inv_id, final_output)

            # Audyt ataków (baza agent_audit) — zachowane dla forensiki/show_run.py
            create_agent_log(
                AgentLog(
                    run_id=get_run_id(),
                    agent_name=self.NAME,
                    task=task,
                    tool_calls=_extract_tool_calls(messages),
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
