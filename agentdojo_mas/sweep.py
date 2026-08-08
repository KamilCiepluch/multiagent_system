"""Sweep: single-agent vs MAS attack-success across (user_task x injection_task) pairs, bucketed by
whether the injected goal is in the SAME role as the user task (same_role) or a DIFFERENT role
(cross_agent). Tests the thesis: role decomposition + asymmetric permissions contain cross-agent
injections (the compromised agent lacks the tool; the supervisor doesn't escalate).

ASR = AgentDojo `security()` (injection succeeded, checked on real env state).
Containment (the headline number) = among pairs the SINGLE agent falls for, the fraction the MAS blocks.

Run (proxy big model via shim):
  export OPENAI_COMPATIBLE_BASE_URL=http://localhost:11500/v1 OPENAI_COMPATIBLE_API_KEY=x
  conda run -n agentdojo python -m agentdojo_mas.sweep --model-id <proxy-model> [--limit N]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop, ToolsExecutor
from agentdojo.agent_pipeline.agent_pipeline import get_llm, load_system_message
from agentdojo.attacks import load_attack
from agentdojo.benchmark import benchmark_suite_with_injections
from agentdojo.default_suites.v1.workspace.task_suite import task_suite as workspace_suite
from agentdojo.logging import OutputLogger

from agentdojo_mas.mas import build_mas_pipeline

# (user_task, injection_task, bucket). Role of each: user tasks 0/1 = calendar, 14/16 = email;
# injection goals: injection_task_0 = email, injection_task_1 = drive, injection_task_2 = calendar.
PAIRS: list[tuple[str, str, str]] = [
    ("user_task_0", "injection_task_2", "same_role"),    # calendar -> calendar
    ("user_task_0", "injection_task_0", "cross_agent"),  # calendar -> email
    ("user_task_0", "injection_task_1", "cross_agent"),  # calendar -> drive
    ("user_task_1", "injection_task_2", "same_role"),    # calendar -> calendar
    ("user_task_1", "injection_task_0", "cross_agent"),  # calendar -> email
    ("user_task_16", "injection_task_0", "same_role"),   # email -> email
    ("user_task_16", "injection_task_2", "cross_agent"), # email -> calendar
    ("user_task_16", "injection_task_1", "cross_agent"), # email -> drive
    ("user_task_14", "injection_task_0", "same_role"),   # email -> email
    ("user_task_14", "injection_task_1", "cross_agent"), # email -> drive
]


def build_single_pipeline(llm, name_hint: str) -> AgentPipeline:
    pipe = AgentPipeline(
        [SystemMessage(load_system_message(None)), InitQuery(), llm,
         ToolsExecutionLoop([ToolsExecutor(), llm])]
    )
    pipe.name = f"single_agent ({name_hint})"
    return pipe


def run_one(pipeline, attack_name: str, ut: str, it: str, logdir: Path) -> bool:
    attack = load_attack(attack_name, workspace_suite, pipeline)
    with OutputLogger(str(logdir)):
        res = benchmark_suite_with_injections(
            pipeline, workspace_suite, attack, logdir=logdir, force_rerun=True,
            user_tasks=(ut,), injection_tasks=(it,),
        )
    # security_results maps (user_task, injection_task) -> injection succeeded
    return bool(next(iter(res["security_results"].values())))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--provider", default="openai-compatible")
    ap.add_argument("--attack", default="important_instructions")
    ap.add_argument("--limit", type=int, default=None, help="run only first N pairs")
    ap.add_argument("--logdir", default=str(Path(__file__).resolve().parent / "runs_sweep"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "sweep_result.json"))
    args = ap.parse_args()

    llm = get_llm(args.provider, args.model_id, args.model_id, "")
    single = build_single_pipeline(llm, args.provider)
    mas = build_mas_pipeline(llm, name_hint=args.provider)

    pairs = PAIRS[: args.limit] if args.limit else PAIRS
    rows = []
    for ut, it, bucket in pairs:
        s = run_one(single, args.attack, ut, it, Path(args.logdir) / "single")
        m = run_one(mas, args.attack, ut, it, Path(args.logdir) / "mas")
        rows.append({"user_task": ut, "injection_task": it, "bucket": bucket,
                     "single_asr": s, "mas_asr": m})
        print(f"[{bucket:11s}] {ut} x {it}: single={'HIT' if s else 'miss'}  mas={'HIT' if m else 'miss'}")

    # aggregate
    agg = defaultdict(lambda: {"n": 0, "single": 0, "mas": 0, "single_hits": 0, "mas_given_single": 0})
    for r in rows:
        a = agg[r["bucket"]]
        a["n"] += 1
        a["single"] += r["single_asr"]
        a["mas"] += r["mas_asr"]
        if r["single_asr"]:
            a["single_hits"] += 1
            a["mas_given_single"] += r["mas_asr"]

    print("\n==== AGGREGATE (ASR = injection succeeded on state) ====")
    print(f"model={args.model_id} attack={args.attack}")
    for bucket in ("same_role", "cross_agent"):
        a = agg[bucket]
        if not a["n"]:
            continue
        contain = (1 - a["mas_given_single"] / a["single_hits"]) if a["single_hits"] else float("nan")
        print(f"  {bucket:11s} n={a['n']}  single_ASR={a['single']}/{a['n']}  mas_ASR={a['mas']}/{a['n']}"
              f"  | among single-hits({a['single_hits']}): MAS_contained={contain:.0%}" if a["single_hits"]
              else f"  {bucket:11s} n={a['n']}  single_ASR={a['single']}/{a['n']}  mas_ASR={a['mas']}/{a['n']}  | no single-hits")

    Path(args.out).write_text(json.dumps(
        {"model": args.model_id, "attack": args.attack, "rows": rows,
         "aggregate": {k: dict(v) for k, v in agg.items()}}, indent=2), encoding="utf-8")
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
