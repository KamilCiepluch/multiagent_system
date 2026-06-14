"""
Warstwa dostępu do bazy audytowej (agents_audit).

Baza nigdy nie jest resetowana — przechowuje pełną historię ataków.
Operacje są odporne na błędy: audit nie może blokować głównej logiki agentów.
"""

import json
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool

from config import settings

_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.audit_db_dsn)
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


# ------------------------------------------------------------------
# Attack runs
# ------------------------------------------------------------------

def start_attack(
    name: str,
    attack_type: str | None = None,
    description: str | None = None,
) -> str:
    """Tworzy rekord ataku, zwraca attack_id (UUID jako string)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_runs (name, attack_type, description) "
                "VALUES (%s, %s, %s) RETURNING id::text",
                (name, attack_type, description),
            )
            return cur.fetchone()[0]


def finish_attack(attack_id: str, outcome: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attack_runs SET finished_at = NOW(), outcome = %s "
                "WHERE id = %s::uuid",
                (outcome, attack_id),
            )


# ------------------------------------------------------------------
# Invocations
# ------------------------------------------------------------------

def start_invocation(
    attack_id: str,
    invocation_n: int,
    run_id: str,
    task: str | None = None,
) -> int:
    """Tworzy rekord wywołania, zwraca invocation_id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_invocations (attack_id, invocation_n, run_id, task) "
                "VALUES (%s::uuid, %s, %s::uuid, %s) RETURNING id",
                (attack_id, invocation_n, run_id, task),
            )
            return cur.fetchone()[0]


def finish_invocation(invocation_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attack_invocations SET finished_at = NOW() WHERE id = %s",
                (invocation_id,),
            )


def next_invocation_n(attack_id: str) -> int:
    """Zwraca kolejny numer wywołania w ramach ataku (1-based)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(invocation_n), 0) + 1 "
                "FROM attack_invocations WHERE attack_id = %s::uuid",
                (attack_id,),
            )
            return cur.fetchone()[0]


# ------------------------------------------------------------------
# Logs & changes
# ------------------------------------------------------------------

def log_agent_log(
    invocation_id: int,
    agent_name: str | None,
    task: str | None,
    tool_calls: list,
    final_output: str | None,
    attack_success: bool | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_agent_logs "
                "(invocation_id, agent_name, task, tool_calls, final_output, attack_success) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                (
                    invocation_id,
                    agent_name,
                    task,
                    json.dumps(tool_calls, ensure_ascii=False),
                    final_output,
                    attack_success,
                ),
            )


def get_run_logs(run_id: str):
    """Zwraca logi agentów dla danego run_id jako list[AgentLog], posortowane chronologicznie."""
    from database.models import AgentLog
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT aal.id, ai.run_id, aal.agent_name, aal.task,
                       aal.tool_calls, aal.final_output, aal.attack_success, aal.created_at
                FROM attack_agent_logs aal
                JOIN attack_invocations ai ON aal.invocation_id = ai.id
                WHERE ai.run_id = %s::uuid
                ORDER BY aal.created_at ASC
                """,
                (run_id,),
            )
            return [AgentLog.from_row(r) for r in cur.fetchall()]


def log_self_improving_iteration(
    attack_id: str,
    iteration_n: int,
    run_id: str | None,
    payload: str,
    verdict: str,
    evidence: list[str],
    judge_reasoning: str | None,
    mutation_rationale: str | None,
) -> None:
    """Zapisuje jedną rundę pętli self-improving (payload + werdykt + uzasadnienia)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO self_improving_iterations "
                "(attack_id, iteration_n, run_id, payload, verdict, evidence, "
                " judge_reasoning, mutation_rationale) "
                "VALUES (%s::uuid, %s, %s::uuid, %s, %s, %s::jsonb, %s, %s)",
                (
                    attack_id,
                    iteration_n,
                    run_id,
                    payload,
                    verdict,
                    json.dumps(evidence, ensure_ascii=False),
                    judge_reasoning,
                    mutation_rationale,
                ),
            )


def get_self_improving_iterations(attack_id: str):
    """Zwraca historię iteracji danej sesji self-improving (chronologicznie)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT iteration_n, run_id::text, payload, verdict, evidence, "
                "       judge_reasoning, mutation_rationale, created_at "
                "FROM self_improving_iterations "
                "WHERE attack_id = %s::uuid "
                "ORDER BY iteration_n ASC",
                (attack_id,),
            )
            return cur.fetchall()


