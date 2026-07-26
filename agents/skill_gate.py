"""
SkillGate — `before_agent` middleware: enforces `list_skills`, leaving the `load_skill` choice to the agent.

Ollama ignores `tool_choice`, so we inject the procedure catalog as a resolved `list_skills`
call in the history. Fail-open: an agent with no procedures → None.
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware import before_agent

from database.db import list_skills as db_list_skills


def _tool_call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": f"skillgate_{uuid.uuid4().hex[:8]}", "type": "tool_call"}


def make_skill_gate(agent_name: str):
    """`before_agent` middleware enforcing `list_skills` for the given agent."""

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
