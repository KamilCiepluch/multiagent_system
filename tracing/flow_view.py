"""
Liniowy trace przebiegu z bazy agent_logs — END-TO-END, do debugowania.

W odróżnieniu od log_view.py (układ hierarchiczny: osobna sekcja na każde
wywołanie agenta) ten widok czyta się od góry do dołu jak jeden ciągły przebieg:
wywołanie agenta podrzędnego jest WSTAWIANE w miejscu, w którym agent nadrzędny
je zlecił (delegacja → cały przebieg pod-agenta → wartość zwrócona).

Dzięki temu widać dokładnie całą ścieżkę od pierwszego promptu do finalnej
odpowiedzi: co model pomyślał, jaką decyzję podjął, jak wywołał narzędzie, co
zobaczył w wyniku i co pomyślał PO wyniku — z poprawnym zagnieżdżeniem
(supervisor → agent → narzędzie). Idealne do prześledzenia, czy scheduler
deleguje we właściwej kolejności.

Oś czasu w obrębie jednego agenta odtwarzamy ze wspólnego licznika `step`
(reasoning_steps / tool_calls / loaded_skills). Zmiany w bazie agent_benchmark
pokazujemy jako blok przypisany do agenta, który je wywołał.

Użycie:
    from tracing.flow_view import format_run_flow
    print(format_run_flow(run_id))
"""

from __future__ import annotations

from collections import defaultdict

from database import logs_db
from tracing.log_view import _format_args, _format_decided_tools

_WIDTH = 72


def _hr(char: str = "=") -> str:
    return char * _WIDTH


def _ts(value) -> str:
    return value.strftime("%H:%M:%S") if value else "--:--:--"


def _lines(text) -> list[str]:
    """Tekst → lista linii (zawsze min. jedna, pusty tekst → ['(brak)'])."""
    if text is None or str(text) == "":
        return ["(brak)"]
    return str(text).splitlines() or [""]


# ------------------------------------------------------------------
# Oś czasu pojedynczego wywołania agenta (scalenie po `step`)
# ------------------------------------------------------------------

def _build_timeline(inv_id: int) -> list[dict]:
    events: list[dict] = []
    for rs in logs_db.get_reasoning_steps(inv_id):
        events.append({"step": rs["step"], "kind": "reason", "data": rs})
    for sk in logs_db.get_loaded_skills(inv_id):
        events.append({"step": sk["step"], "kind": "skill", "data": sk})
    for tc in logs_db.get_tool_calls(inv_id):
        events.append({"step": tc["step"], "kind": "tool", "data": tc})
    _kind_rank = {"reason": 0, "skill": 1, "tool": 1}
    events.sort(key=lambda e: (e.get("step") or 0, _kind_rank.get(e["kind"], 9)))
    return events


# ------------------------------------------------------------------
# Renderery pojedynczych zdarzeń (bez gutterów — te dokleja rodzic)
# ------------------------------------------------------------------

def _render_reason(rs: dict, show_thinking: bool) -> list[str]:
    lines = [f"• MYŚL [{rs['step']}]"]
    thinking = rs.get("thinking")
    if thinking:
        if show_thinking:
            lines += [f"    {l}" for l in _lines(thinking)]
        else:
            lines.append(f"    (thinking ukryty — użyj --thinking, {len(str(thinking))} znaków)")
    content = rs.get("content")
    if content:
        lines.append("    treść:")
        lines += [f"      {l}" for l in _lines(content)]
    lines.append(f"  → decyzja: {_format_decided_tools(rs.get('decided_tools'))}")
    return lines


def _render_skill(sk: dict) -> list[str]:
    head = f"load: {sk['skill_name']}" if sk["action"] == "load" else "list (dostępne skille)"
    err = "  [BŁĄD]" if sk["is_error"] else ""
    lines = [f"• SKILL {head}{err}  [{sk['step']}]"]
    lines += [f"    │ {l}" for l in _lines(sk["content"])]
    return lines


def _render_tool(tc: dict) -> list[str]:
    err = "  [BŁĄD]" if tc["is_error"] else ""
    lines = [f"• NARZĘDZIE {tc['tool_name']}({_format_args(tc['input'])}){err}  [{tc['step']}]"]
    payload = tc["error"] if tc["is_error"] else tc["output"]
    out = _lines(payload)
    lines.append(f"    └→ {out[0]}")
    lines += [f"       {l}" for l in out[1:]]
    return lines


def _render_dbchange(ch: dict) -> list[str]:
    key = f" {ch['record_key']}" if ch["record_key"] else ""
    lines = [f"• [DB] {ch['operation']} {ch['table_name']}{key}"]
    if ch["old_value"] is not None:
        lines.append(f"    old: {ch['old_value']}")
    if ch["new_value"] is not None:
        lines.append(f"    new: {ch['new_value']}")
    return lines


# ------------------------------------------------------------------
# Rekurencyjny render wywołania agenta z wstawianiem pod-agentów
# ------------------------------------------------------------------

