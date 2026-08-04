"""REPL for the mini system.

Every tool call is printed live as it happens, so you can see what the system actually did —
which agent ran, what it searched for, and what came back — rather than inferring it from the
answer. That is the difference between "it sounds like it refused" and knowing it never looked.

Run:  python -m mini_system.cli
      python -m mini_system.cli --no-log          # do not write to mini_system_logs
      python -m mini_system.cli --quiet           # no live trace, just the answers
      python -m mini_system.cli --no-structured   # search agent answers in plain text

Commands: /new [id]  /reset  /history  /chats  /trace  /log  /exit
"""

from __future__ import annotations

import sys

from mini_system import logs_db
from mini_system.system import MiniAgentSystem

_MAX_PREVIEW = 140


def _shorten(text, limit: int = _MAX_PREVIEW) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _format_args(payload) -> str:
    if not isinstance(payload, dict):
        return _shorten(payload, 60)
    return ", ".join(f"{k}={_shorten(v, 60)!r}" for k, v in payload.items() if v not in ("", None))


def format_event(event: dict) -> list[str]:
    """One trace event as printable lines. Depth reflects agent-inside-agent nesting."""
    pad = "  " * event.get("depth", 1)
    if event["kind"] == "agent":
        return [f"  {pad}[agent] {event['agent']}  <- {_shorten(event['task'], 80)}"]
    if event["kind"] == "tool_start":
        return [f"  {pad}. {event['tool']}({_format_args(event['input'])})"]
    flag = "" if event["status"] == "ok" else f"  !! {event['status']} "
    return [f"  {pad}  ->{flag} {_shorten(event.get('error') or event.get('output'))}"]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    quiet = "--quiet" in sys.argv
    trace_on = not quiet

    def listener(event: dict) -> None:
        if trace_on:
            print("\n".join(format_event(event)))

    system = MiniAgentSystem(log="--no-log" not in sys.argv, listener=listener,
                             structured_search="--no-structured" not in sys.argv)
    where = (
        f"logging to {logs_db.settings.mini_system_logs_name}"
        if system.recorder.enabled else "not logging"
    )
    print(f"Mini agent system — chat with a research tool ({where}).")
    print(f"Chat: {system.conversation_id}.  Live tool trace: {'on' if trace_on else 'off'}.")
    print("Commands: /new [id] /reset /history /chats /trace /log /exit")

    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        if line == "/reset":
            system.reset()
            print(f"[new chat — {system.conversation_id}, history cleared]")
            continue
        if line.startswith("/new"):
            name = line[len("/new"):].strip() or None
            print(f"[new chat — {system.new_chat(name)}]")
            continue
        if line == "/chats":
            try:
                rows = logs_db.list_conversations(10)
            except Exception as exc:
                print(f"[the log database is unreachable: {exc}]")
                continue
            for pk, cid, model, _note, started, turns in rows:
                mark = "*" if pk == system.recorder.conversation_pk else " "
                print(f" {mark} {pk:>5}  {started:%Y-%m-%d %H:%M}  {cid:<24} {turns:>3} turns  {model or '?'}")
            continue
        if line == "/trace":
            trace_on = not trace_on
            print(f"[live tool trace {'on' if trace_on else 'off'}]")
            continue
        if line == "/history":
            for m in system.history():
                print(f"  {type(m).__name__}: {m.content}")
            continue
        if line == "/log":
            pk = system.recorder.conversation_pk
            print("\n".join(logs_db.timeline(pk)) if pk else "[logging is off]")
            continue

        try:
            answer, researched = system.ask(line)
        except Exception as exc:
            # One bad generation must not end the session: the turn is logged with status
            # 'error' and the conversation stays open.
            print(f"[turn failed: {type(exc).__name__}: {exc}]")
            print("[the conversation is intact — try again or rephrase]")
            continue

        calls = system.recorder.turn_calls
        summary = ", ".join(c["tool"] for c in calls) if calls else "no tools"
        print(f"bot> [{summary}] {answer}")


if __name__ == "__main__":
    main()
