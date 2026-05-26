"""
BaseAgent — klasa bazowa dla wszystkich agentów.

Każdy agent definiuje:
  NAME        — identyfikator (używany przez supervisor jako nazwa toola)
  DESCRIPTION — opis dla supervisora: kiedy i do czego go używać
  SYSTEM_PROMPT — statyczny skill zakodowany w kodzie

Żeby zainfekować WSZYSTKICH agentów wystarczy zmienić rekord w tools_outputs.
"""

from langchain_core.messages import HumanMessage
from langchain.agents import create_agent

from database.db import create_agent_log
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
        self.tools = mcp_tools
        self._agent = create_agent(
            llm,
            mcp_tools,
            system_prompt=self.SYSTEM_PROMPT,
        )

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
