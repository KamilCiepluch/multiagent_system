"""
Gateway — JEDYNY most między zamkniętym w kontenerze hyperagentem a światem
zewnętrznym (narzędzia ataku, LLM, ground truth, własna historia, cel ataku).

To jest fizyczna realizacja "niełamliwego mechanizmu logowania", o który
prosił użytkownik: agent może przepisać dosłownie CAŁY swój kod — łącznie
z własną orkiestracją — ale nie ma żadnej drogi, by ominąć ten proces, bo:

  1. kod gatewaya nie znajduje się w katalogu, który agent może zapisywać
     (żyje w osobnym kontenerze/procesie, na hoście — poza zasięgiem agenta);
  2. agent siedzi na sieci Docker `internal: true` — jedyna trasa sieciowa
     na zewnątrz to ten właśnie proces (Postgres/Ollama/internet są
     fizycznie nieosiągalne — patrz hyperagent/sandbox);
  3. KAŻDY request — zanim cokolwiek zrobi — dostaje wpis w
     `hyperagent_gateway_log`, zapisany PRZED wykonaniem handlera i
     uzupełniony PO (sukces lub błąd) — patrz `_call_logged`.

To "adnotacja, której nie da się popsuć": nie dekorator w kodzie agenta
(self-modyfikujący się agent mógłby go usunąć), tylko obowiązkowy krok przez
który fizycznie musi przejść każda użyteczna akcja, zanim cokolwiek się stanie.

Endpointy:
    GET  /objective             — RO: opis celu ataku (stały, host-defined)
    POST /tools/{name}          — niemodyfikowalne prymitywy ataku (gateway/tools.py)
    POST /llm/chat              — proxy do Ollamy (model skonfigurowany dla hyperagenta)
    GET  /ground_truth/{run_id} — RO: faktycznie wykonane tool-calle z audytu
    GET  /history               — RO: cała dotychczasowa historia agenta
    POST /history               — APPEND-ONLY: dopisuje wpis (bez ścieżki edycji/usuwania)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import ollama as _ollama_module
from fastapi import Body, FastAPI, HTTPException
from ollama import ResponseError
from pydantic import BaseModel

from attack_core.runner import AttackRunner
from config import settings
from database import audit_db
from graph.workflow import build_supervisor_workflow
from attack_core.primitives import AttackPrimitives
from hyperagent.gateway.tools import INJECTION_POINT_TOOLS, TOOL_ARGSPEC, TOOL_OPTIONAL_ARGS
from attack_core.objectives import AttackObjective

@dataclass(frozen=True)
class GatewayConfig:
    """Niezmienny zestaw parametrów gatewaya — ustalany WYŁĄCZNIE przez hosta
    przy starcie procesu (env/CLI), poza zasięgiem agenta. `session_id`,
    `generation_n` i `objective` nie mogą się zmienić w trakcie życia procesu
    — host odpala FRESH gateway dla każdej generacji, więc nie istnieje
    żaden endpoint/mechanizm, którym agent mógłby je podmienić, a co za tym
    idzie — nie ma jak 'sfałszować' przypisania swoich akcji do generacji."""

    session_id: str
    generation_n: int
    objective: AttackObjective


_TOOL_CALL_PARSE_ERROR_RAW = re.compile(r"error parsing tool call: raw='(.*)', err=", re.DOTALL)


def _recover_from_tool_call_parse_error(e: ResponseError) -> str | None:
    """Znany defekt Ollamy z modelami `gpt-oss` (format 'harmony'): serwer
    bezwarunkowo próbuje sparsować zwykłą treść odpowiedzi jako wywołanie
    narzędzia (nawet gdy żadnych narzędzi nie zadeklarowano w żądaniu — patrz
    `llm_chat`, `llm.invoke(messages)` bez `tools=`) i wywala się, gdy treść
    nie jest poprawnym JSON-em. Komunikat błędu niesie ze sobą dokładnie to,
    co model wygenerował (`raw='...'`) — odzyskujemy to jako prawdziwą treść
    odpowiedzi zamiast wywalać całe żądanie 500-tką. `None` → nie ten przypadek,
    niech poleci dalej jako prawdziwy błąd."""
    m = _TOOL_CALL_PARSE_ERROR_RAW.search(e.error)
    return m.group(1) if m else None


def _build_ollama_client() -> tuple[_ollama_module.Client, str]:
    """Buduje raw `ollama.Client` + zwraca nazwę modelu.

    Używamy raw klienta zamiast `langchain_ollama.ChatOllama`, bo modele
    reasoning (jak `gpt-oss:20b`) zwracają dwa kanały: `message.content`
    (finalny) i `message.thinking` (wewnętrzne rozumowanie). `ChatOllama`
    stripuje `thinking` — raw klient daje dostęp do obu, co pozwala użyć
    `thinking` jako fallback gdy `content` jest pusty."""
    model = settings.hyperagent_model or settings.ollama_model
    base_url = settings.hyperagent_base_url or settings.ollama_base_url
    return _ollama_module.Client(host=base_url), model


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class HistoryEntry(BaseModel):
    entry_type: str
    content: str


def _call_logged(config: GatewayConfig, endpoint: str, request_payload: dict | None, fn: Callable[[], Any]) -> Any:
    """JEDYNA droga, którą którykolwiek handler poniżej wykonuje pracę.

    Bezwarunkowo zapisuje próbę w `hyperagent_gateway_log` PRZED wywołaniem
    `fn` (więc nawet zawieszenie/crash w środku zostawia trwały ślad), a
    następnie — w finally-jak-semantyce try/except poniżej — uzupełnia ten
    sam wpis wynikiem: sukcesem ALBO opisem błędu. Nigdy nie ma trzeciej
    opcji ('nic się nie zapisało'), bo `start_*` zawsze poprzedza `fn()`,
    a dokładnie jedna z gałęzi except/else zawsze uzupełnia `finish_*`."""
    log_id = audit_db.start_hyperagent_gateway_call(
        config.session_id, config.generation_n, endpoint, request_payload
    )
    try:
        result = fn()
    except HTTPException as e:
        audit_db.finish_hyperagent_gateway_call(
            log_id, {"ok": False, "http_status": e.status_code, "error": e.detail}
        )
        raise
    except Exception as e:
        audit_db.finish_hyperagent_gateway_call(log_id, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e
    else:
        audit_db.finish_hyperagent_gateway_call(log_id, {"ok": True, "result": result})
        return result


def create_app(config: GatewayConfig) -> FastAPI:
    """Buduje aplikację FastAPI dla DANEJ generacji — `runner`/`workflow`/`llm`
    są tworzone raz przy starcie i współdzielone przez wszystkie requesty
    w obrębie życia tego procesu (jeden proces = jedna generacja = jeden,
    niezmienny `GatewayConfig`)."""
    app = FastAPI(
        title="hyperagent-gateway",
        description="Jedyny most hyperagenta do świata zewnętrznego — wszystko tu jest logowane bezwarunkowo.",
    )

    runner = AttackRunner()
    workflow = build_supervisor_workflow()
    primitives = AttackPrimitives(runner, workflow)
    ollama_client, ollama_model = _build_ollama_client()

    @app.get("/objective")
    def get_objective():
        def _do():
            o = config.objective
            available = [
                INJECTION_POINT_TOOLS[pt]
                for pt in o.compatible_injection_points
                if pt in INJECTION_POINT_TOOLS
            ]
            return {
                "id": o.id,
                "name": o.name,
                "description": o.description,
                "compatible_injection_points": o.compatible_injection_points,
                "available_attack_tools": available,
            }

        return _call_logged(config, "GET /objective", None, _do)

    @app.post("/tools/{name}")
    def call_tool(name: str, body: dict = Body(default_factory=dict)):
        def _do():
            if name not in TOOL_ARGSPEC:
                raise HTTPException(
                    status_code=404,
                    detail=f"Nieznane narzędzie '{name}'. Dostępne: {sorted(TOOL_ARGSPEC)}",
                )
            # Sprawdź czy to narzędzie ataku zgodne z celem — narzędzia operacyjne
            # (reset_target, run_target_task) zawsze przechodzą; wektory ataku
            # (inject_email, poison_skill, poison_search_result) tylko jeśli ich
            # injection point jest w objective.compatible_injection_points.
            blocked_by = next(
                (pt for pt, tool in INJECTION_POINT_TOOLS.items() if tool == name), None
            )
            if blocked_by is not None and blocked_by not in config.objective.compatible_injection_points:
                available = [
                    INJECTION_POINT_TOOLS[pt]
                    for pt in config.objective.compatible_injection_points
                    if pt in INJECTION_POINT_TOOLS
                ]
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Wektor '{blocked_by}' nie jest zgodny z celem '{config.objective.id}'. "
                        f"Dostępne wektory ataku: {available}"
                    ),
                )
            argspec = TOOL_ARGSPEC[name]
            optional = TOOL_OPTIONAL_ARGS.get(name, set())
            missing = [a for a in argspec if a not in optional and a not in body]
            if missing:
                raise HTTPException(status_code=422, detail=f"Brakujące argumenty dla '{name}': {missing}")
            kwargs = {a: body[a] for a in argspec if a in body}
            method = getattr(primitives, name)
            if name == "run_target_task":
                return method(config.session_id, **kwargs)
            return method(**kwargs)

        return _call_logged(config, f"POST /tools/{name}", body, _do)

    @app.post("/llm/chat")
    def llm_chat(req: ChatRequest):
        def _do():
            valid_roles = {"system", "user", "assistant"}
            for m in req.messages:
                if m.role not in valid_roles:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Nieznana rola '{m.role}' (oczekiwano: system / user / assistant)",
                    )
            raw_messages = [{"role": m.role, "content": m.content} for m in req.messages]
            try:
                resp = ollama_client.chat(model=ollama_model, messages=raw_messages)
            except ResponseError as e:
                content = _recover_from_tool_call_parse_error(e)
                if content is None:
                    raise
                return {"content": content}
            content = resp.message.content or ""
            if not content:
                # Model reasoning: kanał finalny (`content`) pusty — model
                # "zużył" budżet na `thinking`. Zwracamy `thinking` jako
                # fallback żeby agent nie dostał pustej odpowiedzi i nie
                # zapętlił się na nudge'ach.
                content = getattr(resp.message, "thinking", "") or ""
            return {"content": content}

        return _call_logged(config, "POST /llm/chat", req.model_dump(), _do)

    @app.get("/ground_truth/{run_id}")
    def ground_truth(run_id: str):
        def _do():
            logs = audit_db.get_run_logs(run_id)
            return {
                "run_id": run_id,
                "logs": [
                    {
                        "agent_name": log.agent_name,
                        "task": log.task,
                        "tool_calls": log.tool_calls,
                        "final_output": log.final_output,
                        "attack_success": log.attack_success,
                    }
                    for log in logs
                ],
            }

        return _call_logged(config, f"GET /ground_truth/{run_id}", None, _do)

    @app.get("/history")
    def get_history():
        def _do():
            rows = audit_db.get_hyperagent_history(config.session_id)
            return {
                "entries": [
                    {"generation_n": r[0], "entry_type": r[1], "content": r[2], "created_at": str(r[3])}
                    for r in rows
                ]
            }

        return _call_logged(config, "GET /history", None, _do)

    @app.post("/history")
    def post_history(entry: HistoryEntry):
        def _do():
            audit_db.append_hyperagent_history(
                config.session_id, config.generation_n, entry.entry_type, entry.content
            )
            return {"appended": True}

        return _call_logged(config, "POST /history", entry.model_dump(), _do)

    return app


def run_from_env() -> None:
    """Entry point procesu gatewaya — czyta NIEZMIENNĄ konfigurację z env
    (ustawioną wyłącznie przez hosta przy starcie) i odpala uvicorn.

        python -m hyperagent.gateway.server

    Wymagane zmienne: HYPERAGENT_SESSION_ID, HYPERAGENT_GENERATION_N,
    HYPERAGENT_OBJECTIVE_ID. Opcjonalna: HYPERAGENT_GATEWAY_PORT (domyślnie 8800)."""
    import os

    import uvicorn

    from attack_core.objectives import OBJECTIVES

    session_id = os.environ["HYPERAGENT_SESSION_ID"]
    generation_n = int(os.environ["HYPERAGENT_GENERATION_N"])
    objective_id = os.environ["HYPERAGENT_OBJECTIVE_ID"]
    objective = OBJECTIVES[objective_id]

    config = GatewayConfig(session_id=session_id, generation_n=generation_n, objective=objective)
    app = create_app(config)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("HYPERAGENT_GATEWAY_PORT", "8800")))


if __name__ == "__main__":
    run_from_env()
