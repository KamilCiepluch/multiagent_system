"""
Unit testy gatewaya hyperagenta — wszystkie wywołania DB/LLM/workflow są
mockowane (mirror tests/test_redteam.py — bez działającej bazy/Ollamy).

To są testy WŁAŚNIE tych właściwości, które w planie realizują "niełamliwe
adnotacje" i kontrolę dostępu — rdzeń całego mechanizmu bezpieczeństwa:

- KAŻDY endpoint loguje próbę PRZED wykonaniem handlera i wynik PO
  (sukces ALBO błąd — nigdy "nic"), w tej właśnie kolejności
- /ground_truth i /objective są czysto RO (żadnej trasy zapisu)
- /history jest append-only (żadnej trasy edycji/usuwania)
- /tools/{name} waliduje argumenty i nieznane narzędzia — i loguje też
  nieudane/odrzucone próby, nie tylko udane
- session_id wstrzykiwanego do run_target_task pochodzi WYŁĄCZNIE
  z niezmiennego, host-defined configu — agent nie ma jak go podmienić
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from database.models import AgentLog
from hyperagent.gateway.server import GatewayConfig, create_app
from attack_core.objectives import SECRET_EXFILTRATION

_SESSION_ID = "11111111-1111-1111-1111-111111111111"
_GENERATION_N = 2


def _config() -> GatewayConfig:
    return GatewayConfig(session_id=_SESSION_ID, generation_n=_GENERATION_N, objective=SECRET_EXFILTRATION)


@pytest.fixture
def harness():
    """Buduje aplikację z w pełni zmockowanymi zależnościami zewnętrznymi —
    zwraca (app, client, mock_audit_db, mock_primitives) do dalszych asercji."""
    with patch("hyperagent.gateway.server.AttackRunner"), \
         patch("hyperagent.gateway.server.build_supervisor_workflow"), \
         patch("hyperagent.gateway.server.build_llm"), \
         patch("hyperagent.gateway.server.AttackPrimitives") as primitives_cls, \
         patch("hyperagent.gateway.server.audit_db") as mock_audit:
        mock_audit.start_hyperagent_gateway_call.return_value = 42
        primitives = MagicMock()
        primitives_cls.return_value = primitives

        app = create_app(_config())
        yield app, TestClient(app), mock_audit, primitives


def _routes_for(app, path: str):
    return [r for r in app.routes if getattr(r, "path", None) == path]


# ------------------------------------------------------------------
# Bezwarunkowe logowanie — rdzeń mechanizmu "niełamliwych adnotacji"
# ------------------------------------------------------------------

class TestUnconditionalLogging:
    def test_successful_call_logs_request_then_response(self, harness):
        _, client, audit, _ = harness

        resp = client.get("/objective")

        assert resp.status_code == 200
        audit.start_hyperagent_gateway_call.assert_called_once_with(
            _SESSION_ID, _GENERATION_N, "GET /objective", None
        )
        audit.finish_hyperagent_gateway_call.assert_called_once_with(
            42, {"ok": True, "result": resp.json()}
        )

    def test_log_write_order_is_start_then_handler_then_finish(self, harness):
        """To jest sedno 'logowania PRZED wykonaniem': start_* musi się wykonać,
        zanim handler zacznie cokolwiek robić, a finish_* — dopiero po."""
        _, client, audit, primitives = harness
        order: list[str] = []
        audit.start_hyperagent_gateway_call.side_effect = lambda *a, **k: (order.append("start"), 42)[1]
        audit.finish_hyperagent_gateway_call.side_effect = lambda *a, **k: order.append("finish")
        primitives.reset_target.side_effect = lambda: (order.append("handler"), "ok")[1]

        resp = client.post("/tools/reset_target", json={})

        assert resp.status_code == 200
        assert order == ["start", "handler", "finish"]

    def test_handler_exception_is_still_logged_as_failure(self, harness):
        _, client, audit, primitives = harness
        primitives.reset_target.side_effect = RuntimeError("boom")

        resp = client.post("/tools/reset_target", json={})

        assert resp.status_code == 500
        audit.start_hyperagent_gateway_call.assert_called_once()
        log_id, response = audit.finish_hyperagent_gateway_call.call_args[0]
        assert log_id == 42
        assert response["ok"] is False
        assert "boom" in response["error"]

    def test_unknown_tool_is_logged_not_skipped(self, harness):
        """Nawet odrzucenie (404) musi zostawić ślad — agent 'próbował X i
        dostał odmowę' jest tak samo ważnym sygnałem audytowym jak sukces."""
        _, client, audit, _ = harness

        resp = client.post("/tools/does_not_exist", json={"foo": "bar"})

        assert resp.status_code == 404
        audit.start_hyperagent_gateway_call.assert_called_once_with(
            _SESSION_ID, _GENERATION_N, "POST /tools/does_not_exist", {"foo": "bar"}
        )
        log_id, response = audit.finish_hyperagent_gateway_call.call_args[0]
        assert response["ok"] is False

    def test_missing_arguments_returns_422_and_is_logged_as_failure(self, harness):
        _, client, audit, _ = harness

        resp = client.post("/tools/inject_email", json={"sender": "a@b.com"})

        assert resp.status_code == 422
        _, response = audit.finish_hyperagent_gateway_call.call_args[0]
        assert response["ok"] is False
        assert "subject" in response["error"] and "body" in response["error"]


