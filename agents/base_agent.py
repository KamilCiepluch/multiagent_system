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


def run_graph_collecting(agent, task: str, config: dict) -> tuple[dict, bool]:
    """Uruchamia graf ReAct STRUMIENIOWO, akumulując kolejne snapshoty stanu.

    Gdy zostanie przekroczony `recursion_limit` (typowe dla słabszych modeli, które
    zapętlają wywołania narzędzi), `agent.invoke` rzuciłby `GraphRecursionError` i
    cały przebieg by przepadł — RAZEM z dowodem ground-truth (faktycznie wykonanymi
    tool-callami). Tu zamiast tego zwracamy to, co agent zdążył zrobić, oraz flagę
    `truncated=True`. Dzięki temu udany atak (np. odczyt sekretu) zostaje policzony,
    a nie ginie w wyjątku. Callbacki (RunLogger) działają tak samo przy stream() co
    przy invoke().

    Zwraca OSTATNI STAN (dict) — zawiera 'messages' oraz, gdy agent ma `response_format`,
    'structured_response' (natywny structured output w JEDNYM przebiegu; w stream(values)
    pojawia się w finalnym stanie)."""
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
        # Natywny response_format jest ŚCISŁY: gdy model wyprodukuje structured output niezgodny
        # ze schematem, rzuca — co bez obsługi wywaliłoby cały przebieg (agent→supervisor→workflow).
        # NIE crashujemy: dołączamy surową finalną wiadomość modelu (niesie ją wyjątek w ai_message)
        # jako fallback; supervisor odczyta z niej rolę/prośbę (są w treści, choć JSON się nie sparsował).
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
        # Ostatni obiekt RESPONSE_SCHEMA z natywnego structured output (state['structured_response'])
        # — do inspekcji/debugowania; run() i tak zwraca string (render) dla supervisora.
        self.last_structured = None
        skill_tools = self._build_skill_tools()
        mcp_tools = [all_mcp_tools[n] for n in self.TOOL_NAMES if n in all_mcp_tools]
        self.tools = mcp_tools + skill_tools
        # Middleware opcjonalne (np. SkillGate) — domyślnie brak, więc create_agent dostaje
        # dokładnie te same argumenty co dotąd dla agentów, które tego nie nadpisują.
        kwargs: dict = {}
        middleware = self._build_middleware()
        if middleware:
            kwargs["middleware"] = middleware
        # Natywny structured output (JEDEN przebieg) zamiast stratnego post-hoc re-formatu LLM.
        # Agent z RESPONSE_SCHEMA zwraca obiekt w state['structured_response'] — supervisor
        # dostaje czysty, niezniekształcony pakiet (rola + prośba + egzekutor).
        if self.RESPONSE_SCHEMA is not None:
            kwargs["response_format"] = self.RESPONSE_SCHEMA
        self._agent = create_agent(
            llm,
            self.tools,
            system_prompt=self.SYSTEM_PROMPT,
            **kwargs,
        )

    def _build_middleware(self) -> list:
        """Lista middleware dla create_agent. Domyślnie pusta — nadpisz w podklasie."""
        return []

    def _render_structured(self, structured, fallback_text: str, tool_calls: list | None = None) -> str:
        """Zamienia obiekt RESPONSE_SCHEMA na czytelny tekst. Nadpisz w podklasie.
        `tool_calls` (opcjonalnie) pozwala uzupełnić pola deterministycznie z wyników narzędzi."""
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
            state, truncated = run_graph_collecting(self._agent, task, config)
            messages = state.get("messages", [])
            tool_calls = _extract_tool_calls(messages)
            final_output = messages[-1].content if messages else "[brak odpowiedzi agenta]"
            if truncated:
                final_output = str(final_output) + _RECURSION_NOTE
            elif self.RESPONSE_SCHEMA is not None:
                # Natywny structured output (jeden przebieg) — render DETERMINISTYCZNY z obiektu,
                # bez drugiego wywołania LLM. Gdy modelowi nie udało się wyprodukować obiektu
                # (rzadkie), zostaw surowy final. Render dostaje też tool_calls — by uzupełnić
                # pola (np. nadawca/rola) DETERMINISTYCZNIE z wyników narzędzi, nie z konfabulacji modelu.
                structured = state.get("structured_response")
                if structured is not None:
                    self.last_structured = structured
                    final_output = self._render_structured(structured, str(final_output), tool_calls)

            if logger is not None:
                logger.finish_agent(inv_id, final_output)

            # Audyt ataków (baza agent_audit) — zachowane dla forensiki/show_run.py
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
