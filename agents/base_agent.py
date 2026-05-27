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


class BaseAgent:
    NAME = "base_agent"
    DESCRIPTION = "Ogólny agent pomocniczy."
    SYSTEM_PROMPT = "Jesteś pomocnym asystentem."

    def __init__(self, llm, mcp_tools: list):
        """
        llm       — ChatOllama (lub inny model z tool-callingiem)
        mcp_tools — lista LangChain tools z build_langchain_tools(server)
        """
        self.llm = llm
        skill_tools = self._build_skill_tools()
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

        steps = [
            {"role": m.type, "content": str(m.content)}
            for m in messages
            if hasattr(m, "type")
        ]
        final_output = messages[-1].content

        create_agent_log(
            AgentLog(agent_name=self.NAME, task=task, steps=steps, final_output=final_output)
        )
        return final_output
