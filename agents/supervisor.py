"""
Supervisor — orchestrator wieloagentowy zbudowany jako pełny ReAct agent.

W odróżnieniu od Orchestratora (prostego routera 1-do-1), Supervisor:
- może wywoływać agentów wielokrotnie i w dowolnej kolejności,
- przekazuje wyniki jednego agenta jako kontekst do następnego,
- kończy dopiero gdy całe złożone zadanie jest wykonane.

System prompt generowany jest dynamicznie z listy agentów (NAME + DESCRIPTION),
więc dodanie nowego agenta nie wymaga żadnej zmiany w tym pliku.
"""

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from pydantic import BaseModel, Field

from agents.base_agent import BaseAgent
from database.db import create_agent_log
from database.models import AgentLog

SUPERVISOR_PREAMBLE = """Jesteś supervisorem systemu wieloagentowego. Koordynujesz pracę wyspecjalizowanych agentów.

Zasady działania:
- Analizuj zadanie i zdecyduj, którzy agenci są potrzebni i w jakiej kolejności.
- Możesz wywołać tego samego agenta wielokrotnie.
- Wynik jednego agenta możesz przekazać jako kontekst do następnego — wklej go bezpośrednio w treść zadania dla następnego agenta.
- Nie wykonuj sam żadnych operacji — deleguj zawsze do agentów.
- Zakończ dopiero gdy zadanie użytkownika jest w pełni wykonane.

Dostępni agenci:
"""


class _TaskInput(BaseModel):
    task: str = Field(description="Opis zadania do wykonania przez agenta.")


def _make_agent_tool(agent: BaseAgent) -> StructuredTool:
    """
    Zamienia instancję agenta w StructuredTool z jawną nazwą i opisem.
    StructuredTool.from_function pozwala podać description bez docstringa.
    """
    return StructuredTool.from_function(
        func=agent.run,
        name=agent.NAME,
        description=agent.DESCRIPTION,
        args_schema=_TaskInput,
    )


class Supervisor:
    """
    Supervisor jako agent klasy — analogiczny do BaseAgent,
    ale jego "narzędziami" są inne agenty, nie narzędzia MCP.
    """

    NAME = "supervisor"

    def __init__(self, llm, agents: list[BaseAgent]):
        agent_lines = "\n".join(f"- {a.NAME}: {a.DESCRIPTION}" for a in agents)
        system_prompt = SUPERVISOR_PREAMBLE + agent_lines

        agent_tools = [_make_agent_tool(a) for a in agents]

        self._agent = create_agent(llm, agent_tools, system_prompt=system_prompt)

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
