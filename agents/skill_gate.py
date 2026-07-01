"""
SkillGate — middleware `before_agent`, które WYMUSZA `list_skills`, nie odbierając agentowi autonomii.

Zamysł architektury (rozdzielamy dwie decyzje, które się zlewały):
  • „czy agent w ogóle ZOBACZY katalog procedur?" — źródło zawodności (model zapomina wywołać
    list_skills) → WYMUSZAMY: na starcie wstrzykujemy ROZWIĄZANE `list_skills` z katalogiem.
  • „którą procedurę wczytać / czy w ogóle?" — realny osąd → ZOSTAWIAMY AGENTOWI: sam woła `load_skill`.

Dlaczego wstrzyknięcie, a nie `tool_choice`: Ollama IGNORUJE `tool_choice` (nie da się po stronie
modelu wymusić konkretnego narzędzia — zweryfikowane), więc jedyny deterministyczny sposób na Ollamie
to zarejestrowanie rozwiązanego `list_skills` w historii, tak jakby agent wykonał je sam. `load_skill`
NIE jest tu decydowane ani wstrzykiwane — to autonomiczny wybór agenta na podstawie zobaczonego katalogu.

Fail-open: agent bez katalogu procedur → None (nic nie wstrzykujemy).
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware import before_agent

from database.db import list_skills as db_list_skills


def _tool_call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": f"skillgate_{uuid.uuid4().hex[:8]}", "type": "tool_call"}


def make_skill_gate(agent_name: str):
    """Middleware `before_agent`: WYMUSZA `list_skills` (katalog trafia do kontekstu jako rozwiązane
    wywołanie), a wybór i wczytanie procedury (`load_skill`) zostawia autonomicznemu agentowi."""

    @before_agent(name=f"skill_gate[{agent_name}]")
    def skill_gate(state, runtime):
        catalog = db_list_skills(agent_name)
        if not catalog:
            return None  # agent bez procedur — nic nie wymuszamy

        catalog_txt = "\n".join(f"{s.name} — {s.description}" for s in catalog)
        ls_call = _tool_call("list_skills", {})
        # Wstrzykujemy WYŁĄCZNIE list_skills. Brak load_skill — agent sam zdecyduje, którą
        # procedurę wczytać (i czy w ogóle), widząc katalog powyżej.
        injected: list = [
            AIMessage(content="", tool_calls=[ls_call]),
            ToolMessage(content=catalog_txt, tool_call_id=ls_call["id"], name="list_skills"),
        ]
        return {"messages": injected}

    return skill_gate
