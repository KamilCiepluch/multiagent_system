"""
Warstwa dostępu do bazy jailbreaków (SQLite, jeden plik `jailbreaks.db`).

Dlaczego SQLite, a nie Postgres jak reszta repo: to samodzielny playground do RĘCZNEGO
bawienia się promptem na CZYSTYM modelu. Ma być zero-setup, przenośny (jeden plik do
backupu/skopiowania) i niezależny od infry agentowej. Gdyby kiedyś trzeba było wpiąć to w
agent_core — schemat jest płaski, migracja to zwykły INSERT ... SELECT.

Jeden wiersz = jeden STRZAŁ (jedna tura wysłana do modelu). Każdy wiersz jest w pełni
odtwarzalny: trzyma model, base_url, opcje próbkowania ORAZ pełną listę wiadomości (`messages`),
którą realnie wysłano — więc atak da się powtórzyć 1:1 niezależnie od stanu sesji.

CLI (podgląd/eksport bez wchodzenia do REPL):
    python db.py stats
    python db.py list [--model M] [--verdict V] [--limit N]
    python db.py show <id>
    python db.py export <plik.json|plik.csv>
"""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(__file__).with_name("jailbreaks.db")

# Dozwolone werdykty — świadomie wąskie, żeby statystyki się nie rozjeżdżały literówkami.
VERDICTS = ("unknown", "success", "partial", "refused", "error")

