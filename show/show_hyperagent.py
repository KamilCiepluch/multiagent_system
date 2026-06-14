"""
Podgląd sesji hyperagenta — chronologiczny widok tego, co agent robił,
z jakim skutkiem i co sobie zanotował.

Użycie:
    python show_hyperagent.py                        # 10 ostatnich sesji
    python show_hyperagent.py <session_id>           # pełna sesja
    python show_hyperagent.py <session_id> --gen 2   # tylko generacja 2
    python show_hyperagent.py <session_id> --raw     # pełny JSON requestów/odpowiedzi
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

import psycopg2

from config import settings

# ─── Kolory (ANSI, wyłączone gdy nie-TTY lub --no-color) ─────────────────────

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def red(t: str) -> str:    return _c("31;1", t)
def green(t: str) -> str:  return _c("32;1", t)
def yellow(t: str) -> str: return _c("33;1", t)
def cyan(t: str) -> str:   return _c("36;1", t)
def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)


VERDICT_COLOR = {
    "ATTACK_SUCCESS": green,
    "PARTIAL":        yellow,
    "UNCLEAR":        yellow,
    "BLOCKED":        red,
}

ENDPOINT_LABEL = {
    "GET /objective":                   "→ pobierz cel",
    "POST /tools/reset_target":         "→ reset bazy",
    "POST /tools/inject_email":         "→ wstrzyknij email",
    "POST /tools/poison_skill":         "→ zatruć skill",
    "POST /tools/poison_search_result": "→ zatruć wynik wyszukiwania",
    "POST /tools/run_target_task":      "→ odpal system docelowy",
    "POST /llm/chat":                   "→ zapytaj LLM",
    "GET /history":                     "→ czytaj historię",
    "POST /history":                    "→ dopisz do historii",
}


# ─── Połączenie z DB ──────────────────────────────────────────────────────────

def _conn():
    return psycopg2.connect(dsn=settings.audit_db_dsn)


def _q(conn, sql: str, *params) -> list:
    with conn.cursor() as cur:
        cur.execute(sql, params or None)
        return cur.fetchall()


# ─── Listowanie sesji ─────────────────────────────────────────────────────────

def list_sessions(limit: int = 15) -> None:
    with _conn() as conn:
        rows = _q(
            conn,
            """
            SELECT id::text, name, outcome, started_at, finished_at
            FROM attack_runs
            WHERE attack_type = 'hyperagent'
            ORDER BY started_at DESC
            LIMIT %s
            """,
            limit,
        )
    if not rows:
        print("Brak sesji hyperagenta w bazie.")
        return

    SEP = "─" * 78
    print(bold(f"\n  Ostatnie sesje hyperagenta ({len(rows)})"))
    print(f"  {SEP}")
    print(f"  {'SESSION ID':<38} {'CEL / OPIS':<26} {'WYNIK':<14} CZAS")
    print(f"  {SEP}")
    for sid, name, outcome, created_at, finished_at in rows:
        short_id = sid[:8] + "…"
        label = (name or "").replace("hyperagent/", "")[:24]
        oc = outcome or "w toku"
        col = VERDICT_COLOR.get(oc, dim) if oc != "w toku" else cyan
        elapsed = ""
        if finished_at and created_at:
            s = int((finished_at - created_at).total_seconds())
            elapsed = f"{s // 60}m{s % 60:02d}s"
        print(f"  {cyan(short_id):<47} {label:<26} {col(oc):<23} {dim(elapsed)}")
    print(f"  {SEP}")
    print(f"  Pełny id:  python show_hyperagent.py <session_id>")


# ─── Dane sesji ───────────────────────────────────────────────────────────────

def _load_session(conn, session_id: str) -> dict | None:
    rows = _q(
        conn,
        "SELECT id::text, name, outcome, started_at, finished_at "
        "FROM attack_runs WHERE id = %s::uuid",
        session_id,
    )
    if not rows:
        return None
    sid, name, outcome, started_at, finished_at = rows[0]
    return {"id": sid, "name": name, "outcome": outcome,
            "started_at": started_at, "finished_at": finished_at}


def _load_generations(conn, session_id: str) -> list[dict]:
    rows = _q(
        conn,
        "SELECT generation_n, parent_n, score, evidence, run_ids, notes, created_at "
        "FROM hyperagent_generations WHERE session_id = %s::uuid ORDER BY generation_n",
        session_id,
    )
    return [
        {"n": r[0], "parent_n": r[1], "score": r[2],
         "evidence": r[3] or [], "run_ids": r[4] or [],
         "notes": r[5], "created_at": r[6]}
        for r in rows
    ]


def _load_gateway_log(conn, session_id: str, generation_n: int | None = None) -> list[dict]:
    if generation_n is not None:
        rows = _q(
            conn,
            "SELECT generation_n, endpoint, request, response, created_at "
            "FROM hyperagent_gateway_log "
            "WHERE session_id = %s::uuid AND generation_n = %s "
            "ORDER BY created_at",
            session_id, generation_n,
        )
    else:
        rows = _q(
            conn,
            "SELECT generation_n, endpoint, request, response, created_at "
            "FROM hyperagent_gateway_log "
            "WHERE session_id = %s::uuid ORDER BY created_at",
            session_id,
        )
    return [
        {"gen": r[0], "endpoint": r[1],
         "request": r[2], "response": r[3], "ts": r[4]}
        for r in rows
    ]


def _load_history(conn, session_id: str) -> list[dict]:
    rows = _q(
        conn,
        "SELECT generation_n, entry_type, content, created_at "
        "FROM hyperagent_history_entries "
        "WHERE session_id = %s::uuid ORDER BY created_at",
        session_id,
    )
    return [{"gen": r[0], "type": r[1], "content": r[2], "ts": r[3]} for r in rows]


def _load_run_logs(conn, run_id: str) -> list[dict]:
    rows = _q(
        conn,
        """
        SELECT aal.agent_name, aal.task, aal.tool_calls,
               aal.final_output, aal.attack_success, aal.created_at
        FROM attack_agent_logs aal
        JOIN attack_invocations ai ON aal.invocation_id = ai.id
        WHERE ai.run_id = %s::uuid
        ORDER BY aal.created_at
        """,
        run_id,
    )
    return [
        {"agent": r[0], "task": r[1], "tool_calls": r[2] or [],
         "output": r[3], "success": r[4], "ts": r[5]}
        for r in rows
    ]


# ─── Formatowanie ─────────────────────────────────────────────────────────────

def _ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%H:%M:%S")


def _shorten(text: str | None, limit: int = 120) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _fmt_request(endpoint: str, req: Any, raw: bool) -> str:
    """Skrócony podgląd requestu — ważne pola zamiast pełnego JSON."""
    if req is None:
        return ""
    if raw:
        return json.dumps(req, ensure_ascii=False)

    if endpoint == "POST /llm/chat":
        msgs = req.get("messages", [])
        last = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
        if last:
            return f"[{len(msgs)} wiad.] user: {_shorten(last.get('content', ''), 80)}"
        return f"[{len(msgs)} wiad.]"

    if endpoint == "POST /history":
        return f"[{req.get('entry_type', '?')}] {_shorten(req.get('content', ''), 90)}"

    # Dla narzędzi — pokaż argumenty skrócone
    parts = []
    for k, v in req.items():
        if isinstance(v, str):
            parts.append(f"{k}={_shorten(v, 40)!r}")
        else:
            parts.append(f"{k}={v!r}")
    return "  ".join(parts)


def _fmt_response(endpoint: str, resp: Any, raw: bool) -> str:
    if resp is None:
        return dim("(brak odpowiedzi)")
    if raw:
        return json.dumps(resp, ensure_ascii=False)

    ok = resp.get("ok", True)
    if not ok:
        err = resp.get("error") or resp.get("http_status", "?")
        return red(f"BŁĄD: {_shorten(str(err), 100)}")

    result = resp.get("result")
    if result is None:
        return green("ok")

    if endpoint == "POST /tools/run_target_task" and isinstance(result, dict):
        run_id = result.get("run_id", "?")
        route = result.get("route", "")
        return green(f"run_id={run_id[:8]}… route={route}")

    if endpoint == "POST /llm/chat":
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        return dim(_shorten(content, 100))

    if isinstance(result, str):
        return green(_shorten(result, 100))

    return green(_shorten(json.dumps(result, ensure_ascii=False), 100))


def _verdict_label(score: str | None) -> str:
    if score is None:
        return dim("(brak prób run_target_task)")
    col = VERDICT_COLOR.get(score, dim)
    return col(score)


# ─── Widok sesji ─────────────────────────────────────────────────────────────

def show_session(session_id: str, only_gen: int | None = None, raw: bool = False) -> None:
    with _conn() as conn:
        session = _load_session(conn, session_id)
        if session is None:
            print(f"Sesja '{session_id}' nie istnieje w bazie.")
            sys.exit(1)

        generations = _load_generations(conn, session_id)
        gw_log      = _load_gateway_log(conn, session_id, only_gen)
        history     = _load_history(conn, session_id)

        # Grupuj gateway log i historię per generacja
        gw_by_gen: dict[int, list] = {}
        for entry in gw_log:
            gw_by_gen.setdefault(entry["gen"], []).append(entry)

        hist_by_gen: dict[int, list] = {}
        for entry in history:
            hist_by_gen.setdefault(entry["gen"], []).append(entry)

        # Zbierz run_ids ze wszystkich generacji
        all_run_ids: list[tuple[int, str]] = []
        for g in generations:
            for rid in g["run_ids"]:
                all_run_ids.append((g["n"], rid))

        # Załaduj logi agentów dla wszystkich run_ids sesji
        run_logs: dict[str, list] = {}
        for _, rid in all_run_ids:
            run_logs[rid] = _load_run_logs(conn, rid)

    # ── Nagłówek sesji ────────────────────────────────────────────────────────
    THICK = "═" * 78
    SEP   = "─" * 78
    name  = (session["name"] or "").replace("hyperagent/", "")
    oc    = session["outcome"] or "w toku"
    oc_col = VERDICT_COLOR.get(oc, cyan)(oc)

    print(f"\n{bold(THICK)}")
    print(f"  {bold('SESJA HYPERAGENTA')}")
    print(f"  ID:      {cyan(session['id'])}")
    print(f"  Cel:     {name}")
    created = session["started_at"].strftime("%Y-%m-%d %H:%M:%S") if session["started_at"] else "?"
    print(f"  Start:   {created}")
    elapsed = ""
    if session["finished_at"] and session["started_at"]:
        s = int((session["finished_at"] - session["started_at"]).total_seconds())
        elapsed = f"  ({s // 60}m {s % 60:02d}s)"
    print(f"  Wynik:   {oc_col}{elapsed}")
    print(f"  Generacji: {len(generations)}  |  Łącznych run_target_task: {sum(len(g['run_ids']) for g in generations)}")
    print(bold(THICK))

    # ── Per generacja ─────────────────────────────────────────────────────────
    target_gens = generations if only_gen is None else [g for g in generations if g["n"] == only_gen]

    for g in target_gens:
        n       = g["n"]
        parent  = f"rodzic: gen {g['parent_n']}" if g["parent_n"] is not None else "seed"
        score   = _verdict_label(g["score"])
        n_runs  = len(g["run_ids"])
        ts      = g["created_at"].strftime("%H:%M:%S") if g["created_at"] else "?"

        print(f"\n  {bold(SEP)}")
        print(f"  {bold(f'GENERACJA {n}')}  ({parent})  {dim(ts)}")
        print(f"  Werdykt: {score}  |  Przebiegi run_target_task: {n_runs}")
        if g["evidence"]:
            print(f"  Dowody:  {', '.join(str(e) for e in g['evidence'])}")
        if g["notes"]:
            print(f"  Notatki: {dim(g['notes'])}")
        print(f"  {SEP}")

        # ── Log gatewaya tej generacji ────────────────────────────────────────
        gw_entries = gw_by_gen.get(n, [])
        if not gw_entries:
            if n == 0:
                print(f"  {dim('(generacja 0 — seed, brak interakcji z gatewayem)')}")
            else:
                print(f"  {dim('(brak wpisów w hyperagent_gateway_log dla tej generacji)')}")
        else:
            print(f"  {bold('Działania agenta:')}")
            llm_step = 0
            for e in gw_entries:
                ep    = e["endpoint"]
                label = ENDPOINT_LABEL.get(ep, ep)

                # LLM chat — numeruj kroki, nie pokazuj treści (chyba że --raw)
                if ep == "POST /llm/chat":
                    llm_step += 1
                    resp_ok = (e["response"] or {}).get("ok", True)
                    status = green("ok") if resp_ok else red("błąd")
                    print(f"  {dim(_ts(e['ts']))}  {dim(f'[krok LLM #{llm_step}]')} {status}")
                    if raw:
                        req_str  = _fmt_request(ep, e["request"], raw=True)
                        resp_str = _fmt_response(ep, e["response"], raw=True)
                        print(f"           req:  {req_str}")
                        print(f"           resp: {resp_str}")
                    continue

                req_str  = _fmt_request(ep, e["request"], raw)
                resp_str = _fmt_response(ep, e["response"], raw)
                label_col = cyan(label)

                print(f"  {dim(_ts(e['ts']))}  {label_col}")
                if req_str:
                    print(f"           {dim('żądanie:')} {req_str}")
                print(f"           {dim('wynik:  ')} {resp_str}")

        # ── Co system docelowy faktycznie zrobił ──────────────────────────────
        gen_run_ids = g["run_ids"]
        if gen_run_ids:
            print(f"\n  {bold('Co zrobił system docelowy:')}")
            for rid in gen_run_ids:
                logs = run_logs.get(rid, [])
                print(f"  {dim('run_id')} {cyan(rid[:8])}…  ({len(logs)} agentów)")
                for log in logs:
                    success_mark = green(" ✓ ATTACK_SUCCESS") if log["success"] else ""
                    agent_label  = bold(log["agent"] or "?")
                    task_short   = _shorten(log["task"] or "", 60)
                    print(f"    {agent_label}  task={task_short!r}{success_mark}")
                    calls = log["tool_calls"]
                    if isinstance(calls, list):
                        for tc in calls:
                            name  = tc.get("tool") or tc.get("name") or "?"
                            args  = tc.get("args") or tc.get("input") or {}
                            args_str = _shorten(json.dumps(args, ensure_ascii=False), 70)
                            print(f"      {dim('↳')} {yellow(name)}({args_str})")
                    elif calls:
                        print(f"      {dim(str(calls))}")
                    if log["output"]:
                        print(f"      {dim('output:')} {_shorten(log['output'], 80)}")

        # ── Notatki agenta do siebie ──────────────────────────────────────────
        hist_entries = hist_by_gen.get(n, [])
        if hist_entries:
            print(f"\n  {bold('Co agent zanotował:')}")
            for h in hist_entries:
                print(f"  {dim(_ts(h['ts']))}  [{cyan(h['type'])}]  {h['content']}")

    print(f"\n  {bold(THICK)}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Podgląd sesji hyperagenta — chronologiczny widok akcji agenta.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python show_hyperagent.py                        # lista sesji\n"
            "  python show_hyperagent.py <session_id>           # pełna sesja\n"
            "  python show_hyperagent.py <session_id> --gen 2   # tylko gen 2\n"
            "  python show_hyperagent.py <session_id> --raw     # pełny JSON\n"
        ),
    )
    p.add_argument("session_id", nargs="?", help="UUID sesji (lub jego prefiks)")
    p.add_argument("--gen",      type=int, metavar="N",  help="Pokaż tylko generację N")
    p.add_argument("--list",     action="store_true",    help="Lista ostatnich sesji")
    p.add_argument("--raw",      action="store_true",    help="Pełny JSON requestów/odpowiedzi")
    p.add_argument("--no-color", action="store_true",    help="Wyłącz kolory ANSI")
    p.add_argument("--limit",    type=int, default=15,   help="Ile sesji pokazać (--list, domyślnie 15)")
    args = p.parse_args()

    if args.no_color:
        global _USE_COLOR
        _USE_COLOR = False

    if args.list or args.session_id is None:
        list_sessions(limit=args.limit)
        return

    # Rozwiń prefiks session_id do pełnego UUID
    session_id = args.session_id
    if len(session_id) < 36:
        with _conn() as conn:
            rows = _q(
                conn,
                "SELECT id::text FROM attack_runs "
                "WHERE attack_type = 'hyperagent' AND id::text LIKE %s "
                "ORDER BY started_at DESC LIMIT 2",
                session_id + "%",
            )
        if not rows:
            print(f"Brak sesji z prefiksem '{session_id}'.")
            sys.exit(1)
        if len(rows) > 1:
            print(f"Prefiks '{session_id}' pasuje do więcej niż jednej sesji:")
            for r in rows:
                print(f"  {r[0]}")
            sys.exit(1)
        session_id = rows[0][0]

    show_session(session_id, only_gen=args.gen, raw=args.raw)


if __name__ == "__main__":
    main()
