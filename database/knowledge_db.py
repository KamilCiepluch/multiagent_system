"""
DAL warstwy wiedzy o atakach (baza agent_audit): katalog technik + log prób + agregaty.

Trzy tabele (projekt: docs/knowledge_layer_design.md):
  attack_techniques  — KATALOG (wiedza z literatury; powtarzalny opis)
  attack_attempts    — APPEND-ONLY log prób (niezmienne fakty = historia)
  attack_strategies  — AGREGATY (retrieval-facing; write-through)

Reużywa puli połączeń z `audit_db` (te tabele żyją w tej samej bazie agent_audit).
Zwracane „strategie" mają kształt oczekiwany przez autodan_turbo (Strategy/Definition/
Example/Score), więc retrieval podstawia się pod istniejącą mechanikę bez zmian w attackerze.
"""

from __future__ import annotations

from contextlib import contextmanager

from psycopg2 import pool as pg_pool

from config import settings

# Własna pula na schemat `knowledge` w agent_core (search_path=knowledge w DSN).
_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.knowledge_db_dsn)
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


def _vec(embedding) -> str | None:
    """Formatuje listę floatów na literał pgvector ('[...]'). None → None."""
    if embedding is None:
        return None
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class TechniqueRepository:
    """Katalog technik (reference data). Upsert po unikalnej nazwie (slug)."""

    @staticmethod
    def upsert(name: str, description: str, example: str | None = None,
               attack_class: str | None = None, source: str | None = None) -> int:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO attack_techniques (name, description, example, attack_class, source)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET
                     description = EXCLUDED.description,
                     example     = EXCLUDED.example,
                     attack_class = EXCLUDED.attack_class,
                     source      = EXCLUDED.source,
                     updated_at  = NOW()
                   RETURNING id""",
                (name, description, example, attack_class, source),
            )
            return cur.fetchone()[0]

    @staticmethod
    def get_by_name(name: str) -> dict | None:
        cols = ("id", "name", "description", "example", "attack_class", "source")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, example, attack_class, source "
                "FROM attack_techniques WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

    @staticmethod
    def all() -> list[dict]:
        cols = ("id", "name", "description", "example", "attack_class", "source")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, example, attack_class, source "
                "FROM attack_techniques ORDER BY id"
            )
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    @staticmethod
    def count() -> int:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM attack_techniques")
            return cur.fetchone()[0]


class StrategyRepository:
    """Doświadczenie: append-only log prób + write-through agregaty (retrieval cosine)."""

    @staticmethod
    def record_attempt(*, objective_id: str, vector_id: str, situation_text: str,
                       embedding, payload: str, outcome: str, depth: float,
                       score: float, run_id: str | None = None,
                       technique_id: int | None = None) -> None:
        """Zapisuje jedną próbę: niezmienny fakt + aktualizacja agregatu (gdy znana technika).

        `depth` napędza ranking (mean_score/best_score) — to gęsty sygnał głębokości.
        """
        emb = _vec(embedding)
        succ = 1 if outcome == "ATTACK_SUCCESS" else 0
        p = {
            "tid": technique_id, "obj": objective_id, "vec": vector_id,
            "sit": situation_text, "emb": emb, "payload": payload,
            "outcome": outcome, "depth": depth, "score": score, "run_id": run_id,
            "succ": succ,
        }
        with get_conn() as conn, conn.cursor() as cur:
            # 1) APPEND-ONLY log — niezmienny fakt
            cur.execute(
                """INSERT INTO attack_attempts
                     (technique_id, objective_id, vector_id, situation_text, embedding,
                      payload, outcome, depth, score, run_id)
                   VALUES (%(tid)s, %(obj)s, %(vec)s, %(sit)s, %(emb)s::vector,
                           %(payload)s, %(outcome)s, %(depth)s, %(score)s, %(run_id)s)""",
                p,
            )
            # 2) AGREGAT (write-through) — tylko gdy próba miała przypisaną technikę
            if technique_id is not None:
                cur.execute(
                    """INSERT INTO attack_strategies
                         (technique_id, objective_id, vector_id, situation_centroid,
                          best_example, success_count, attempt_count, mean_score, best_score, last_updated)
                       VALUES (%(tid)s, %(obj)s, %(vec)s, %(emb)s::vector,
                               %(payload)s, %(succ)s, 1, %(depth)s, %(depth)s, NOW())
                       ON CONFLICT (technique_id, objective_id, vector_id) DO UPDATE SET
                         success_count = attack_strategies.success_count + EXCLUDED.success_count,
                         attempt_count = attack_strategies.attempt_count + 1,
                         mean_score = (attack_strategies.mean_score * attack_strategies.attempt_count
                                       + %(depth)s) / (attack_strategies.attempt_count + 1),
                         best_example = CASE WHEN %(depth)s > attack_strategies.best_score
                                        THEN EXCLUDED.best_example ELSE attack_strategies.best_example END,
                         situation_centroid = CASE WHEN %(depth)s > attack_strategies.best_score
                                        THEN EXCLUDED.situation_centroid ELSE attack_strategies.situation_centroid END,
                         best_score = GREATEST(attack_strategies.best_score, %(depth)s),
                         last_updated = NOW()""",
                    p,
                )

    @staticmethod
    def find(objective_id: str, vector_id: str, situation_embedding,
             k: int = 5) -> list[dict]:
        """Top-k strategii dla danego kontekstu, posortowane po podobieństwie stanu obrony
        (cosine) i skuteczności. Kształt zgodny z autodan_turbo (Strategy/Definition/Example/Score)."""
        emb = _vec(situation_embedding)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT t.name, t.description,
                          COALESCE(s.best_example, t.example) AS example, s.mean_score
                   FROM attack_strategies s
                   JOIN attack_techniques t ON t.id = s.technique_id
                   WHERE s.objective_id = %s AND s.vector_id = %s
                     AND s.situation_centroid IS NOT NULL
                   ORDER BY (s.situation_centroid <=> %s::vector) ASC, s.mean_score DESC
                   LIMIT %s""",
                (objective_id, vector_id, emb, k),
            )
            return [
                {"Strategy": n, "Definition": d, "Example": e, "Score": float(m or 0)}
                for (n, d, e, m) in cur.fetchall()
            ]

    @staticmethod
    def catalog_fallback(k: int = 5, attack_class: str | None = None) -> list[dict]:
        """Cold start: techniki z katalogu (jeszcze bez doświadczenia), prior Score=0."""
        with get_conn() as conn, conn.cursor() as cur:
            if attack_class:
                cur.execute(
                    "SELECT name, description, example FROM attack_techniques "
                    "WHERE attack_class = %s ORDER BY id LIMIT %s",
                    (attack_class, k),
                )
            else:
                cur.execute(
                    "SELECT name, description, example FROM attack_techniques ORDER BY id LIMIT %s",
                    (k,),
                )
            return [
                {"Strategy": n, "Definition": d, "Example": e, "Score": 0.0}
                for (n, d, e) in cur.fetchall()
            ]