def start_hyperagent_gateway_call(
    session_id: str,
    generation_n: int | None,
    endpoint: str,
    request: dict | None,
) -> int:
    """Zapisuje wpis o ROZPOCZĘCIU wywołania gatewaya — PRZED jego wykonaniem,
    zwraca id wpisu do uzupełnienia przez finish_hyperagent_gateway_call.

    To jest sedno mechanizmu 'niełamliwych adnotacji': ten wpis istnieje w
    bazie, zanim handler w ogóle zacznie działać — nawet jeśli wykonanie
    zawiesi się albo wywali w dowolny, nieprzewidziany sposób, ślad próby
    już jest trwale zapisany. Agent (zamknięty w osobnym kontenerze, bez
    dostępu do agent_audit) nie ma żadnej drogi, by to ominąć."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO hyperagent_gateway_log (session_id, generation_n, endpoint, request) "
                "VALUES (%s::uuid, %s, %s, %s::jsonb) RETURNING id",
                (
                    session_id,
                    generation_n,
                    endpoint,
                    json.dumps(request, ensure_ascii=False, default=str) if request is not None else None,
                ),
            )
            return cur.fetchone()[0]


def finish_hyperagent_gateway_call(log_id: int, response: dict | None) -> None:
    """Uzupełnia istniejący wpis o wynik wywołania (sukces albo opis błędu —
    zawsze coś: handler jest wołany w try/except, więc ta funkcja jest
    wywoływana bezwarunkowo w finally, nigdy nie zostawiając wpisu 'wiszącego')."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hyperagent_gateway_log SET response = %s::jsonb WHERE id = %s",
                (
                    json.dumps(response, ensure_ascii=False, default=str) if response is not None else None,
                    log_id,
                ),
            )


def get_hyperagent_run_ids(session_id: str, generation_n: int) -> list[str]:
    """Zwraca `run_id` wszystkich UDANYCH wywołań `run_target_task` w obrębie
    jednej generacji — host (`hyperagent.loop`) używa tego, by wiedzieć, KTÓRE
    przebiegi systemu docelowego ocenić (`attack_core.judge.evaluate`).

    Czyta WYŁĄCZNIE z `hyperagent_gateway_log` — bezwarunkowego, logowanego
    PRZED wykonaniem śladu każdego wywołania gatewaya (patrz
    start_/finish_hyperagent_gateway_call). To dokładnie ten sam ślad, który
    widzi sam agent przez /ground_truth — tu tylko przefiltrowany do jednej
    generacji i jednego typu wywołania."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT response -> 'result' ->> 'run_id' "
                "FROM hyperagent_gateway_log "
                "WHERE session_id = %s::uuid AND generation_n = %s "
                "  AND endpoint = %s "
                "  AND response @> '{\"ok\": true}'::jsonb "
                "  AND response -> 'result' ->> 'run_id' IS NOT NULL "
                "ORDER BY created_at ASC",
                (session_id, generation_n, "POST /tools/run_target_task"),
            )
            return [row[0] for row in cur.fetchall()]


def append_hyperagent_history(
    session_id: str,
    generation_n: int,
    entry_type: str,
    content: str,
) -> None:
    """Dopisuje wpis do historii agenta. WYŁĄCZNIE INSERT — nie istnieje
    żadna funkcja UPDATE/DELETE dla tej tabeli (append-only z definicji)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO hyperagent_history_entries "
                "(session_id, generation_n, entry_type, content) "
                "VALUES (%s::uuid, %s, %s, %s)",
                (session_id, generation_n, entry_type, content),
            )


def get_hyperagent_history(session_id: str):
    """Zwraca CAŁĄ historię sesji — agent może to czytać w pełni (read-only)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT generation_n, entry_type, content, created_at "
                "FROM hyperagent_history_entries "
                "WHERE session_id = %s::uuid "
                "ORDER BY created_at ASC",
                (session_id,),
            )
            return cur.fetchall()


def save_hyperagent_generation(
    session_id: str,
    generation_n: int,
    parent_n: int | None,
    code_archive: bytes,
    score: str | None = None,
    evidence: list | None = None,
    run_ids: list[str] | None = None,
    notes: str | None = None,
) -> int:
    """Zapisuje snapshot kodu jednej generacji do archiwum, zwraca jej id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO hyperagent_generations "
                "(session_id, generation_n, parent_n, code_archive, score, "
                " evidence, run_ids, notes) "
                "VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
                "RETURNING id",
                (
                    session_id,
                    generation_n,
                    parent_n,
                    psycopg2.Binary(code_archive),
                    score,
                    json.dumps(evidence or [], ensure_ascii=False),
                    json.dumps(run_ids or [], ensure_ascii=False),
                    notes,
                ),
            )
            return cur.fetchone()[0]