class _Ctx:
    """Stan renderu: kolejka dzieci per (parent_id, agent_name) oraz zmiany DB."""

    def __init__(self, invocations: list[dict], db_changes: list[dict]):
        self.children: dict[int | None, list[dict]] = defaultdict(list)
        for inv in invocations:
            self.children[inv["parent_id"]].append(inv)
        # kolejka dzieci do "skonsumowania" przez dopasowanie do tool-calla
        self._queue: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for inv in invocations:
            if inv["parent_id"] is not None:
                self._queue[(inv["parent_id"], inv["agent_name"])].append(inv)
        self.db_changes: dict[int, list[dict]] = defaultdict(list)
        for ch in db_changes:
            if ch["invocation_id"] is not None:
                self.db_changes[ch["invocation_id"]].append(ch)

    def pop_child(self, parent_id: int, agent_name: str) -> dict | None:
        q = self._queue.get((parent_id, agent_name))
        return q.pop(0) if q else None

    def leftover_children(self, parent_id: int) -> list[dict]:
        """Dzieci nieskonsumowane przez żaden tool-call (defensywnie — nic nie gubimy)."""
        out = []
        for (pid, _name), q in self._queue.items():
            if pid == parent_id and q:
                out.extend(q)
                q.clear()
        return sorted(out, key=lambda i: i["seq"])


def _render_invocation(inv: dict, ctx: _Ctx, show_thinking: bool) -> list[str]:
    status = inv["status"]
    status_tag = "" if status == "completed" else f"  [{status.upper()}]"
    lines = [f"┌─ AGENT {inv['agent_name']}  [#{inv['seq']}]  ({_ts(inv['started_at'])}){status_tag}"]
    body = "│  "

    lines.append(f"{body}IN: {_lines(inv['input'])[0]}")
    lines += [f"{body}    {l}" for l in _lines(inv["input"])[1:]]

    for ev in _build_timeline(inv["id"]):
        kind, data = ev["kind"], ev["data"]
        if kind == "reason":
            lines += [body + l for l in _render_reason(data, show_thinking)]
        elif kind == "skill":
            lines += [body + l for l in _render_skill(data)]
        else:  # tool — może być delegacją do agenta podrzędnego
            child = ctx.pop_child(inv["id"], data["tool_name"])
            if child is not None:
                lines.append(f"{body}• DELEGACJA → {data['tool_name']}:")
                child_lines = _render_invocation(child, ctx, show_thinking)
                lines += [f"{body}    {cl}" for cl in child_lines]
                ret = data["error"] if data["is_error"] else data["output"]
                ret_lines = _lines(ret)
                lines.append(f"{body}    ↩ zwrócono: {ret_lines[0]}")
                lines += [f"{body}      {l}" for l in ret_lines[1:]]
            else:
                lines += [body + l for l in _render_tool(data)]

    for ch in ctx.db_changes.get(inv["id"], []):
        lines += [body + l for l in _render_dbchange(ch)]

    # Dzieci bez dopasowanego tool-calla (nie powinno się zdarzyć — defensywnie)
    for orphan in ctx.leftover_children(inv["id"]):
        lines.append(f"{body}• (pod-agent bez dopasowanego wywołania):")
        lines += [f"{body}    {cl}" for cl in _render_invocation(orphan, ctx, show_thinking)]

    ret = inv["error"] if status == "error" else inv["output"]
    ret_lines = _lines(ret)
    lines.append(f"└─ WYNIK: {ret_lines[0]}")
    lines += [f"   {l}" for l in ret_lines[1:]]
    return lines


# ------------------------------------------------------------------
# Wejście publiczne
# ------------------------------------------------------------------

def format_run_flow(run_id: str, show_thinking: bool = False) -> str:
    run = logs_db.get_run(run_id)
    if run is None:
        return f"Brak przebiegu o run_id={run_id} w bazie agent_logs."

    invocations = logs_db.get_invocations(run_id)
    ctx = _Ctx(invocations, logs_db.get_db_changes(run_id))

    started = run["started_at"].strftime("%Y-%m-%d %H:%M:%S") if run["started_at"] else "?"
    out: list[str] = [
        _hr("="),
        f"TRACE  {run_id[:8]}...  |  {started}  |  tryb: {run['mode']}  |  status: {run['status']}",
        "",
        f"PROMPT: {_lines(run['task'])[0]}",
    ]
    out += [f"        {l}" for l in _lines(run["task"])[1:]]
    out.append(_hr("="))

    # Wywołania najwyższego poziomu (parent_id IS NULL), w kolejności seq.
    roots = sorted(ctx.children.get(None, []), key=lambda i: i["seq"])
    for root in roots:
        out.append("")
        out += _render_invocation(root, ctx, show_thinking)

    out.append("")
    out.append(_hr("="))
    final = run["error"] if run["status"] == "error" else run["result"]
    out.append(f"WYNIK KOŃCOWY SYSTEMU ({run['status']}):")
    out += [f"   {l}" for l in _lines(final)]
    out.append(_hr("="))
    return "\n".join(out)
