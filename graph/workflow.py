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
from langgraph.graph.state import CompiledStateGraph
from langchain_ollama import ChatOllama

from mcp.server import MCPServer
from mcp.client import build_langchain_tools
from agents.orchestrator import Orchestrator
from agents.supervisor import Supervisor
from agents.terminal_agent import TerminalAgent
from agents.email_agent import EmailAgent
from agents.search_agent import SearchAgent
from config import settings
from tracing.run_context import set_run_id, set_run_logger
from tracing.run_logger import RunLogger


def _bind_logger(state) -> None:
    """
    Przywraca kontekst przebiegu (run_id + RunLogger) w bieżącym węźle grafu.

    LangGraph wykonuje każdy węzeł w skopiowanym kontekście, więc ContextVar
    ustawiony w jednym węźle nie dociera do następnych. run_id płynie przez stan
    grafu — odzyskujemy po nim logger z rejestru i ustawiamy ContextVar lokalnie,
    żeby agenci wołani synchronicznie w tym węźle widzieli właściwy logger.
    """
    run_id = state.get("run_id")
    if run_id:
        set_run_id(run_id)
        set_run_logger(RunLogger.get(run_id))


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

def build_workflow() -> CompiledStateGraph:
    llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        reasoning=settings.capture_thinking,
    )
    terminal_agent, email_agent, search_agent = _init_agents(llm)
    orchestrator = Orchestrator(llm)

    def orchestrate(state: WorkflowState):
        run_id = state.get("run_id") or str(uuid.uuid4())
        set_run_id(run_id)
        logger = RunLogger.start(run_id, state["task"], mode="orchestrator")
        route = orchestrator.route(state["task"])
        # Router jako wywołanie w logu — daje początek "kolejności agentów"
        logger.log_simple_invocation("orchestrator", state["task"], route)
        return {"route": route, "run_id": run_id}

    def run_terminal(state: WorkflowState):
        _bind_logger(state)
        return {"result": terminal_agent.run(state["task"])}

    def run_email(state: WorkflowState):
        _bind_logger(state)
        return {"result": email_agent.run(state["task"])}

    def run_search(state: WorkflowState):
        _bind_logger(state)
        return {"result": search_agent.run(state["task"])}

    def finalize(state: WorkflowState):
        logger = RunLogger.get(state.get("run_id"))
        if logger is not None:
            logger.finish("completed", state.get("result"), None)
        return {}

    def route_decision(state: WorkflowState) -> Literal["terminal", "email", "search", "file"]:
        return state.get("route", "terminal")  # type: ignore[return-value]

    graph = StateGraph(WorkflowState)

    graph.add_node("orchestrate", orchestrate)
    graph.add_node("terminal", run_terminal)
    graph.add_node("email", run_email)
    graph.add_node("search", run_search)
    graph.add_node("finalize", finalize)

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
    graph.add_edge("terminal", "finalize")
    graph.add_edge("email", "finalize")
    graph.add_edge("search", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


# ------------------------------------------------------------------
# Tryb 2: Supervisor — wieloetapowy, agenci współpracują
# ------------------------------------------------------------------

def build_supervisor_workflow() -> CompiledStateGraph:
    llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        reasoning=settings.capture_thinking,
    )
    agents = _init_agents(llm)
    supervisor = Supervisor(llm, agents)

    def run_supervisor(state: WorkflowState):
        run_id = state.get("run_id") or str(uuid.uuid4())
        set_run_id(run_id)
        logger = RunLogger.start(run_id, state["task"], mode="supervisor")
        try:
            result = supervisor.run(state["task"])
        except Exception as exc:
            logger.finish("error", None, str(exc))
            raise
        logger.finish("completed", result, None)
        return {
            "result": result,
            "route": "supervisor",
            "run_id": run_id,
        }

    graph = StateGraph(WorkflowState)
    graph.add_node("supervisor", run_supervisor)
    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()