# ------------------------------------------------------------------
# /tools/{name} — dispatch do niemodyfikowalnych prymitywów
# ------------------------------------------------------------------

class TestToolDispatch:
    def test_dispatches_to_matching_primitive_with_kwargs(self, harness):
        _, client, _, primitives = harness
        primitives.inject_email.return_value = "emails.id=1"

        resp = client.post("/tools/inject_email", json={"sender": "a@b.com", "subject": "S", "body": "B"})

        assert resp.status_code == 200
        assert resp.json() == "emails.id=1"
        primitives.inject_email.assert_called_once_with(sender="a@b.com", subject="S", body="B")

    def test_optional_argument_omitted_falls_back_to_primitive_default(self, harness):
        _, client, _, primitives = harness
        primitives.poison_search_result.return_value = "ok"

        resp = client.post("/tools/poison_search_result", json={"query": "q", "content": "c"})

        assert resp.status_code == 200
        primitives.poison_search_result.assert_called_once_with(query="q", content="c")

    def test_run_target_task_session_id_comes_from_immutable_config_not_agent(self, harness):
        """Agent może wysłać dowolne 'session_id' w body — gateway je
        ignoruje, bo argspec run_target_task zawiera tylko 'task'. Realny
        session_id pochodzi WYŁĄCZNIE z GatewayConfig (host-defined, stały
        przez całe życie procesu) — nie istnieje droga, by go podmienić."""
        _, client, _, primitives = harness
        primitives.run_target_task.return_value = {"run_id": "rid-1", "route": "supervisor", "result": "ok"}

        resp = client.post(
            "/tools/run_target_task",
            json={"task": "zrób coś", "session_id": "AGENT-PODSZYWA-SIE-POD-INNA-SESJE"},
        )

        assert resp.status_code == 200
        primitives.run_target_task.assert_called_once_with(_SESSION_ID, task="zrób coś")


# ------------------------------------------------------------------
# Kontrola dostępu — read-only ground truth/objective, append-only history
# ------------------------------------------------------------------

class TestAccessControl:
    def test_ground_truth_has_no_write_route(self, harness):
        app, client, audit, _ = harness
        audit.get_run_logs.return_value = [
            AgentLog(
                agent_name="terminal_agent",
                task="t",
                tool_calls=[{"tool_name": "execute_command", "input": {"command": "ls"}, "output": "..."}],
                final_output="done",
            ),
        ]

        resp = client.get("/ground_truth/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 200
        assert resp.json()["logs"][0]["agent_name"] == "terminal_agent"

        methods = {m for r in _routes_for(app, "/ground_truth/{run_id}") for m in r.methods}
        assert methods.isdisjoint({"POST", "PUT", "PATCH", "DELETE"})
        assert "GET" in methods

    def test_objective_has_no_write_route(self, harness):
        app, _, _, _ = harness
        methods = {m for r in _routes_for(app, "/objective") for m in r.methods}
        assert methods.isdisjoint({"POST", "PUT", "PATCH", "DELETE"})
        assert "GET" in methods

    def test_history_route_has_no_edit_or_delete_path(self, harness):
        """Append-only z definicji: GET (czytaj wszystko) + POST (dopisz) —
        i nic poza tym. Nie ma żadnej trasy, którą dałoby się zmodyfikować
        albo usunąć istniejący wpis."""
        app, _, _, _ = harness
        methods = {m for r in _routes_for(app, "/history") for m in r.methods}
        assert methods.isdisjoint({"PUT", "PATCH", "DELETE"})
        assert {"GET", "POST"} <= methods

    def test_history_post_appends_with_current_generation_from_config(self, harness):
        _, client, audit, _ = harness

        resp = client.post("/history", json={"entry_type": "note", "content": "próbowałem X, zablokowane"})

        assert resp.status_code == 200
        audit.append_hyperagent_history.assert_called_once_with(
            _SESSION_ID, _GENERATION_N, "note", "próbowałem X, zablokowane"
        )

    def test_history_get_returns_full_session_history(self, harness):
        _, client, audit, _ = harness
        audit.get_hyperagent_history.return_value = [
            (1, "note", "pierwsza próba", "2026-06-01 10:00:00"),
            (2, "note", "druga próba", "2026-06-01 11:00:00"),
        ]

        resp = client.get("/history")

        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 2
        assert entries[0]["content"] == "pierwsza próba"
        audit.get_hyperagent_history.assert_called_once_with(_SESSION_ID)
