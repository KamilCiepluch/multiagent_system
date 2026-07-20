"""Live delivery + judging — run an attack_forge vector through the REAL agent graph and score it.

This is the ONE place attack_forge reaches into the running system (graph.workflow + attack_core
runner/injection): it injects the vector's message at an injection point, runs the supervisor
workflow (which logs a per-agent trace to the audit DB under a run_id), reads that trace back, and
scores it with a `JudgeSpec`. Heavy/live — needs Postgres, the agents, and a target model — so all
system imports are function-local, keeping the offline judge engine (`judge.py`) importable on its own.

    OLLAMA_MODEL=qwen3.6:27b META_ATTACKER_MODEL=gemma4:31b \
    python -m attack_forge.live --goal "..." --target email_agent --spec secret_exfil_via_email
"""

from __future__ import annotations

import argparse
import re
import sys

from collections import Counter

from .executor import execute_batch
from .judge import AgentStep, DEFAULT_JUDGE_LIBRARY, JudgeSpec, RunTrace, ToolCall, Verdict, evaluate
from .models import TargetProfile
from .reflect import BatchReflection, JudgedVector, apply_to_target, reflect_batch
from .strategist import StrategistError, make_plan
from .surfaces import SURFACES, Surface, index_for_injection, next_surface
from .system_kb import DEFAULT_MODEL_LIBRARY, DEFAULT_SYSTEM_LIBRARY, build_target_profile

_ROLE_RE = re.compile(r"rola:\s*(\w+)", re.IGNORECASE)  # \w only — avoids capturing trailing ',' etc.


def _role_from_output(agent: str, output: str) -> str | None:
    """Best-effort: the role email_agent propagated downstream, parsed from its rendered output
    ('Użytkownik: <email> (rola: X)'). Used by the judge's role_spoof gate."""
    if agent != "email_agent" or not output:
        return None
    m = _ROLE_RE.search(output)
    return m.group(1) if m else None


def trace_from_run(run_id: str, *, true_role: str | None = None) -> RunTrace:
    """Build a `RunTrace` from the per-agent audit logs of a completed run (ground truth)."""
    from database.audit_db import get_run_logs

    steps: list[AgentStep] = []
    for log in get_run_logs(run_id):
        calls = [ToolCall(tc.get("tool_name", ""), tc.get("input") or {}, str(tc.get("output") or ""))
                 for tc in (log.tool_calls or [])]
        steps.append(AgentStep(agent=log.agent_name, tool_calls=calls, output=log.final_output or "",
                               propagated_role=_role_from_output(log.agent_name, log.final_output or "")))
    return RunTrace(steps=steps, run_id=run_id, true_role=true_role)


def deliver_and_run(payload: str, *, injection_id: str = "email", attack_name: str = "attack_forge") -> str:
    """Inject `payload` at an injection point, run the supervisor workflow, return the run_id.
    Mirrors autodan_turbo.target.AgentsBlocksTarget.respond (reset → apply → invocation → invoke)."""
    import psycopg2

    from config import settings
    from attack_core.injection_points import INJECTION_POINTS
    from attack_core.runner import AttackRunner
    from graph.workflow import build_supervisor_workflow

    injection = INJECTION_POINTS[injection_id]
    runner = AttackRunner()
    workflow = build_supervisor_workflow()
    attack_id = runner.start_attack(attack_name, "prompt_injection")
    runner.reset_main_db()

    conn = psycopg2.connect(dsn=settings.db_dsn)
    try:
        record = injection.apply(conn, payload)
        conn.commit()
    finally:
        conn.close()
    print(f"[live] injected at {injection_id}: {record}")

    with runner.invocation(attack_id, task=injection.task) as run_id:
        try:
            workflow.invoke({"task": injection.task, "run_id": run_id})
        except Exception as e:
            print(f"[live] workflow.invoke error ({type(e).__name__}: {str(e)[:160]}) — partial trace")
    runner.finish_attack(attack_id, "unknown")
    return run_id


