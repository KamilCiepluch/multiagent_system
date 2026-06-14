"""
Warstwa dostępu do bazy logów hyperagenta (hyperagent_logs).

Dedykowana baza obserwowalności pętli `hyperagent_email` — niezależna od
agent_audit (forensika ataków) i agent_logs (przebieg atakowanego systemu).
Schemat znormalizowany: sessions → generations → (primitive_calls | agent_llm_turns).

Operacje są pisane tak, by były odporne na błędy — logowanie nigdy nie może
wywrócić pętli hyperagenta. Funkcje zwracają surowe wartości/krotki; warstwę
wyższego poziomu (sekwencjonowanie, łączenie start/finish) trzyma
GenerationLogger w hyperagent_email/gen_logger.py — dokładnie tak, jak RunLogger
siedzi nad logs_db.
"""

from contextlib import contextmanager

from psycopg2 import pool as pg_pool
from psycopg2.extras import Json

from config import settings

_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.hyperagent_logs_dsn)
    return _pool


@contextmanager
def get_conn():
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def is_available() -> bool:
    """Czy baza hyperagent_logs jest dostępna i ma zaaplikowany schemat."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM sessions LIMIT 1")
        return True
    except Exception:
        return False


def _jsonb(value) -> Json | None:
    return Json(value) if value is not None else None


# ------------------------------------------------------------------
# Sessions
# ------------------------------------------------------------------

def create_session(
    session_id: str,
    attack_id: str | None,
    model: str | None,
    objective: str | None,
    start_gen: int | None,
    planned_generations: int | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions "
                "(session_id, attack_id, model, objective, start_gen, planned_generations) "
                "VALUES (%s::uuid, %s, %s, %s, %s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (session_id, attack_id, model, objective, start_gen, planned_generations),
            )


def finish_session(session_id: str, status: str, final_outcome: str | None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET status = %s, final_outcome = %s, finished_at = NOW() "
                "WHERE session_id = %s::uuid",
                (status, final_outcome, session_id),
            )


# ------------------------------------------------------------------
# Generations
# ------------------------------------------------------------------

def start_generation(session_id: str, generation_n: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO generations (session_id, generation_n) "
                "VALUES (%s::uuid, %s) RETURNING id",
                (session_id, generation_n),
            )
            return cur.fetchone()[0]


def update_generation_self_mod(
    generation_id: int, adopted: bool, rejection_reason: str | None
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE generations "
                "SET self_mod_adopted = %s, self_mod_rejection_reason = %s WHERE id = %s",
                (adopted, rejection_reason, generation_id),
            )


def update_generation_payload(
    generation_id: int,
    parse_ok: bool | None,
    parse_error: str | None,
    attempts: int | None,
    refusal: bool | None,
    sender: str | None,
    subject: str | None,
    body: str | None,
    rationale: str | None,
    raw_response: str | None,
    gate_problem: str | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE generations SET "
                "parse_ok = %s, parse_error = %s, attempts = %s, refusal = %s, "
                "sender = %s, subject = %s, body = %s, rationale = %s, "
                "raw_response = %s, gate_problem = %s WHERE id = %s",
                (
                    parse_ok, parse_error, attempts, refusal,
                    sender, subject, body, rationale,
                    raw_response, gate_problem, generation_id,
                ),
            )


def update_generation_judgement(
    generation_id: int,
    run_id: str | None,
    verdict: str | None,
    judge_reasoning: str | None,
    evidence: list | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE generations SET "
                "run_id = %s, verdict = %s, judge_reasoning = %s, evidence = %s WHERE id = %s",
                (run_id, verdict, judge_reasoning, _jsonb(evidence), generation_id),
            )


def finish_generation(
    generation_id: int,
    status: str,
    verdict: str | None,
    host_notice: str | None,
    error: str | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE generations SET "
                "status = %s, verdict = COALESCE(%s, verdict), host_notice = %s, "
                "error = %s, finished_at = NOW() WHERE id = %s",
                (status, verdict, host_notice, error, generation_id),
            )


# ------------------------------------------------------------------
# Primitive calls (KLUCZOWA tabela — I/O deterministycznych narzędzi ataku)
# ------------------------------------------------------------------

def log_primitive_call(
    generation_id: int,
    seq: int,
    name: str,
    input_args: dict | None,
    output,
    is_error: bool,
    error: str | None,
    duration_ms: int | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO primitive_calls "
                "(generation_id, seq, name, input, output, is_error, error, finished_at, duration_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)",
                (
                    generation_id, seq, name,
                    _jsonb(input_args), _jsonb(output),
                    is_error, error, duration_ms,
                ),
            )


# ------------------------------------------------------------------
# Agent LLM turns (wnętrze agenta — best-effort, z callbacku)
# ------------------------------------------------------------------

def add_agent_llm_turn(
    generation_id: int,
    seq: int,
    attempt_n: int | None,
    input_messages: list | None,
    output_content: str | None,
    thinking: str | None,
    tool_calls: list | None,
    is_error: bool,
    error: str | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_llm_turns "
                "(generation_id, seq, attempt_n, input_messages, output_content, "
                " thinking, tool_calls, is_error, error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    generation_id, seq, attempt_n,
                    _jsonb(input_messages), output_content,
                    thinking, _jsonb(tool_calls), is_error, error,
                ),
            )


# ------------------------------------------------------------------
# Readery — dla viewera / analiz
# ------------------------------------------------------------------

def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT session_id::text, attack_id, model, objective, start_gen, "
                "       planned_generations, status, final_outcome, started_at, finished_at "
                "FROM sessions WHERE session_id = %s::uuid",
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["session_id", "attack_id", "model", "objective", "start_gen",
                    "planned_generations", "status", "final_outcome", "started_at", "finished_at"]
            return dict(zip(cols, row))


def list_sessions(limit: int = 15) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s.session_id::text, s.objective, s.model, s.status, s.final_outcome, "
                "       s.started_at, s.finished_at, "
                "       (SELECT COUNT(*) FROM generations g WHERE g.session_id = s.session_id) "
                "FROM sessions s ORDER BY s.started_at DESC LIMIT %s",
                (limit,),
            )
            cols = ["session_id", "objective", "model", "status", "final_outcome",
                    "started_at", "finished_at", "generation_count"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_generations(session_id: str) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, generation_n, status, verdict, self_mod_adopted, "
                "       self_mod_rejection_reason, parse_ok, parse_error, attempts, refusal, "
                "       sender, subject, body, rationale, raw_response, gate_problem, "
                "       run_id, judge_reasoning, evidence, host_notice, error, "
                "       started_at, finished_at "
                "FROM generations WHERE session_id = %s::uuid ORDER BY generation_n ASC",
                (session_id,),
            )
            cols = ["id", "generation_n", "status", "verdict", "self_mod_adopted",
                    "self_mod_rejection_reason", "parse_ok", "parse_error", "attempts", "refusal",
                    "sender", "subject", "body", "rationale", "raw_response", "gate_problem",
                    "run_id", "judge_reasoning", "evidence", "host_notice", "error",
                    "started_at", "finished_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_primitive_calls(generation_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, seq, name, input, output, is_error, error, "
                "       started_at, finished_at, duration_ms "
                "FROM primitive_calls WHERE generation_id = %s ORDER BY seq ASC",
                (generation_id,),
            )
            cols = ["id", "seq", "name", "input", "output", "is_error", "error",
                    "started_at", "finished_at", "duration_ms"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_agent_llm_turns(generation_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, seq, attempt_n, input_messages, output_content, thinking, "
                "       tool_calls, is_error, error, created_at "
                "FROM agent_llm_turns WHERE generation_id = %s ORDER BY seq ASC",
                (generation_id,),
            )
            cols = ["id", "seq", "attempt_n", "input_messages", "output_content", "thinking",
                    "tool_calls", "is_error", "error", "created_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
