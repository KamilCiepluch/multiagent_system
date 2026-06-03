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

import uuid
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
from config import settings
from tracing.run_context import set_run_id


# ------------------------------------------------------------------
# Stan grafu
# Podział na wymagane (task) i opcjonalne (ustawiane przez węzły).
# ------------------------------------------------------------------

class _WorkflowRequired(TypedDict):
    task: str


class WorkflowState(_WorkflowRequired, total=False):
    route: str
    result: str
    run_id: str


# ------------------------------------------------------------------
# Budowa grafu
# ------------------------------------------------------------------

def _init_agents(llm):
    """Wspólna inicjalizacja agentów — LLM i MCP tworzone raz."""
    mcp_server = MCPServer()
    all_mcp_tools = build_langchain_tools(mcp_server)  # dict {name: tool}
    return [
        TerminalAgent(llm, all_mcp_tools),
        EmailAgent(llm, all_mcp_tools),
        SearchAgent(llm, all_mcp_tools),
    ]


# ------------------------------------------------------------------
# Tryb 1: Orchestrator — prosty router, jedno zadanie → jeden agent
# ------------------------------------------------------------------

def build_workflow() -> object:
    llm = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)
    terminal_agent, email_agent, search_agent = _init_agents(llm)
    orchestrator = Orchestrator(llm)

    def orchestrate(state: WorkflowState):
        run_id = state.get("run_id") or str(uuid.uuid4())
        set_run_id(run_id)
        route = orchestrator.route(state["task"])
        return {"route": route, "run_id": run_id}

    def run_terminal(state: WorkflowState):
        return {"result": terminal_agent.run(state["task"])}

    def run_email(state: WorkflowState):
        return {"result": email_agent.run(state["task"])}

    def run_search(state: WorkflowState):
        return {"result": search_agent.run(state["task"])}


    def route_decision(state: WorkflowState) -> Literal["terminal", "email", "search", "file"]:
        return state.get("route", "terminal")  # type: ignore[return-value]

    graph = StateGraph(WorkflowState)

    graph.add_node("orchestrate", orchestrate)
    graph.add_node("terminal", run_terminal)
    graph.add_node("email", run_email)
    graph.add_node("search", run_search)

    graph.set_entry_point("orchestrate")
    graph.add_conditional_edges(
        "orchestrate",
        route_decision,
        {
            "terminal": "terminal",
            "email": "email",
            "search": "search",
        },
    )
    graph.add_edge("terminal", END)
    graph.add_edge("email", END)
    graph.add_edge("search", END)

    return graph.compile()


# ------------------------------------------------------------------
# Tryb 2: Supervisor — wieloetapowy, agenci współpracują
# ------------------------------------------------------------------

def build_supervisor_workflow() -> object:
    llm = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)
    agents = _init_agents(llm)
    supervisor = Supervisor(llm, agents)

    def run_supervisor(state: WorkflowState):
        run_id = state.get("run_id") or str(uuid.uuid4())
        set_run_id(run_id)
        return {
            "result": supervisor.run(state["task"]),
            "route": "supervisor",
            "run_id": run_id,
        }

    graph = StateGraph(WorkflowState)
    graph.add_node("supervisor", run_supervisor)
    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()
