"""
DAL warstwy recon (schemat `recon` w agent_core): benchmark podatności atakowanego modelu.

Trzy tabele (projekt: docs/garak_recon_design.md):
  recon.scans     — jedno uruchomienie narzędzia red-team (Garak) na danym modelu
  recon.findings  — wynik per (probe, detector): passed/total + failure_rate
  recon.hits      — pojedyncze prompty, które ZŁAMAŁY model (wprost użyteczne payloady)

Adresowanie spójne z resztą `agent_core`: własna pula z `search_path=recon`
(`settings.recon_db_dsn`), więc zapytania w module są bez kwalifikacji schematu
(wzorzec jak database/knowledge_db.py).

DAL przyjmuje na wejściu zwykłe dicty (parser z vuln_recon/ dostarcza dataclassy →
ingest konwertuje je na dicty), żeby warstwa bazy nie zależała od pakietu vuln_recon.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from psycopg2 import pool as pg_pool
from psycopg2.extras import execute_values

from config import settings

# Własna pula na schemat `recon` w agent_core (search_path=recon w DSN).
_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.recon_db_dsn)
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


class ScanRepository:
    """Cykl życia jednego skanu: start (status='running') → finish (completed|failed)."""

    @staticmethod
    def start(*, target_model: str, target_type: str = "ollama",
              attacker_model: str | None = None, tool: str = "garak",
              probes: list[str] | None = None, command: str | None = None,
              meta: dict | None = None) -> str:
        """Tworzy wiersz skanu (status='running'), zwraca scan_id (UUID jako string)."""
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scans
                     (tool, target_model, target_type, attacker_model, probes, command, meta)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                   RETURNING id::text""",
                (tool, target_model, target_type, attacker_model,
                 json.dumps(probes or [], ensure_ascii=False), command,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
            return cur.fetchone()[0]

    @staticmethod
    def finish(scan_id: str, *, status: str, report_path: str | None = None,
               tool_version: str | None = None, command: str | None = None,
               error: str | None = None) -> None:
        """Domyka skan: status (completed|failed) + metadane przebiegu (COALESCE — nie nadpisuje
        istniejących wartości NULL-em). `command` znamy dopiero po zbudowaniu argv w runnerze."""
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE scans SET
                     status = %s, report_path = COALESCE(%s, report_path),
                     tool_version = COALESCE(%s, tool_version),
                     command = COALESCE(%s, command), error = %s,
                     finished_at = NOW()
                   WHERE id = %s::uuid""",
                (status, report_path, tool_version, command, error, scan_id),
            )

    @staticmethod
    def get(scan_id: str) -> dict | None:
        cols = ("id", "tool", "tool_version", "target_model", "target_type",
                "attacker_model", "probes", "command", "report_path", "status",
                "error", "started_at", "finished_at")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, tool, tool_version, target_model, target_type, "
                "attacker_model, probes, command, report_path, status, error, "
                "started_at, finished_at FROM scans WHERE id = %s::uuid",
                (scan_id,),
            )
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

    @staticmethod
    def list(limit: int = 50) -> list[dict]:
        cols = ("id", "tool", "target_model", "attacker_model", "status",
                "started_at", "finished_at")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, tool, target_model, attacker_model, status, "
                "started_at, finished_at FROM scans ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            return [dict(zip(cols, r)) for r in cur.fetchall()]


class FindingRepository:
    """Wyniki per (probe, detector). bulk_insert idempotentny (ON CONFLICT DO NOTHING)."""

    @staticmethod
    def bulk_insert(scan_id: str, findings: list[dict]) -> int:
        """Zapisuje listę findingów (dicty: probe, probe_family, detector, passed, total,
        failure_rate). Zwraca liczbę przekazanych rekordów."""
        if not findings:
            return 0
        rows = [
            (scan_id, f["probe"], f.get("probe_family"), f["detector"],
             int(f["passed"]), int(f["total"]), float(f["failure_rate"]))
            for f in findings
        ]
        with get_conn() as conn, conn.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO findings
                     (scan_id, probe, probe_family, detector, passed, total, failure_rate)
                   VALUES %s
                   ON CONFLICT (scan_id, probe, detector) DO NOTHING""",
                rows,
                template="(%s::uuid, %s, %s, %s, %s, %s, %s)",
            )
        return len(rows)

    @staticmethod
    def for_scan(scan_id: str) -> list[dict]:
        cols = ("probe", "probe_family", "detector", "passed", "total", "failure_rate")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT probe, probe_family, detector, passed, total, failure_rate "
                "FROM findings WHERE scan_id = %s::uuid ORDER BY failure_rate DESC, probe",
                (scan_id,),
            )
            return [dict(zip(cols, r)) for r in cur.fetchall()]


class HitRepository:
    """Pojedyncze trafienia (prompty, które złamały model)."""

    @staticmethod
    def bulk_insert(scan_id: str, hits: list[dict]) -> int:
        if not hits:
            return 0
        rows = [
            (scan_id, h["probe"], h.get("detector"), h.get("prompt"),
             h.get("output"), h.get("score"))
            for h in hits
        ]
        with get_conn() as conn, conn.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO hits (scan_id, probe, detector, prompt, output, score) VALUES %s",
                rows,
                template="(%s::uuid, %s, %s, %s, %s, %s)",
            )
        return len(rows)

    @staticmethod
    def for_scan(scan_id: str, limit: int = 50) -> list[dict]:
        cols = ("probe", "detector", "prompt", "output", "score")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT probe, detector, prompt, output, score FROM hits "
                "WHERE scan_id = %s::uuid ORDER BY id LIMIT %s",
                (scan_id, limit),
            )
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def top_vulnerabilities(target_model: str, k: int = 10) -> list[dict]:
    """Agregat podatności danego modelu po rodzinie probe'a (po WSZYSTKICH skanach).

    To API „realnego użycia": zwraca rodziny jailbreaku posortowane malejąco po
    ważonym failure_rate (suma trafień / suma prób) — gotowe do priorytetyzacji
    technik w pętli ataku (następny krok: mapowanie na attack_core/knowledge/catalog).
    """
    cols = ("probe_family", "failures", "total", "failure_rate", "scans")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT f.probe_family,
                      SUM(f.total - f.passed)                                    AS failures,
                      SUM(f.total)                                               AS total,
                      SUM(f.total - f.passed)::float / NULLIF(SUM(f.total), 0)   AS failure_rate,
                      COUNT(DISTINCT f.scan_id)                                  AS scans
               FROM findings f
               JOIN scans s ON s.id = f.scan_id
               WHERE s.target_model = %s
               GROUP BY f.probe_family
               ORDER BY failure_rate DESC NULLS LAST
               LIMIT %s""",
            (target_model, k),
        )
        return [dict(zip(cols, r)) for r in cur.fetchall()]