SCHEMA = """
CREATE TABLE IF NOT EXISTS attacks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT    NOT NULL,          -- ISO8601 UTC, moment wysłania
    session         TEXT,                      -- etykieta sesji zabawy (grupowanie)
    conversation_id TEXT,                      -- id rozmowy (multi-turn); zmienia się na /reset
    turn_index      INTEGER DEFAULT 0,         -- nr tury w rozmowie (0 = pierwsza)
    replay_of       INTEGER,                   -- id ataku odtworzonego przez /replay
    provider        TEXT    DEFAULT 'ollama',
    model           TEXT    NOT NULL,          -- np. 'gpt-oss:20b'
    base_url        TEXT,
    options         TEXT,                      -- JSON: temperature, num_ctx, seed, top_p, think...
    system_prompt   TEXT,                      -- system prompt CZYSTEGO modelu (często pusty)
    messages        TEXT,                      -- JSON: PEŁNA lista wiadomości wysłana do modelu
    attack_prompt   TEXT,                      -- ostatnia wiadomość user (wygoda/wyszukiwanie)
    goal            TEXT,                      -- cel: jakie zachowanie chcemy wywołać
    technique       TEXT,                      -- etykieta techniki (DAN, roleplay, prefix-inject...)
    response        TEXT,                      -- pełny output modelu
    reasoning       TEXT,                      -- kanał myślenia (modele rozumujące), jeśli był
    verdict         TEXT    DEFAULT 'unknown', -- unknown|success|partial|refused|error
    tags            TEXT,                      -- JSON: lista tagów
    notes           TEXT,
    latency_ms      INTEGER,
    eval_count      INTEGER,                   -- liczba wygenerowanych tokenów (z Ollamy)
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_attacks_model   ON attacks(model);
CREATE INDEX IF NOT EXISTS idx_attacks_verdict ON attacks(verdict);
CREATE INDEX IF NOT EXISTS idx_attacks_session ON attacks(session);
CREATE INDEX IF NOT EXISTS idx_attacks_ts      ON attacks(ts_utc);
CREATE INDEX IF NOT EXISTS idx_attacks_conv    ON attacks(conversation_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JailbreakDB:
    """Cienki DAL nad SQLite. Nie trzyma połączenia otwartego na stałe — każda operacja
    bierze świeże połączenie (SQLite jest plikowy i tani), więc jest bezpieczny przy
    przerwaniach REPL i łatwy do użycia z zewnętrznych skryptów."""

    def __init__(self, path: str | Path = DB_PATH):
        self.path = Path(path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Połączenie + transakcja + GWARANTOWANE zamknięcie. `with sqlite3.connect(...)`
        commituje, ale NIE zamyka połączenia — bez tego w długiej sesji REPL połączenia
        by się kumulowały i na Windows blokowały plik bazy."""
        conn = self._conn()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        with self._tx() as conn:
            conn.executescript(SCHEMA)

    # ---- zapis -------------------------------------------------------------
    def log_attack(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response: str,
        session: str | None = None,
        conversation_id: str | None = None,
        turn_index: int = 0,
        replay_of: int | None = None,
        provider: str = "ollama",
        base_url: str | None = None,
        options: dict[str, Any] | None = None,
        system_prompt: str | None = None,
        goal: str | None = None,
        technique: str | None = None,
        reasoning: str | None = None,
        verdict: str = "unknown",
        tags: list[str] | None = None,
        notes: str | None = None,
        latency_ms: int | None = None,
        eval_count: int | None = None,
        error: str | None = None,
    ) -> int:
        """Zapisuje jeden strzał i zwraca jego id. Ostatnia wiadomość user trafia też do
        `attack_prompt` (do szybkiego wyszukiwania/podglądu)."""
        attack_prompt = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"), None
        )
        with self._tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO attacks (
                    ts_utc, session, conversation_id, turn_index, replay_of, provider,
                    model, base_url, options, system_prompt, messages, attack_prompt,
                    goal, technique, response, reasoning, verdict, tags, notes,
                    latency_ms, eval_count, error
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _now_iso(), session, conversation_id, turn_index, replay_of, provider,
                    model, base_url, json.dumps(options or {}), system_prompt,
                    json.dumps(messages, ensure_ascii=False), attack_prompt,
                    goal, technique, response, reasoning, verdict,
                    json.dumps(tags or [], ensure_ascii=False), notes,
                    latency_ms, eval_count, error,
                ),
            )
            return int(cur.lastrowid)

    # ---- anotacje ----------------------------------------------------------
    def set_verdict(self, attack_id: int, verdict: str) -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"werdykt musi być jednym z {VERDICTS}, dostałem {verdict!r}")
        with self._tx() as conn:
            conn.execute("UPDATE attacks SET verdict=? WHERE id=?", (verdict, attack_id))

    def add_note(self, attack_id: int, note: str) -> None:
        """Dopisuje notatkę (nie nadpisuje istniejących)."""
        with self._tx() as conn:
            row = conn.execute("SELECT notes FROM attacks WHERE id=?", (attack_id,)).fetchone()
            prev = (row["notes"] + "\n") if row and row["notes"] else ""
            conn.execute("UPDATE attacks SET notes=? WHERE id=?", (prev + note, attack_id))

    def add_tags(self, attack_id: int, new_tags: list[str]) -> None:
        with self._tx() as conn:
            row = conn.execute("SELECT tags FROM attacks WHERE id=?", (attack_id,)).fetchone()
            tags = json.loads(row["tags"]) if row and row["tags"] else []
            for t in new_tags:
                if t and t not in tags:
                    tags.append(t)
            conn.execute(
                "UPDATE attacks SET tags=? WHERE id=?",
                (json.dumps(tags, ensure_ascii=False), attack_id),
            )

    # ---- odczyt ------------------------------------------------------------
    def get(self, attack_id: int) -> dict | None:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM attacks WHERE id=?", (attack_id,)).fetchone()
            return dict(row) if row else None

    def last(self) -> dict | None:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM attacks ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def list(
        self,
        *,
        model: str | None = None,
        verdict: str | None = None,
        session: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        clauses, params = [], []
        if model:
            clauses.append("model=?"); params.append(model)
        if verdict:
            clauses.append("verdict=?"); params.append(verdict)
        if session:
            clauses.append("session=?"); params.append(session)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._tx() as conn:
            rows = conn.execute(
                f"SELECT * FROM attacks{where} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> list[dict]:
        """Zestawienie werdyktów per model (baza do liczenia ASR)."""
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT model,
                       COUNT(*)                                        AS total,
                       SUM(verdict='success')                         AS success,
                       SUM(verdict='partial')                         AS partial,
                       SUM(verdict='refused')                         AS refused,
                       SUM(verdict='unknown')                         AS unknown,
                       SUM(verdict='error')                           AS errors
                FROM attacks GROUP BY model ORDER BY total DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- eksport -----------------------------------------------------------
    def export(self, path: str | Path) -> int:
        """Eksport wszystkiego do JSON lub CSV (po rozszerzeniu). Zwraca liczbę wierszy."""
        path = Path(path)
        with self._tx() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM attacks ORDER BY id").fetchall()]
        if path.suffix.lower() == ".csv":
            if rows:
                with path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
        else:
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(rows)


# --------------------------------------------------------------------------
# Mini-CLI: podgląd i eksport bazy bez wchodzenia do REPL.
# --------------------------------------------------------------------------
def _fmt_row(r: dict) -> str:
    v = r.get("verdict", "?")
    mark = {"success": "BROKEN", "partial": "partial", "refused": "refused",
            "error": "error", "unknown": "unknown"}.get(v, v)
    prompt = (r.get("attack_prompt") or "").replace("\n", " ")
    if len(prompt) > 70:
        prompt = prompt[:67] + "..."
    return f"#{r['id']:<4} {r['ts_utc']}  {r['model']:<16} [{mark:<8}] {prompt}"


def _main() -> None:
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):  # UTF-8, żeby konsola cp1250 nie crashowała na outpucie
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Podgląd/eksport bazy jailbreaków")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    p_list = sub.add_parser("list")
    p_list.add_argument("--model")
    p_list.add_argument("--verdict")
    p_list.add_argument("--session")
    p_list.add_argument("--limit", type=int, default=20)
    p_show = sub.add_parser("show")
    p_show.add_argument("id", type=int)
    p_exp = sub.add_parser("export")
    p_exp.add_argument("path")
    args = ap.parse_args()

    db = JailbreakDB()
    if args.cmd == "stats":
        rows = db.stats()
        if not rows:
            print("(baza pusta)")
            return
        print(f"{'model':<20} {'total':>6} {'success':>8} {'partial':>8} {'refused':>8} {'unknown':>8} {'err':>5}")
        for r in rows:
            print(f"{r['model']:<20} {r['total']:>6} {r['success'] or 0:>8} "
                  f"{r['partial'] or 0:>8} {r['refused'] or 0:>8} {r['unknown'] or 0:>8} {r['errors'] or 0:>5}")
    elif args.cmd == "list":
        rows = db.list(model=args.model, verdict=args.verdict, session=args.session, limit=args.limit)
        for r in reversed(rows):
            print(_fmt_row(r))
        print(f"\n({len(rows)} wierszy)")
    elif args.cmd == "show":
        r = db.get(args.id)
        if not r:
            print(f"brak ataku #{args.id}")
            return
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == "export":
        n = db.export(args.path)
        print(f"wyeksportowano {n} wierszy -> {args.path}")


if __name__ == "__main__":
    _main()
