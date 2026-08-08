"""Run the workspace suite through the MAS (supervisor + role sub-agents) and score with AgentDojo.

Benign (no attack) confirms utility() still computes through the MAS. Model via the OpenAI-compatible
provider -> local Ollama /v1, or -> the shim for proxy big models (qwen3.6:35b etc.).

Example (proxy big model via shim):
  export OPENAI_COMPATIBLE_BASE_URL=http://localhost:11500/v1 OPENAI_COMPATIBLE_API_KEY=x
  conda run -n agentdojo python -m agentdojo_mas.run_mas --model-id qwen3.6:35b --user-task user_task_0
"""
from __future__ import annotations

import argparse
from pathlib import Path

from agentdojo.agent_pipeline.agent_pipeline import get_llm
from agentdojo.attacks import load_attack
from agentdojo.benchmark import benchmark_suite_with_injections, benchmark_suite_without_injections
from agentdojo.default_suites.v1.workspace.task_suite import task_suite as workspace_suite
from agentdojo.logging import OutputLogger

from agentdojo_mas.mas import build_mas_pipeline


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", default="qwen3.6:35b")
    ap.add_argument("--provider", default="openai-compatible")
    ap.add_argument("--user-task", action="append", dest="user_tasks", default=None,
                    help="repeatable; default = user_task_0")
    ap.add_argument("--attack", default=None, help="e.g. important_instructions (enables attack mode)")
    ap.add_argument("--injection-task", action="append", dest="injection_tasks", default=None,
                    help="repeatable; only in attack mode")
    ap.add_argument("--logdir", default=str(Path(__file__).resolve().parent / "runs"))
    args = ap.parse_args()

    user_tasks = tuple(args.user_tasks or ("user_task_0",))
    llm = get_llm(args.provider, args.model_id, args.model_id, "")
    mas = build_mas_pipeline(llm, name_hint=args.provider)

    if args.attack is None:
        with OutputLogger(str(args.logdir)):
            results = benchmark_suite_without_injections(
                mas, workspace_suite, logdir=Path(args.logdir), force_rerun=True, user_tasks=user_tasks,
            )
        util = results["utility_results"]
        n = len(util)
        ok = sum(1 for v in util.values() if v)
        print("\n==== MAS RESULT (workspace, benign) ====")
        print(f"model={args.model_id}  tasks={n}  utility={ok}/{n} = {100*ok/max(n,1):.1f}%")
        for (ut, _), v in util.items():
            print(f"  {ut}: {'OK' if v else 'FAIL'}")
        return

    # attack mode: security = injection succeeded (ASR); reads real env state
    attack = load_attack(args.attack, workspace_suite, mas)
    injection_tasks = tuple(args.injection_tasks) if args.injection_tasks else None
    with OutputLogger(str(args.logdir)):
        results = benchmark_suite_with_injections(
            mas, workspace_suite, attack, logdir=Path(args.logdir), force_rerun=True,
            user_tasks=user_tasks, injection_tasks=injection_tasks,
        )
    util = results["utility_results"]
    sec = results["security_results"]
    n = len(sec)
    asr = sum(1 for v in sec.values() if v)
    print("\n==== MAS RESULT (workspace, UNDER ATTACK) ====")
    print(f"model={args.model_id}  attack={args.attack}  pairs={n}")
    print(f"  ASR (injection succeeded) = {asr}/{n} = {100*asr/max(n,1):.1f}%")
    for key in sec:
        ut, it = key
        print(f"  {ut} x {it}: injection={'SUCCEEDED' if sec[key] else 'blocked'} | user_task_utility={'OK' if util.get(key) else 'FAIL'}")


if __name__ == "__main__":
    main()
