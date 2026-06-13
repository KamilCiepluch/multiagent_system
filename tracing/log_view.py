"""
Renderuje przebieg z bazy agent_logs do czytelnego raportu tekstowego,
odwzorowując strukturę idealnego logu:

    1.    Prompt do systemu
    2.    Wywołanie agenta (w kolejności, z zagnieżdżeniem supervisor → agent)
    2.1   Wejście do agenta
    2.2   Wczytane skille
    2.3   Uruchomienie narzędzi (input, output, flaga błędu)
    (+)   Thinking agenta
    (+)   Wynik agenta
    (+)   Zmiany w bazie agent_benchmark wykonane w trakcie przebiegu

Użycie:
    from tracing.log_view import format_run_log
    print(format_run_log(run_id))
"""

from __future__ import annotations

from database import logs_db

_WIDTH = 72


def _hr(char: str = "=") -> str:
    return char * _WIDTH


def _ts(value) -> str:
    return value.strftime("%H:%M:%S") if value else "--:--:--"


def _indent_block(text: str | None, prefix: str, *, empty: str = "(brak)") -> list[str]:
    if text is None or text == "":
        return [f"{prefix}{empty}"]
    return [f"{prefix}{line}" for line in str(text).splitlines() or [""]]


def _format_args(args) -> str:
    if not args:
        return ""
    if not isinstance(args, dict):
        return str(args)
    parts = []
    for k, v in args.items():
        v_str = repr(v) if isinstance(v, str) else str(v)
        parts.append(f"{k}={v_str}")
    return ", ".join(parts)


def _format_invocation(inv: dict, depth: int, show_thinking: bool = False) -> list[str]:
    pad = "    " * depth
    lines: list[str] = []

    status = inv["status"]
    status_tag = "" if status == "completed" else f"  [{status.upper()}]"
    lines.append("")
    lines.append(f"{pad}2. WYWOŁANIE AGENTA [{inv['seq']}] {inv['agent_name'].upper()}"
                 f"  ({_ts(inv['started_at'])}){status_tag}")

    # 2.1 Wejście
    lines.append(f"{pad}   2.1 Wejście do agenta:")
    lines.extend(_indent_block(inv["input"], f"{pad}       "))

    # 2.2 Wczytane skille
    skills = logs_db.get_loaded_skills(inv["id"])
    lines.append(f"{pad}   2.2 Wczytane skille:")
    if not skills:
        lines.append(f"{pad}       (brak)")
    for sk in skills:
        if sk["action"] == "load":
            head = f"load: {sk['skill_name']}"
        else:
            head = "list (dostępne skille)"
        err = "  [BŁĄD]" if sk["is_error"] else ""
        lines.append(f"{pad}       • {head}{err}")
        for line in _indent_block(sk["content"], f"{pad}         │ ", empty="(pusta treść)"):
            lines.append(line)

    # 2.3 Narzędzia
    tools = logs_db.get_tool_calls(inv["id"])
    lines.append(f"{pad}   2.3 Uruchomienie narzędzi:")
    if not tools:
        lines.append(f"{pad}       (brak wywołań narzędzi)")
    for tc in tools:
        is_last = tc is tools[-1]
        connector = "└─" if is_last else "├─"
        cont = "  " if is_last else "│ "
        err = "  [BŁĄD]" if tc["is_error"] else ""
        lines.append(f"{pad}       {connector} {tc['tool_name']}({_format_args(tc['input'])}){err}")
        payload = tc["error"] if tc["is_error"] else tc["output"]
        for j, out_line in enumerate((str(payload) if payload is not None else "").splitlines() or [""]):
            arrow = "→ " if j == 0 else "  "
            lines.append(f"{pad}       {cont}   {arrow}{out_line}")

    # Thinking (opcjonalny — pokazywany tylko gdy show_thinking=True; bywa długi)
    if show_thinking and inv["thinking"]:
        lines.append(f"{pad}   ↳ Thinking:")
        lines.extend(_indent_block(inv["thinking"], f"{pad}       "))
    elif inv["thinking"]:
        lines.append(f"{pad}   ↳ Thinking: (ukryty — użyj --thinking, {len(str(inv['thinking']))} znaków)")

    # Wynik agenta
    lines.append(f"{pad}   ↳ WYNIK:")
    payload = inv["error"] if inv["status"] == "error" else inv["output"]
    lines.extend(_indent_block(payload, f"{pad}       "))

    return lines


def _format_db_changes(run_id: str, agent_by_inv: dict[int, str]) -> list[str]:
    changes = logs_db.get_db_changes(run_id)
    if not changes:
        return []
    lines = ["", _hr("-"), "ZMIANY W BAZIE agent_benchmark (w trakcie przebiegu):"]
    for ch in changes:
        agent = agent_by_inv.get(ch["invocation_id"], "—")
        key = f" {ch['record_key']}" if ch["record_key"] else ""
        lines.append(f"  [{ch['seq']}] {ch['operation']} {ch['table_name']}{key}  (agent: {agent})")
        if ch["old_value"] is not None:
            lines.append(f"        old: {ch['old_value']}")
        if ch["new_value"] is not None:
            lines.append(f"        new: {ch['new_value']}")
    return lines


def format_run_log(run_id: str, show_thinking: bool = False) -> str:
    """Renderuje przebieg do raportu tekstowego. `show_thinking=True` dołącza
    pełny thinking każdego agenta (domyślnie ukryty — bywa bardzo długi)."""
    run = logs_db.get_run(run_id)
    if run is None:
        return f"Brak przebiegu o run_id={run_id} w bazie agent_logs."

    invocations = logs_db.get_invocations(run_id)
    agent_by_inv = {inv["id"]: inv["agent_name"] for inv in invocations}

    # Głębokość zagnieżdżenia z łańcucha parent_id
    depth_by_id: dict[int, int] = {}
    for inv in invocations:
        d, parent = 0, inv["parent_id"]
        while parent is not None and parent in depth_by_id:
            d = depth_by_id[parent] + 1
            break
        depth_by_id[inv["id"]] = d

    started = run["started_at"].strftime("%Y-%m-%d %H:%M:%S") if run["started_at"] else "?"
    short = run_id[:8]

    lines: list[str] = []
    lines.append(_hr("="))
    lines.append(f"RUN  {short}...  |  {started}  |  tryb: {run['mode']}  |  status: {run['status']}")
    lines.append("")
    lines.append("1. PROMPT DO SYSTEMU:")
    lines.extend(_indent_block(run["task"], "   "))
    lines.append(_hr("="))

    for inv in invocations:
        lines.extend(_format_invocation(inv, depth_by_id.get(inv["id"], 0), show_thinking))

    lines.extend(_format_db_changes(run_id, agent_by_inv))

    lines.append("")
    lines.append(_hr("="))
    lines.append(f"WYNIK KOŃCOWY SYSTEMU ({run['status']}):")
    payload = run["error"] if run["status"] == "error" else run["result"]
    lines.extend(_indent_block(payload, "   "))
    lines.append(_hr("="))

    return "\n".join(lines)
