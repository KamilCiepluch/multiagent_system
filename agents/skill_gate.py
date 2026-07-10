"""
SkillGate — middleware `before_agent`: wymusza `list_skills`, zostawiając wybór `load_skill` agentowi.

Ollama ignoruje `tool_choice`, więc katalog procedur wstrzykujemy jako rozwiązane wywołanie
`list_skills` w historii. Fail-open: agent bez procedur → None.
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware import before_agent

from database.db import list_skills as db_list_skills


def _tool_call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": f"skillgate_{uuid.uuid4().hex[:8]}", "type": "tool_call"}


def make_skill_gate(agent_name: str):
    """Middleware `before_agent` wymuszające `list_skills` dla danego agenta."""

    @before_agent(name=f"skill_gate[{agent_name}]")
    def skill_gate(state, runtime):
        catalog = db_list_skills(agent_name)
        if not catalog:
            return None

        catalog_txt = "\n".join(f"{s.name} — {s.description}" for s in catalog)
        ls_call = _tool_call("list_skills", {})
        injected: list = [
            AIMessage(content="", tool_calls=[ls_call]),
            ToolMessage(content=catalog_txt, tool_call_id=ls_call["id"], name="list_skills"),
        ]
        return {"messages": injected}

    return skill_gate