def get_hyperagent_generations(session_id: str):
    """Zwraca metadane wszystkich generacji sesji (bez code_archive — zbyt
    duże do listowania; pobierz pojedynczą generację przez get_hyperagent_generation_code)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, generation_n, parent_n, score, evidence, run_ids, notes, created_at "
                "FROM hyperagent_generations "
                "WHERE session_id = %s::uuid "
                "ORDER BY generation_n ASC",
                (session_id,),
            )
            return cur.fetchall()


def get_hyperagent_generation_code(session_id: str, generation_n: int) -> bytes | None:
    """Zwraca surowy snapshot kodu (tar.gz jako bytes) jednej generacji."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code_archive FROM hyperagent_generations "
                "WHERE session_id = %s::uuid AND generation_n = %s",
                (session_id, generation_n),
            )
            row = cur.fetchone()
            return bytes(row[0]) if row else None


# ------------------------------------------------------------------
# Biblioteka strategii atakującego (attack_strategies, pgvector)
# ------------------------------------------------------------------

def _vec_literal(embedding: list[float]) -> str:
    """Serializuje listę floatów do literału pgvector: '[v1,v2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def upsert_attack_strategy(
    name: str,
    description: str,
    example: str | None,
    objective_id: str | None,
    vector_id: str | None,
    embedding: list[float],
) -> int:
    """Wstawia/aktualizuje strategię (klucz: name). Zwraca jej id.

    Przy konflikcie nazwy NIE zeruje statystyk (success_count/attempt_count/
    mean_score) — odświeża jedynie opis/przykład/embedding/updated_at, żeby
    ponowne odkrycie tej samej techniki kumulowało historię, a nie ją kasowało.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_strategies "
                "(name, description, example, objective_id, vector_id, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector) "
                "ON CONFLICT (name) DO UPDATE SET "
                "  description = EXCLUDED.description, "
                "  example     = EXCLUDED.example, "
                "  embedding   = EXCLUDED.embedding, "
                "  updated_at  = NOW() "
                "RETURNING id",
                (name, description, example, objective_id, vector_id, _vec_literal(embedding)),
            )
            return cur.fetchone()[0]


def retrieve_attack_strategies(embedding: list[float], k: int = 5) -> list[dict]:
    """Zwraca top-k strategii najbliższych `embedding` (cosine), od najbliższej.

    Zwraca listę dictów (name/description/example/objective_id/vector_id/
    mean_score/success_count/attempt_count/distance) — gotowych do wstrzyknięcia
    w prompt hiperagenta.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, description, example, objective_id, vector_id, "
                "       mean_score, success_count, attempt_count, "
                "       embedding <=> %s::vector AS distance "
                "FROM attack_strategies "
                "ORDER BY distance ASC "
                "LIMIT %s",
                (_vec_literal(embedding), k),
            )
            cols = ("name", "description", "example", "objective_id", "vector_id",
                    "mean_score", "success_count", "attempt_count", "distance")
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def record_strategy_outcomes(names: list[str], score: float, success: bool) -> None:
    """Aktualizuje statystyki strategii użytych w jednej generacji.

    `score` ∈ [0,1] (BLOCKED≈0 .. ATTACK_SUCCESS≈1) — kroczący `mean_score`
    liczony PRZED inkrementacją `attempt_count` (SET używa starych wartości).
    """
    if not names:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attack_strategies SET "
                "  mean_score    = (mean_score * attempt_count + %s) / (attempt_count + 1), "
                "  attempt_count = attempt_count + 1, "
                "  success_count = success_count + %s, "
                "  updated_at    = NOW() "
                "WHERE name = ANY(%s)",
                (float(score), 1 if success else 0, list(names)),
            )


def get_attack_strategies():
    """Zwraca całą bibliotekę strategii (do inspekcji), posortowaną po mean_score malejąco."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, description, objective_id, vector_id, "
                "       mean_score, success_count, attempt_count, created_at "
                "FROM attack_strategies "
                "ORDER BY mean_score DESC, success_count DESC"
            )
            return cur.fetchall()


def log_db_change(
    invocation_id: int,
    table_name: str,
    operation: str,
    record_key: str | None,
    old_value: dict | None,
    new_value: dict | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attack_db_changes "
                "(invocation_id, table_name, operation, record_key, old_value, new_value) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)",
                (
                    invocation_id,
                    table_name,
                    operation,
                    record_key,
                    json.dumps(old_value, default=str) if old_value is not None else None,
                    json.dumps(new_value, default=str) if new_value is not None else None,
                ),
            )
