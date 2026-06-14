"""
Testy warstwy obserwowalności (baza agent_logs).

Sterują RunLoggerem i callbackiem LangChain syntetycznymi zdarzeniami — bez
Ollamy/LLM — i weryfikują, że znormalizowany log odtwarza strukturę idealnego
logu: prompt systemu, kolejność i zagnieżdżenie agentów, wejście, wczytane
skille, tool calle (z flagą błędu), thinking, wynik oraz zmiany w bazie.

Każdy test sprząta po sobie własny run_id (CASCADE czyści dzieci).
"""

import uuid
from types import SimpleNamespace

import psycopg2
import pytest

from config import settings
from database import logs_db
from tracing import run_context
from tracing.run_logger import RunLogger

pytestmark = pytest.mark.integration


@pytest.fixture
def logs_conn():
    """Połączenie kontrolne do agent_logs; pomija test gdy baza niedostępna."""
    try:
        conn = psycopg2.connect(dsn=settings.logs_db_dsn)
    except Exception as exc:
        pytest.skip(f"Brak bazy agent_logs: {exc}")
    try:
        if not logs_db.is_available():
            pytest.skip("Schemat agent_logs nieobecny")
        yield conn
    finally:
        conn.close()


@pytest.fixture
def cleanup_runs(logs_conn):
    created: list[str] = []
    yield created
    with logs_conn.cursor() as cur:
        for rid in created:
            cur.execute("DELETE FROM runs WHERE run_id = %s::uuid", (rid,))
    logs_conn.commit()


def _fake_llm_response(reasoning: str):
    msg = SimpleNamespace(additional_kwargs={"reasoning_content": reasoning})
    gen = SimpleNamespace(message=msg, generation_info=None)
    return SimpleNamespace(generations=[[gen]])


