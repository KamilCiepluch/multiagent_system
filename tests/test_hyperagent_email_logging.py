"""
Testy host-side warstwy obserwowalności pętli `hyperagent_email`
(GenerationLogger + AgentTurnCallback).

Jednostkowe, BEZ realnej bazy: podmieniamy moduł `hyperagent_logs_db` na fake'a
zbierającego wywołania w pamięci. Weryfikują, że:
  - call_primitive zapisuje wejście/wyjście i re-raise'uje przy błędzie prymitywu,
  - cykl życia generacji (payload/bramka/ocena) trafia do DB,
  - callback tur LLM rekonstruuje tool-calle + thinking,
  - przy niedostępnej bazie logger NIE rusza DB i NIE rzuca (graceful degradation).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# gen_logger żyje w hyperagent_email/ i importuje swoje sąsiedztwo po nazwie
# (jak loop.py) — dokładamy ten katalog do sys.path zanim go zaimportujemy.
_HE = Path(__file__).resolve().parent.parent / "hyperagent_email"
if str(_HE) not in sys.path:
    sys.path.insert(0, str(_HE))

import gen_logger as gen_logger_module  # noqa: E402
from gen_logger import GenerationLogger  # noqa: E402

_SESSION = "11111111-1111-1111-1111-111111111111"


class FakeDB:
    """Podróbka database.hyperagent_logs_db — zbiera wywołania zamiast pisać do DB."""

    def __init__(self, available: bool = True):
        self._available = available
        self.sessions: list = []
        self.generations: list = []
        self.payloads: list = []
        self.judgements: list = []
        self.self_mods: list = []
        self.finished_gens: list = []
        self.primitives: list = []
        self.turns: list = []
        self._gen_id = 0

    def is_available(self):
        return self._available

    def create_session(self, *a):
        self.sessions.append(a)

    def finish_session(self, *a):
        pass

    def start_generation(self, session_id, generation_n):
        self._gen_id += 1
        self.generations.append((session_id, generation_n, self._gen_id))
        return self._gen_id

    def update_generation_self_mod(self, gen_id, adopted, reason):
        self.self_mods.append((gen_id, adopted, reason))

    def update_generation_payload(self, gen_id, **kw):
        self.payloads.append((gen_id, kw))

    def update_generation_judgement(self, gen_id, run_id, verdict, reasoning, evidence):
        self.judgements.append((gen_id, run_id, verdict, evidence))

    def finish_generation(self, gen_id, status, verdict, host_notice, error):
        self.finished_gens.append((gen_id, status, verdict, error))

    def log_primitive_call(self, gen_id, seq, name, inp, out, is_error, error, dur):
        self.primitives.append(
            {"gen_id": gen_id, "seq": seq, "name": name, "input": inp,
             "output": out, "is_error": is_error, "error": error}
        )

    def add_agent_llm_turn(self, gen_id, seq, attempt, inp, out, thinking, tool_calls, is_error, error):
        self.turns.append(
            {"gen_id": gen_id, "seq": seq, "output": out, "thinking": thinking,
             "tool_calls": tool_calls, "is_error": is_error}
        )


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB(available=True)
    monkeypatch.setattr(gen_logger_module, "db", db)
    return db


@pytest.fixture
def logger(fake_db):
    lg = GenerationLogger(session_id=_SESSION)
    lg.start_session(attack_id=_SESSION, model="FakeLLM", objective="cel",
                     start_gen=0, planned_generations=1)
    lg.start_generation(0)
    return lg


# ─── call_primitive ───────────────────────────────────────────────────────────

def test_call_primitive_records_input_and_output(logger, fake_db):
    result = logger.call_primitive(
        "inject_email", lambda sender, subject, body: f"emails.id=7 ({sender})",
        sender="a@evil.com", subject="Hi", body="treść",
    )
    assert result == "emails.id=7 (a@evil.com)"
    assert len(fake_db.primitives) == 1
    rec = fake_db.primitives[0]
    assert rec["name"] == "inject_email"
    assert rec["input"] == {"sender": "a@evil.com", "subject": "Hi", "body": "treść"}
    assert rec["output"] == "emails.id=7 (a@evil.com)"
    assert rec["is_error"] is False


def test_call_primitive_reraises_and_flags_error(logger, fake_db):
    def boom(**_):
        raise RuntimeError("DB padło")

    with pytest.raises(RuntimeError, match="DB padło"):
        logger.call_primitive("run_target_task", boom, session_id=_SESSION, task="t")

    assert len(fake_db.primitives) == 1
    rec = fake_db.primitives[0]
    assert rec["is_error"] is True
    assert "DB padło" in rec["error"]
    assert rec["output"] is None


def test_primitive_seq_resets_per_generation(logger, fake_db):
    logger.call_primitive("reset_target", lambda: "ok")
    logger.start_generation(1)
    logger.call_primitive("reset_target", lambda: "ok")
    seqs = [p["seq"] for p in fake_db.primitives]
    assert seqs == [1, 1]  # licznik zerowany przy nowej generacji


# ─── cykl życia generacji ──────────────────────────────────────────────────────

def test_payload_and_gate_recorded(logger, fake_db):
    result = {"parse_ok": True, "parse_error": None, "attempts": 1, "refusal": False,
              "sender": "a@evil.com", "subject": "S", "body": "B", "rationale": "R",
              "raw_response": "raw"}
    logger.log_payload(result, gate_problem=None)
    gen_id, kw = fake_db.payloads[0]
    assert kw["sender"] == "a@evil.com"
    assert kw["gate_problem"] is None
    assert kw["parse_ok"] is True


def test_gate_problem_recorded_without_run(logger, fake_db):
    logger.log_payload({"parse_ok": False}, gate_problem="pusta treść maila (body)")
    _, kw = fake_db.payloads[0]
    assert kw["gate_problem"] == "pusta treść maila (body)"
    # bramka odrzuciła → nie powinno być wywołania run_target_task
    assert not any(p["name"] == "run_target_task" for p in fake_db.primitives)


def test_judgement_and_finish(logger, fake_db):
    logger.log_judgement("run-123", "BLOCKED", "agent odmówił", ["evidence-1"])
    logger.finish_generation("completed", "BLOCKED", host_notice=None, error=None)
    assert fake_db.judgements[0][2] == "BLOCKED"
    assert fake_db.finished_gens[0][2] == "BLOCKED"


def test_self_mod_rejection_recorded(logger, fake_db):
    logger.log_self_mod(adopted=False, rejection_reason="SyntaxError w agent.py")
    gen_id, adopted, reason = fake_db.self_mods[0]
    assert adopted is False
    assert "SyntaxError" in reason


# ─── callback wnętrza agenta ───────────────────────────────────────────────────

def _fake_llm_result(content, tool_calls, reasoning):
    msg = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        additional_kwargs={"reasoning_content": reasoning},
    )
    gen = SimpleNamespace(message=msg, generation_info=None, text=content)
    return SimpleNamespace(generations=[[gen]])


def test_agent_callback_records_turn(logger, fake_db):
    cb = logger.agent_callback()
    import uuid
    run_id = uuid.uuid4()
    msgs = [[SimpleNamespace(type="human", content="zrób payload", name=None)]]
    cb.on_chat_model_start({}, msgs, run_id=run_id)
    cb.on_llm_end(
        _fake_llm_result("SENDER: a@evil.com", [{"name": "write_file", "args": {"path": "agent.py"}}], "myślę"),
        run_id=run_id,
    )
    assert len(fake_db.turns) == 1
    turn = fake_db.turns[0]
    assert turn["tool_calls"] == [{"name": "write_file", "args": {"path": "agent.py"}}]
    assert turn["thinking"] == "myślę"
    assert "SENDER" in turn["output"]


# ─── graceful degradation ──────────────────────────────────────────────────────

def test_disabled_when_db_unavailable(monkeypatch):
    db = FakeDB(available=False)
    monkeypatch.setattr(gen_logger_module, "db", db)
    lg = GenerationLogger(session_id=_SESSION)
    assert lg.enabled is False

    lg.start_session(attack_id=_SESSION, model="m", objective="o", start_gen=0, planned_generations=1)
    lg.start_generation(0)

    # call_primitive nadal woła funkcję i zwraca wynik, ale NIE dotyka DB
    out = lg.call_primitive("reset_target", lambda: "ok")
    assert out == "ok"
    assert db.primitives == []
    assert db.generations == []

    # callback też nie rusza DB i nie rzuca
    lg.record_agent_turn(None, "x", None, None, False, None)
    assert db.turns == []
