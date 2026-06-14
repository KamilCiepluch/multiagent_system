"""
Podgląd sesji pętli `hyperagent_email` z dedykowanej bazy hyperagent_logs —
chronologiczny widok: co host zrobił w każdej generacji, co trafiło do
deterministycznych prymitywów ataku i co zwróciły, oraz przebieg wnętrza agenta.

Użycie:
    python show_hyperagent_email.py                      # ostatnie sesje
    python show_hyperagent_email.py <session_id>         # pełna sesja
    python show_hyperagent_email.py <session_id> --gen 2 # tylko generacja 2
    python show_hyperagent_email.py <session_id> --turns # + tury LLM agenta
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from database import hyperagent_logs_db as db

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
    "ATTACK_SUCCESS":   green,
    "PARTIAL":          yellow,
    "UNCLEAR":          yellow,
    "BLOCKED":          red,
    "NO_VALID_PAYLOAD": red,
    "ERROR":            red,
}


def _verdict(score: str | None):
    if not score:
        return dim("(brak)")
    return VERDICT_COLOR.get(score, dim)(score)


def _ts(dt: datetime | None) -> str:
    return dt.strftime("%H:%M:%S") if dt else "—"


def _shorten(value: Any, limit: int = 120) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _block(text: str | None, prefix: str = "          ", limit: int = 1500) -> str:
    """Wieloliniowy, wcięty blok — zachowuje nowe linie (czytelny thinking),
    z miękkim limitem długości."""
    if not text:
        return prefix + dim("(brak)")
    if len(text) > limit:
        text = text[:limit] + " […]"
    return "\n".join(prefix + line for line in text.splitlines())


# ─── Listowanie sesji ─────────────────────────────────────────────────────────

def list_sessions(limit: int) -> None:
    rows = db.list_sessions(limit)
    if not rows:
        print("Brak sesji hyperagent_email w bazie hyperagent_logs.")
        return
    SEP = "─" * 78
    print(bold(f"\n  Ostatnie sesje hyperagent_email ({len(rows)})"))
    print(f"  {SEP}")
    print(f"  {'SESSION ID':<36} {'GEN':>4}  {'STATUS':<10} {'WYNIK':<14} CZAS")
    print(f"  {SEP}")
    for s in rows:
        sid = s["session_id"]
        oc = s["final_outcome"] or s["status"] or "—"
        col = VERDICT_COLOR.get(oc, cyan) if oc not in ("running", "—") else cyan
        elapsed = ""
        if s["finished_at"] and s["started_at"]:
            secs = int((s["finished_at"] - s["started_at"]).total_seconds())
            elapsed = f"{secs // 60}m{secs % 60:02d}s"
        print(f"  {cyan(sid):<23} {s['generation_count']:>4}  {(s['status'] or ''):<10} "
              f"{col(oc):<23} {dim(elapsed)}")
    print(f"  {SEP}")
    print(f"  Pełny widok:  python show_hyperagent_email.py <session_id>")


# ─── Widok sesji ─────────────────────────────────────────────────────────────

def show_session(session_id: str, only_gen: int | None, show_turns: bool) -> None:
    session = db.get_session(session_id)
    if session is None:
        print(f"Sesja '{session_id}' nie istnieje w bazie hyperagent_logs.")
        sys.exit(1)

    generations = db.get_generations(session_id)
    if only_gen is not None:
        generations = [g for g in generations if g["generation_n"] == only_gen]

    THICK = "═" * 78
    SEP = "─" * 78
    oc = session["final_outcome"] or session["status"] or "w toku"
    print(f"\n{bold(THICK)}")
    print(f"  {bold('SESJA HYPERAGENT_EMAIL')}")
    print(f"  ID:      {cyan(session['session_id'])}")
    print(f"  Model:   {session['model']}")
    print(f"  Cel:     {_shorten(session['objective'], 90)}")
    print(f"  Wynik:   {VERDICT_COLOR.get(oc, cyan)(oc)}  ({session['status']})")
    print(bold(THICK))

    for g in generations:
        n = g["generation_n"]
        print(f"\n  {bold(SEP)}")
        print(f"  {bold(f'GENERACJA {n}')}  {dim(_ts(g['started_at']))}  "
              f"werdykt: {_verdict(g['verdict'])}  status: {g['status']}")
        print(f"  {SEP}")

        # Self-modyfikacja
        if g["self_mod_adopted"] is False:
            print(f"  {red('self-mod ODRZUCONA → rollback')}: {dim(_shorten(g['self_mod_rejection_reason'], 110))}")
        elif g["self_mod_adopted"] is True:
            print(f"  {dim('self-mod: przyjęta (lub seed)')}")

        # Payload + bramka
        sender = g["sender"] or ""
        print(f"  {bold('Payload:')} sender={sender!r} subject={_shorten(g['subject'], 50)!r} "
              f"parse_ok={g['parse_ok']} attempts={g['attempts']}")
        if g["rationale"]:
            print(f"  {bold('Uzasadnienie agenta:')} {_shorten(g['rationale'], 200)}")
        if g["gate_problem"]:
            print(f"  {red('BRAMKA odrzuciła:')} {_shorten(g['gate_problem'], 110)}")

        # Prymitywy ataku — KLUCZOWE: co trafiło do narzędzia i co zwróciło
        prims = db.get_primitive_calls(g["id"])
        if prims:
            print(f"  {bold('Prymitywy ataku (deterministyczne):')}")
            for p in prims:
                mark = red("✗") if p["is_error"] else green("✓")
                dur = dim(f"({p['duration_ms']}ms)")
                print(f"    {mark} {yellow(p['name'])}  {dur}")
                if p["input"]:
                    print(f"        {dim('→ wejście:')} {_shorten(p['input'], 140)}")
                if p["is_error"]:
                    print(f"        {red('→ błąd:')} {_shorten(p['error'], 140)}")
                else:
                    print(f"        {dim('← wynik: ')} {_shorten(p['output'], 140)}")
        else:
            print(f"  {dim('(brak wywołań prymitywów — np. payload odrzucony przez bramkę)')}")

        # Werdykt sędziego
        if g["run_id"]:
            print(f"  {bold('Ocena:')} run_id={cyan(g['run_id'][:8])}…  {_verdict(g['verdict'])}")
            if g["judge_reasoning"]:
                print(f"        {dim('sędzia:')} {_shorten(g['judge_reasoning'], 120)}")
            if g["evidence"]:
                print(f"        {dim('dowody:')} {_shorten(g['evidence'], 120)}")

        if g["error"]:
            print(f"  {red('WYJĄTEK HOSTA:')} {_shorten(g['error'], 200)}")

        # Tury LLM wnętrza agenta (best-effort) — TU widać, co model MYŚLAŁ.
        if show_turns:
            turns = db.get_agent_llm_turns(g["id"])
            print(f"  {bold('Tury LLM agenta')} ({len(turns)}):")
            for t in turns:
                tc = ", ".join(c.get("name", "?") for c in (t["tool_calls"] or [])) or "—"
                seq_label = dim(f"#{t['seq']}")
                print(f"    {seq_label} tool_calls=[{yellow(tc)}]")
                if t["thinking"]:
                    print(f"      {bold('myślenie:')}")
                    print(cyan(_block(t["thinking"])))
                if t["output_content"]:
                    print(f"      {dim('odpowiedź modelu:')}")
                    print(_block(t["output_content"], limit=800))

    print(f"\n  {bold(THICK)}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Podgląd sesji hyperagent_email z bazy hyperagent_logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("session_id", nargs="?", help="UUID sesji")
    p.add_argument("--gen", type=int, metavar="N", help="Pokaż tylko generację N")
    p.add_argument("--turns", action="store_true", help="Pokaż tury LLM wnętrza agenta")
    p.add_argument("--list", action="store_true", help="Lista ostatnich sesji")
    p.add_argument("--no-color", action="store_true", help="Wyłącz kolory ANSI")
    p.add_argument("--limit", type=int, default=15, help="Ile sesji pokazać (--list)")
    args = p.parse_args()

    if args.no_color:
        global _USE_COLOR
        _USE_COLOR = False

    if not db.is_available():
        print("Baza hyperagent_logs niedostępna. Utwórz ją:\n"
              "  createdb hyperagent_logs && psql -d hyperagent_logs "
              "-f database/schema_hyperagent_logs.sql", file=sys.stderr)
        sys.exit(1)

    if args.list or args.session_id is None:
        list_sessions(limit=args.limit)
        return

    show_session(args.session_id, only_gen=args.gen, show_turns=args.turns)


if __name__ == "__main__":
    main()
