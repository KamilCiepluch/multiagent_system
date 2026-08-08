"""Multi-agent wrapper over an AgentDojo suite: a Supervisor delegates to role-scoped sub-agents.

Design (thin, AgentDojo untouched):
  * The whole MAS is a single `BasePipelineElement` (`MASPipeline`) so it plugs straight into
    AgentDojo's benchmark / scoring — `utility()` and `security()` read the shared `env` exactly as
    for a single agent.
  * The supervisor's LLM only sees three `delegate_to_<role>` tools. Each delegate call runs the
    corresponding sub-agent (a normal AgentPipeline) on the SHARED env with a RESTRICTED runtime
    (only that role's real tools). Sub-agents therefore cannot touch out-of-role tools.
  * Per-agent tool-call trace is stashed in `extra_args["mas_trace"]` — the hook for the Stage-2
    permission / role-violation metrics.
"""
from __future__ import annotations

from collections.abc import Sequence

from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop, ToolsExecutor
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime, make_function
from agentdojo.types import (
    ChatMessage,
    ChatSystemMessage,
    ChatToolResultMessage,
    ChatUserMessage,
    get_text_content_as_str,
    text_content_block_from_string,
)

from agentdojo_mas.roles import ROLES, SUPERVISOR_PROMPT


# --- delegate tool stubs: only their SCHEMA is used (the supervisor's LLM sees them as tools);
#     execution is intercepted by MASPipeline, so the bodies are never actually run. -------------
def delegate_to_email_agent(instruction: str) -> str:
    """Delegate a subtask to the Email Agent (reads/searches/sends email, looks up contacts).

    :param instruction: A clear natural-language instruction describing the email subtask.
    """
    return ""


def delegate_to_calendar_agent(instruction: str) -> str:
    """Delegate a subtask to the Calendar Agent (reads/searches/creates/reschedules/cancels events).

    :param instruction: A clear natural-language instruction describing the calendar subtask.
    """
    return ""


def delegate_to_drive_agent(instruction: str) -> str:
    """Delegate a subtask to the Drive Agent (lists/reads/creates/shares/deletes cloud-drive files).

    :param instruction: A clear natural-language instruction describing the drive subtask.
    """
    return ""


_DELEGATES = {
    "delegate_to_email_agent": "email_agent",
    "delegate_to_calendar_agent": "calendar_agent",
    "delegate_to_drive_agent": "drive_agent",
}


def _assistant_text(messages: Sequence[ChatMessage]) -> str:
    for m in reversed(messages):
        if m["role"] == "assistant":
            txt = get_text_content_as_str(m["content"] or [])
            if txt:
                return txt
    return ""


def _tools_called(messages: Sequence[ChatMessage]) -> list[str]:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.extend(tc.function for tc in m["tool_calls"])
    return out


class MASPipeline(BasePipelineElement):
    """Supervisor + role sub-agents as one pipeline element over a shared environment."""

    def __init__(self, llm: BasePipelineElement, max_delegation_iters: int = 10,
                 name_hint: str = "openai-compatible") -> None:
        self.llm = llm
        self.max_delegation_iters = max_delegation_iters
        # name must contain a MODEL_NAMES key (e.g. the provider) so attacks that address the target
        # model by name (important_instructions) can resolve it from pipeline.name.
        self.name = f"mas_supervisor ({name_hint})"
        self._supervisor_runtime = FunctionsRuntime(
            [make_function(f) for f in (delegate_to_email_agent, delegate_to_calendar_agent, delegate_to_drive_agent)]
        )

    def _run_subagent(self, role: str, instruction: str, full_runtime: FunctionsRuntime, env: Env):
        spec = ROLES[role]
        role_runtime = FunctionsRuntime(
            [full_runtime.functions[n] for n in spec["tools"] if n in full_runtime.functions]
        )
        sub = AgentPipeline(
            [
                SystemMessage(spec["prompt"]),
                InitQuery(),
                self.llm,
                ToolsExecutionLoop([ToolsExecutor(), self.llm]),
            ]
        )
        _, _, env, sub_messages, _ = sub.query(instruction, role_runtime, env, [])
        return env, _assistant_text(sub_messages), _tools_called(sub_messages)

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: Sequence[ChatMessage] = [],
        extra_args: dict = {},
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict]:
        trace: dict[str, list[str]] = {role: [] for role in ROLES}
        msgs: list[ChatMessage] = [
            ChatSystemMessage(role="system", content=[text_content_block_from_string(SUPERVISOR_PROMPT)]),
            ChatUserMessage(role="user", content=[text_content_block_from_string(query)]),
        ]

        for _ in range(self.max_delegation_iters):
            # Supervisor turn: it only sees the delegate tools.
            _, _, env, msgs, extra_args = self.llm.query(query, self._supervisor_runtime, env, msgs, extra_args)
            last = msgs[-1]
            if last["role"] != "assistant" or not last.get("tool_calls"):
                break

            results: list[ChatMessage] = []
            for tc in last["tool_calls"]:
                role = _DELEGATES.get(tc.function)
                if role is None:
                    results.append(
                        ChatToolResultMessage(
                            role="tool",
                            content=[text_content_block_from_string("")],
                            tool_call_id=tc.id,
                            tool_call=tc,
                            error=f"Unknown delegate target '{tc.function}'. Use delegate_to_email_agent/"
                            f"calendar_agent/drive_agent.",
                        )
                    )
                    continue
                instruction = tc.args.get("instruction") or " ".join(str(v) for v in tc.args.values())
                env, reply, tools_used = self._run_subagent(role, instruction, runtime, env)
                trace[role].extend(tools_used)
                results.append(
                    ChatToolResultMessage(
                        role="tool",
                        content=[text_content_block_from_string(reply)],
                        tool_call_id=tc.id,
                        tool_call=tc,
                        error=None,
                    )
                )
            msgs = [*msgs, *results]

        extra_args = {**extra_args, "mas_trace": trace}
        return query, runtime, env, msgs, extra_args


def build_mas_pipeline(llm: BasePipelineElement, name_hint: str = "openai-compatible") -> MASPipeline:
    return MASPipeline(llm, name_hint=name_hint)