def test_full_run_structure(cleanup_runs):
    """Pełny przebieg supervisor → agent podrzędny z toolem, skillem, thinkingiem i zmianą DB."""
    run_id = str(uuid.uuid4())
    cleanup_runs.append(run_id)

    logger = RunLogger.start(run_id, task="Sprawdź maile i wyślij potwierdzenie", mode="supervisor")
    assert logger.enabled, "Baza logów powinna być dostępna w teście integracyjnym"

    h = logger.handler

    # --- Supervisor (poziom 0) ---
    sup = logger.start_agent("supervisor", "Sprawdź maile i wyślij potwierdzenie")
    tok_sup = run_context.set_current_agent_invocation(sup)

    # Supervisor woła agenta podrzędnego jako tool
    rid_subtool = uuid.uuid4()
    h.on_tool_start({"name": "email_agent"}, "", run_id=rid_subtool,
                    inputs={"task": "Przeczytaj maile"})

    # --- email_agent (poziom 1, dziecko supervisora) ---
    email = logger.start_agent("email_agent", "Przeczytaj maile")
    tok_email = run_context.set_current_agent_invocation(email)

    # skill: load
    rid_skill = uuid.uuid4()
    h.on_tool_start({"name": "load_skill"}, "", run_id=rid_skill, inputs={"name": "weryfikacja-kontaktu"})
    h.on_tool_end("KROK 1: sprawdź kontakt\nKROK 2: ...", run_id=rid_skill)

    # tool OK
    rid_tool_ok = uuid.uuid4()
    h.on_tool_start({"name": "list_emails"}, "", run_id=rid_tool_ok, inputs={})
    h.on_tool_end("[1] Od: a@b.com | Temat: Hi", run_id=rid_tool_ok)

    # tool z błędem
    rid_tool_err = uuid.uuid4()
    h.on_tool_start({"name": "read_email"}, "", run_id=rid_tool_err, inputs={"email_id": 999})
    h.on_tool_error(ValueError("Mail 999 nie istnieje"), run_id=rid_tool_err)

    # thinking
    h.on_llm_end(_fake_llm_response("Najpierw zweryfikuję nadawcę."), run_id=uuid.uuid4())

    # zmiana w bazie spowodowana przez email_agent
    logger.log_db_change("emails", "INSERT", "id=5", None, {"sender": "agent@system.local"})

    logger.finish_agent(email, "Maile przeczytane, potwierdzenie wysłane.")
    run_context.reset_current_agent_invocation(tok_email)

    # supervisor kończy tool wywołujący agenta podrzędnego
    h.on_tool_end("Maile przeczytane, potwierdzenie wysłane.", run_id=rid_subtool)

    logger.finish_agent(sup, "Zadanie wykonane.")
    run_context.reset_current_agent_invocation(tok_sup)

    logger.finish("completed", "Zadanie wykonane.", None)
    run_context.set_run_logger(None)

    # --- Weryfikacja odczytu ---
    run = logs_db.get_run(run_id)
    assert run["task"] == "Sprawdź maile i wyślij potwierdzenie"
    assert run["mode"] == "supervisor"
    assert run["status"] == "completed"
    assert run["result"] == "Zadanie wykonane."

    invs = logs_db.get_invocations(run_id)
    assert [i["agent_name"] for i in invs] == ["supervisor", "email_agent"]
    sup_row, email_row = invs
    # zagnieżdżenie
    assert sup_row["parent_id"] is None
    assert email_row["parent_id"] == sup_row["id"]
    # kolejność
    assert sup_row["seq"] < email_row["seq"]
    # wejście do agenta (2.1)
    assert email_row["input"] == "Przeczytaj maile"
    # thinking
    assert "zweryfikuję" in email_row["thinking"]
    # wynik
    assert email_row["output"].startswith("Maile przeczytane")

    # supervisor widzi agenta podrzędnego jako tool
    sup_tools = logs_db.get_tool_calls(sup_row["id"])
    assert [t["tool_name"] for t in sup_tools] == ["email_agent"]

    # tool calle email_agenta (2.3) — bez skilli, z flagą błędu
    email_tools = logs_db.get_tool_calls(email_row["id"])
    by_name = {t["tool_name"]: t for t in email_tools}
    assert set(by_name) == {"list_emails", "read_email"}
    assert by_name["list_emails"]["is_error"] is False
    assert by_name["list_emails"]["input"] == {}
    assert by_name["read_email"]["is_error"] is True
    assert "999" in by_name["read_email"]["error"]

    # skille (2.2) — wyodrębnione z toolów
    skills = logs_db.get_loaded_skills(email_row["id"])
    assert len(skills) == 1
    assert skills[0]["action"] == "load"
    assert skills[0]["skill_name"] == "weryfikacja-kontaktu"
    assert "KROK 1" in skills[0]["content"]

    # zmiany w bazie agent_benchmark — z atrybucją do email_agenta
    changes = logs_db.get_db_changes(run_id)
    assert len(changes) == 1
    assert changes[0]["table_name"] == "emails"
    assert changes[0]["operation"] == "INSERT"
    assert changes[0]["invocation_id"] == email_row["id"]
    assert changes[0]["new_value"] == {"sender": "agent@system.local"}


def test_dedup_double_callback(cleanup_runs):
    """Podwójne wywołanie tego samego callbacku (dziedziczenie) nie dubluje wpisów."""
    run_id = str(uuid.uuid4())
    cleanup_runs.append(run_id)
    logger = RunLogger.start(run_id, task="x", mode="orchestrator")
    h = logger.handler

    inv = logger.start_agent("terminal_agent", "x")
    tok = run_context.set_current_agent_invocation(inv)

    rid = uuid.uuid4()
    h.on_tool_start({"name": "execute_command"}, "", run_id=rid, inputs={"command": "ls"})
    h.on_tool_start({"name": "execute_command"}, "", run_id=rid, inputs={"command": "ls"})  # duplikat
    h.on_tool_end("plik1\nplik2", run_id=rid)
    h.on_tool_end("plik1\nplik2", run_id=rid)  # duplikat

    logger.finish_agent(inv, "ok")
    run_context.reset_current_agent_invocation(tok)
    logger.finish("completed", "ok", None)
    run_context.set_run_logger(None)

    tools = logs_db.get_tool_calls(inv)
    assert len(tools) == 1
    assert tools[0]["output"] == "plik1\nplik2"


def test_logging_never_raises_without_logger():
    """Agent bez aktywnego RunLoggera działa — logowanie jest opcjonalne."""
    run_context.set_run_logger(None)
    assert run_context.get_run_logger() is None
    # get_current_agent_invocation domyślnie None — brak wyjątków przy braku kontekstu
    assert run_context.get_current_agent_invocation() is None