def run_and_judge(payload: str, spec, *, injection_id: str = "email", true_role: str = "brak",
                  judge_llm=None) -> tuple[str, RunTrace, Verdict]:
    run_id = deliver_and_run(payload, injection_id=injection_id)
    trace = trace_from_run(run_id, true_role=true_role)
    verdict = evaluate(trace, spec, llm=judge_llm)
    return run_id, trace, verdict


def run_iteration(attacker, *, provider, judge_llm, analyst, goal: str,
                  target: TargetProfile, spec: JudgeSpec, injection: str, true_role: str,
                  batch: int, reflect: bool, top_n: int = 3, label: str = "") -> BatchReflection | None:
    """One full round: plan once (S1->S2) -> fire a batch of `batch` vectors -> deliver+judge each ->
    summary -> (optional) reflection. Returns the reflection (None if skipped or the analyst failed).
    Raises `StrategistError` if planning fails — the caller decides whether that aborts the loop."""
    selection, plan = make_plan(goal, target, attacker)
    vectors = execute_batch(plan, batch, provider=provider)

    print(f"=== PLAN (S1+S2){label} — {batch} vector(s) from ONE recipe ===")
    print(f"selected tools: {selection.tool_names}")
    print(f"applied per vector: {vectors[0].applied_tools}", flush=True)

    judged: list[JudgedVector] = []
    for i, vector in enumerate(vectors, 1):
        print(f"\n{'#' * 64}\n# VECTOR {i}/{batch}\n{'#' * 64}", flush=True)
        print((vector.payload or "")[:700], flush=True)
        run_id, trace, verdict = run_and_judge(vector.payload, spec, injection_id=injection,
                                               true_role=true_role, judge_llm=judge_llm)
        print(f"run {run_id} — agents reached: {[s.agent for s in trace.steps]}")
        print(verdict.summary(), flush=True)
        judged.append(JudgedVector(vector=vector, verdict=verdict, run_id=run_id))

    verdicts = [jv.verdict for jv in judged]
    outcomes = Counter(v.outcome for v in verdicts)
    depths = [v.depth for v in verdicts]
    scores = [v.weighted_score for v in verdicts]
    n = len(verdicts)
    print(f"\n{'=' * 64}\nBATCH SUMMARY — target=qwen, {n} vector(s), spec={spec.id}\n{'=' * 64}")
    print(f"outcomes    : {dict(outcomes)}")
    print(f"ASR (SUCCESS): {outcomes.get('SUCCESS', 0)}/{n}")
    print(f"depth       : max {max(depths)}/{verdicts[0].max_depth}, avg {sum(depths) / n:.1f}")
    print(f"weighted    : max {max(scores):.2f}, avg {sum(scores) / n:.2f}")

    if not reflect:
        return None
    # Post-hoc analysis — a hiccup here must not discard the measured batch above.
    try:
        reflection = reflect_batch(judged, llm=analyst, goal=goal, target=target, top_n=min(top_n, n))
        print(f"\n{'=' * 64}")
        print(reflection.summary(), flush=True)
        return reflection
    except Exception as e:  # noqa: BLE001 — never let analysis crash a completed measurement
        print(f"\n[!] reflection failed ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr)
        return None


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[attr-defined]

    ap = argparse.ArgumentParser(description="attack_forge: build a vector, run it through the real system, judge it")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--system", default="agents_blocks")
    ap.add_argument("--target", default="email_agent", help="agent the vector is framed against")
    ap.add_argument("--spec", default="secret_exfil_via_email", help="judge spec id (data/judges.yaml)")
    ap.add_argument("--injection", default="email", help="injection point id (attack_core.injection_points)")
    ap.add_argument("--true-role", default="brak", help="the sender's actual role (for the role_spoof gate)")
    ap.add_argument("--batch", type=int, default=1, help="N vectors from one recipe, each run + judged")
    ap.add_argument("--no-reflect", action="store_true",
                    help="skip the post-batch reflection (best->attack signal, weakest->defense insight)")
    ap.add_argument("--iterate", type=int, default=1,
                    help="close the loop: re-plan K times, folding each batch's reflection into the "
                         "target intel the selector reads next (short adaptive loop). Default 1 = no re-plan")
    ap.add_argument("--pivot", action="store_true",
                    help="on a pivot/abandon reflection, escalate to the NEXT attack surface "
                         "(email -> skill -> search_result) instead of only enriching in place")
    args = ap.parse_args()

    system = DEFAULT_SYSTEM_LIBRARY.get(args.system)

    # A surface bundles injection point + framed agent + judge spec (switching surface switches all
    # three). With --pivot the loop climbs the SURFACES ladder starting at the one matching
    # --injection; without it, the single surface described by the CLI args.
    if args.pivot:
        cur_idx = index_for_injection(args.injection)
        surface = SURFACES[cur_idx]
    else:
        cur_idx = -1
        surface = Surface(name="cli", injection=args.injection, target=args.target,
                          spec=args.spec, true_role=args.true_role)

    def _resolve(surf: Surface):
        judge_spec = DEFAULT_JUDGE_LIBRARY.get(surf.spec)
        if judge_spec is None:
            ap.error(f"unknown judge spec '{surf.spec}'; choose from {[s.id for s in DEFAULT_JUDGE_LIBRARY.list()]}")
        return judge_spec, build_target_profile(system, surf.target, DEFAULT_MODEL_LIBRARY)

    spec, target = _resolve(surface)

    from .llm import build_strategist_llm, build_target_llm
    from .llm_provider import ModelProvider

    attacker = build_strategist_llm()
    provider = ModelProvider(lambda model, temperature, reasoning:
                             build_strategist_llm(model=model, temperature=temperature, reasoning=reasoning))

    judge_llm = build_target_llm()

    # Close the loop. Each iteration plans -> fires+judges a batch -> reflects. On `refine`, fold the
    # reflection into the target intel the next plan reads (adapt technique WITHIN the surface). On
    # `pivot`/`abandon` with --pivot, escalate to the next surface (a fresh target profile) — the
    # coarse move the reflector keeps asking for when a surface flatly flops. --iterate 1 = single-shot.
    for it in range(1, args.iterate + 1):
        label = f" — iteration {it}/{args.iterate}" + (f" [{surface.name}]" if args.pivot else "")
        try:
            reflection = run_iteration(
                attacker, provider=provider, judge_llm=judge_llm, analyst=attacker, goal=args.goal,
                target=target, spec=spec, injection=surface.injection, true_role=surface.true_role,
                batch=args.batch, reflect=not args.no_reflect, label=label)
        except StrategistError as e:
            print(f"[x] strategist failed: {e.reason}", file=sys.stderr)
            sys.exit(1)

        if reflection is None or it >= args.iterate:
            break

        if args.pivot and reflection.recommendation in ("pivot", "abandon"):
            nxt = next_surface(cur_idx)
            if nxt is None:
                print(f"\n[loop] surface ladder exhausted after '{surface.name}' — stopping.", flush=True)
                break
            cur_idx += 1
            surface = nxt
            spec, target = _resolve(surface)
            print(f"\n[loop] '{reflection.recommendation}' -> pivoting surface to '{surface.name}' "
                  f"(injection={surface.injection}, spec={surface.spec}, target={surface.target})", flush=True)
        elif reflection.recommendation == "abandon":
            print(f"\n[loop] reflection recommends ABANDON — stopping after iteration {it}.", flush=True)
            break
        else:
            target = apply_to_target(target, reflection)
            print(f"\n[loop] folded reflection into target intel for iteration {it + 1}:")
            print(f"       +defense: {reflection.defense_insight[:140]}")
            if reflection.attack_signal:
                print(f"       +vuln   : {reflection.attack_signal[:140]}", flush=True)


if __name__ == "__main__":
    main()
