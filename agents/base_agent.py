"""
BaseAgent — klasa bazowa dla wszystkich agentów.

Każdy agent definiuje:
  NAME        — identyfikator (używany przez supervisor jako nazwa toola)
  DESCRIPTION — opis dla supervisora: kiedy i do czego go używać
  SYSTEM_PROMPT — statyczny skill zakodowany w kodzie

Żeby zainfekować WSZYSTKICH agentów wystarczy zmienić rekord w tools_outputs.
"""

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as lc_tool
from langchain.agents import create_agent

from database.db import create_agent_log, get_skill as db_get_skill, list_skills as db_list_skills
from database.models import AgentLog
from tracing.run_context import get_run_id


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
        def list_skills() -> str:
            """Wylistuj dostępne procedury obsługi zadań (skille). Użyj gdy zadanie pasuje do złożonego scenariusza."""
            skills = db_list_skills(agent_name)
            if not skills:
                return "Brak dostępnych skillów."
            return "\n".join(f"{s.name} — {s.description}" for s in skills)

        @lc_tool
        def load_skill(name: str) -> str:
            """Wczytaj pełną treść skilla: kroki, narzędzia i ograniczenia."""
            skill = db_get_skill(name, agent_name)
            if not skill:
                return f"Skill '{name}' nie istnieje lub jest niedostępny."
            return skill.content

        return [list_skills, load_skill]

    def run(self, task: str) -> str:
        result = self._agent.invoke({"messages": [HumanMessage(content=task)]})
        messages = result["messages"]

        tool_calls = _extract_tool_calls(messages)
        final_output = messages[-1].content

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
