"""Skill support for the mini system's agents.

Skills are SUPPORTED here — both agents carry `list_skills` / `load_skill` and the same
before-agent gate the task agents use, so a row in `agent_skills` for `chat_agent` or
`search_sim_agent` is the only thing needed to give either of them a procedure. Neither agent has
any yet: the catalog reads as empty and the gate injects nothing, which is support without
content, not a missing capability.

Two deliberate differences from agents/skill_gate.py:

1. An unreachable skills database reads as "no skills" instead of taking the turn down. The
   skills live in the big system's database and the mini system is meant to run on its own. In
   the big system a skill can carry a restriction, so failing open on an outage would be a
   security decision; here there is no security layer to fail open on.
2. The tools are handed to the recorder like every other tool, so a skill call lands in
   `tool_calls` instead of being invisible.
"""

from __future__ import annotations

import sys
import uuid
from typing import Annotated

from langchain.agents.middleware import before_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool as lc_tool
from langgraph.prebuilt import InjectedState

from agents.base_agent import _called_before
from database.db import get_skill as db_get_skill, list_skills as db_list_skills
from mini_system.observability import instrument_tools

_warned = False


def _unavailable(exc: Exception) -> None:
    global _warned
    if not _warned:
        _warned = True
        print(f"[mini_system] the skills database is unreachable — running without skills ({exc})",
              file=sys.stderr)


def catalog(agent_name: str) -> list:
    """The agent's skills — empty when it has none AND when the database is unreachable."""
    try:
        return db_list_skills(agent_name)
    except Exception as exc:
        _unavailable(exc)
        return []


def build_skill_tools(agent_name: str) -> list:
    """`list_skills` / `load_skill` for one agent (same contract as BaseAgent's)."""

    @lc_tool
    def list_skills(
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list, InjectedState("messages")],
    ) -> str:
        """List the available task-handling procedures (skills). Use when the task matches a
        complex scenario or may be governed by a policy."""
        if _called_before(messages, "list_skills", tool_call_id):
            return ("list_skills has already been called in this run. "
                    "Use the earlier list instead of calling it again.")
        skills = catalog(agent_name)
        if not skills:
            return "No skills available."
        return "\n".join(f"{s.name} — {s.description}" for s in skills)

    @lc_tool
    def load_skill(
        name: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list, InjectedState("messages")],
    ) -> str:
        """Load the full content of a skill: steps, tools and constraints."""
        if _called_before(messages, "load_skill", tool_call_id, match_name=name):
            return (f"Skill '{name}' has already been loaded in this run. "
                    "Use the previously returned content instead of calling it again.")
        try:
            skill = db_get_skill(name, agent_name)
        except Exception as exc:
            _unavailable(exc)
            skill = None
        if not skill:
            return f"Skill '{name}' does not exist or is unavailable."
        return skill.content

    return [list_skills, load_skill]


def build_skill_gate(agent_name: str):
    """Injects the skill catalog as a resolved `list_skills` call, because Ollama ignores
    `tool_choice`. No skills → nothing injected, so the agent runs exactly as it does today."""

    @before_agent(name=f"mini_skill_gate[{agent_name}]")
    def skill_gate(state, runtime):
        skills = catalog(agent_name)
        if not skills:
            return None
        call = {"name": "list_skills", "args": {},
                "id": f"skillgate_{uuid.uuid4().hex[:8]}", "type": "tool_call"}
        return {"messages": [
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content="\n".join(f"{s.name} — {s.description}" for s in skills),
                        tool_call_id=call["id"], name="list_skills"),
        ]}

    return skill_gate


class SkillAwareAgent:
    """Mixin wiring the above into an agent: skill tools + gate, both recorder-instrumented.

    Mixed in BEFORE the agent base class, so it also overrides ConversationAgent's decision to
    skip the gate entirely."""

    def __init__(self, llm, all_mcp_tools: dict, *, recorder=None, **kwargs):
        self.recorder = recorder  # must exist before the base __init__ builds the skill tools
        super().__init__(llm, all_mcp_tools, **kwargs)

    def _build_skill_tools(self) -> list:
        tools = {t.name: t for t in build_skill_tools(self.NAME)}
        return list(instrument_tools(tools, self.recorder).values())

    def _build_middleware(self) -> list:
        return [build_skill_gate(self.NAME)]
