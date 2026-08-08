# agentdojo_mas

Multi-agent extension of [AgentDojo](https://github.com/ethz-spylab/agentdojo): a **supervisor**
delegates to **role-scoped sub-agents** over the *same* stateful environment, so AgentDojo's
deterministic `utility()` / `security()` scoring works unchanged while we add the multi-agent and
role-permission dimensions that AgentDojo (single-agent) and TAMAS (mock tools, name-only success)
each lack.

## Layout
- `roles.py` — role → allowed-tools partition (email / calendar / drive) + role and supervisor prompts.
- `mas.py` — `MASPipeline`, a single `BasePipelineElement`. The supervisor's LLM sees only
  `delegate_to_<role>` tools; each delegation runs a sub-agent (a normal `AgentPipeline`) bound to a
  **restricted runtime** over the **shared env**. Per-agent tool-call trace → `extra_args["mas_trace"]`.
- `run_mas.py` — run a workspace task through the MAS and report utility.

## Setup
AgentDojo is installed editable in a separate env (`conda create -n agentdojo python=3.11`,
`pip install -e <agentdojo clone>`). This package imports the installed `agentdojo`.

## Run (local Ollama)
```
export OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1 OPENAI_COMPATIBLE_API_KEY=x
conda run -n agentdojo python -m agentdojo_mas.run_mas --model-id gpt-oss:20b --user-task user_task_0
```

## Run (big models via the Bearer proxy)
The proxy exposes only native `/api/chat` (no `/v1`) and mangles empty `{}` tool schemas, so start the
local bridge `external/ollama_openai_shim.py` (OpenAI `/v1` → native `/api/chat` + Bearer + `{}`
sanitizer) and point at it:
```
SHIM_PORT=11500 python external/ollama_openai_shim.py            # reads OLLAMA_* from .env
export OPENAI_COMPATIBLE_BASE_URL=http://localhost:11500/v1 OPENAI_COMPATIBLE_API_KEY=x
conda run -n agentdojo python -m agentdojo_mas.run_mas --model-id qwen3.6:35b --user-task user_task_0
```

## Status
- Stage 0 (single-agent sanity on Ollama) and Stage 1 (this MAS wrapper; benign utility verified) done.
- Next: Stage 2 (deterministic role-violation metric on the per-agent trace) and Stage 3 (cross-agent
  injection: malicious email → supervisor delegates a privileged drive action → `security()` on state).
