"""
LangGraph StateGraph — dwa tryby pracy:

  build_workflow()            — Orchestrator (prosty router 1-do-1)
    START → orchestrate → [terminal | email | search | file] → END
    Jedno zadanie → jeden agent.

  build_supervisor_workflow() — Supervisor (wieloetapowy)
    START → supervisor → END
    Supervisor sam decyduje ile agentów wywołać i w jakiej kolejności.
    Wyniki jednego agenta płyną jako kontekst do następnego.
"""

from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama

from mcp.server import MCPServer
from mcp.client import build_langchain_tools
from agents.orchestrator import Orchestrator
from agents.supervisor import Supervisor
from agents.terminal_agent import TerminalAgent
from agents.email_agent import EmailAgent
from agents.search_agent import SearchAgent
from agents.file_agent import FileAgent
from config import settings


# ------------------------------------------------------------------
# Stan grafu
# ------------------------------------------------------------------

class WorkflowState(TypedDict):
    task: str
    route: str
    result: str


# ------------------------------------------------------------------
# Budowa grafu
# ------------------------------------------------------------------

def _init_agents(llm):
    """Wspólna inicjalizacja agentów — LLM i MCP tworzone raz."""
    mcp_server = MCPServer()
    mcp_tools = build_langchain_tools(mcp_server)
    return [
        TerminalAgent(llm, mcp_tools),
        EmailAgent(llm, mcp_tools),
        SearchAgent(llm, mcp_tools),
        FileAgent(llm, mcp_tools),
    ]


# ------------------------------------------------------------------
# Tryb 1: Orchestrator — prosty router, jedno zadanie → jeden agent
# ------------------------------------------------------------------

def build_workflow() -> object:
    llm = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)
    terminal_agent, email_agent, search_agent, file_agent = _init_agents(llm)
    orchestrator = Orchestrator(llm)

    def orchestrate(state: WorkflowState) -> WorkflowState:
        route = orchestrator.route(state["task"])
        return {"route": route}

    def run_terminal(state: WorkflowState) -> WorkflowState:
        result = terminal_agent.run(state["task"])
        return {"result": result}

    def run_email(state: WorkflowState) -> WorkflowState:
        result = email_agent.run(state["task"])
        return {"result": result}

    def run_search(state: WorkflowState) -> WorkflowState:
        result = search_agent.run(state["task"])
        return {"result": result}

    def run_file(state: WorkflowState) -> WorkflowState:
        result = file_agent.run(state["task"])
        return {"result": result}

    def route_decision(state: WorkflowState) -> Literal["terminal", "email", "search", "file"]:
        return state["route"]

    graph = StateGraph(WorkflowState)

    graph.add_node("orchestrate", orchestrate)
    graph.add_node("terminal", run_terminal)
    graph.add_node("email", run_email)
    graph.add_node("search", run_search)
    graph.add_node("file", run_file)

    graph.set_entry_point("orchestrate")
    graph.add_conditional_edges(
        "orchestrate",
        route_decision,
        {
            "terminal": "terminal",
            "email": "email",
            "search": "search",
            "file": "file",
        },
    )
    graph.add_edge("terminal", END)
    graph.add_edge("email", END)
    graph.add_edge("search", END)
    graph.add_edge("file", END)

    return graph.compile()


# ------------------------------------------------------------------
# Tryb 2: Supervisor — wieloetapowy, agenci współpracują
# ------------------------------------------------------------------

def build_supervisor_workflow() -> object:
    llm = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)
    agents = _init_agents(llm)
    supervisor = Supervisor(llm, agents)

    def run_supervisor(state: WorkflowState) -> WorkflowState:
        return {"result": supervisor.run(state["task"]), "route": "supervisor"}

    graph = StateGraph(WorkflowState)
    graph.add_node("supervisor", run_supervisor)
    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()
