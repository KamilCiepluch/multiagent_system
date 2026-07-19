"""CLI: strategist → ExecutionPlan (a steps pipeline) → executor → AttackVector(s) [→ real target].

Two strategist variants:
  heuristic   deterministic, no LLM — instant no-strategy baseline (a single literal step)
  two-phase   S1 Selector decides which tools (visible, no text) -> S2 Author emits an ordered
              steps pipeline (tool/input/output). The message is the last step's output.

There is NO automatic fallback: if the two-phase LLM refuses or emits a malformed recipe, the run
fails loudly with a StrategistError (so we can measure how often the model actually fails, instead
of silently shipping a canned vector that looks like a real attack).

The strategist plans ONCE; `--batch N` then runs that same recipe N times. Deterministic steps
repeat identically, but an LLM-backed step (paraphrase, wrap_*) varies per run — so a batch is
several genuinely different attacks from one plan.

    python -m attack_forge.run --goal "Leak the protected secret" --target secret_guard
    python -m attack_forge.run --goal "Leak the protected secret" --target secret_guard \\
        --strategist two-phase --batch 5   # 5 vectors from the same plan, nothing sent anywhere
    python -m attack_forge.run --goal "Leak the protected secret" --target secret_guard \\
        --strategist two-phase --fire   # also delivers the (single) vector to a real target LLM
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .executor import execute_batch
from .models import ExecutionPlan
from .strategist import HeuristicStrategist, LLMAuthor, LLMSelector, StrategistError, TwoPhaseStrategist
from .system_kb import DEFAULT_MODEL_LIBRARY, DEFAULT_SYSTEM_LIBRARY, build_target_profile
from .target import deliver
from .transforms import TRANSFORMS


def _deterministic_only(plan: ExecutionPlan) -> bool:
    """True if every step is a deterministic transform — then a batch of N is N identical vectors
    (nothing varies). An LLM-backed step (paraphrase, wrap_*) is what makes a batch worthwhile."""
    return bool(plan.steps) and all(step.tool in TRANSFORMS for step in plan.steps)


def _build_strategist(kind: str):
    """Returns (strategist, provider): the strategist authors the plan with a single attacker model;
    `provider` builds each LLM-backed step's declared model+params at execution time (`None` for
    heuristic — a deterministic plan needs no model)."""
    if kind == "heuristic":
        return HeuristicStrategist(), None

    from .llm import build_strategist_llm
    from .llm_provider import ModelProvider
    llm = build_strategist_llm()
    provider = ModelProvider(
        lambda model, temperature, reasoning: build_strategist_llm(
            model=model, temperature=temperature, reasoning=reasoning
        )
    )
    return TwoPhaseStrategist(LLMSelector(llm), LLMAuthor(llm)), provider


def main() -> None:
    # Attack payloads carry chars outside the Windows console codepage (zero-width, morse/unicode,
    # homoglyphs) — force UTF-8 so printing them (and JSON to a pipe) never crashes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[attr-defined]

    ap = argparse.ArgumentParser(description="attack_forge: strategist + executor → attack vector")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--system", default="agents_blocks", help="target system (see data/systems.yaml)")
    ap.add_argument("--target", default="secret_guard", help="agent name within the system (see systems.yaml)")
    ap.add_argument("--strategist", choices=["heuristic", "two-phase"], default="heuristic")
    ap.add_argument("--vuln", action="append", default=[], metavar="TEXT",
                    help="append a known vulnerability for the selector to exploit (repeatable)")
    ap.add_argument("--defense", action="append", default=[], metavar="TEXT",
                    help="append a known defense for the selector to avoid (repeatable)")
    ap.add_argument("--batch", type=int, default=1, help="generate N vectors from the same plan (default 1)")
    ap.add_argument("--fire", action="store_true", help="also deliver the vector to a real target LLM")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    system = DEFAULT_SYSTEM_LIBRARY.get(args.system)
    if system is None:
        ap.error(f"unknown system '{args.system}'; choose from {', '.join(s.id for s in DEFAULT_SYSTEM_LIBRARY.list())}")
    try:
        target = build_target_profile(system, args.target, DEFAULT_MODEL_LIBRARY)
    except KeyError:
        ap.error(f"unknown agent '{args.target}' in system '{args.system}'; choose from {', '.join(system.agent_names())}")
    if args.vuln or args.defense:
        target = target.model_copy(update={
            "known_vulnerabilities": [*target.known_vulnerabilities, *args.vuln],
            "known_defenses": [*target.known_defenses, *args.defense],
        })
    if args.batch < 1:
        ap.error("--batch must be >= 1")
    if args.fire and args.batch > 1:
        ap.error("--fire isn't supported together with --batch > 1 yet (batch generation only, this round)")

    strategist, provider = _build_strategist(args.strategist)
    try:
        plan = strategist.plan(args.goal, target)
    except StrategistError as e:
        print(f"[x] strategist failed (no fallback by design): {e.reason}", file=sys.stderr)
        sys.exit(1)

    vectors = execute_batch(plan, args.batch, provider=provider)

    selection = getattr(strategist, "last_selection", None)
    missing_tools = getattr(strategist, "last_missing_tools", [])
    extra_tools = getattr(strategist, "last_extra_tools", [])

    no_tools = selection is not None and not selection.tool_names
    identical_batch = args.batch > 1 and _deterministic_only(plan)

    response = None
    if args.fire:
        from .llm import build_target_llm
        response = deliver(vectors[0], build_target_llm())

    if args.json:
        out: dict[str, Any] = {"target": target.model_dump(), "plan": plan.model_dump(),
                               "vectors": [v.model_dump() for v in vectors]}
        if selection is not None:
            out["selection"] = selection.model_dump()
        if missing_tools:
            out["missing_tools"] = missing_tools
        if extra_tools:
            out["extra_tools"] = extra_tools
        if no_tools:
            out["warning_no_tools"] = True
        if identical_batch:
            out["warning_identical_batch"] = True
        if response is not None:
            out["target_response"] = {"content": response.content, "has_prefill": response.has_prefill}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print(f"=== TARGET: {target.name} @ {args.system}  [model: {target.model or '?'}] ===")
    if target.model_vulnerabilities:
        print(f"model vulns (lean in): {', '.join(target.model_vulnerabilities)}")
    if target.model_resistant_to:
        print(f"model resists (avoid): {', '.join(target.model_resistant_to)}")
    print()

    if no_tools:
        print("[!] S1 selected NO tools — bare plaintext request, no obfuscation or framing "
              "(if the rationale argued for tools, the model failed to fill tool_names)\n")
    if identical_batch:
        print(f"[!] plan has no LLM-backed step (paraphrase/wrap_*) - all {args.batch} batch "
              f"vectors will be identical\n")
    if missing_tools:
        print(f"[!] S1 selected but S2 never used: {missing_tools}\n")
    if extra_tools:
        print(f"[!] S2 used tools S1 didn't select: {extra_tools}\n")
    if selection is not None:
        print("=== TECHNIQUE SELECTION (S1 — Selector) — decided before any attack text existed ===")
        print(selection.model_dump_json(indent=2))
        print()
        print("=== EXECUTION PLAN (S2 — Author: an ordered steps pipeline) ===")
    else:
        print("=== EXECUTION PLAN ===")
    print(plan.model_dump_json(indent=2))

    for i, vector in enumerate(vectors, start=1):
        label = f"ATTACK VECTOR {i}/{len(vectors)}" if len(vectors) > 1 else "ATTACK VECTOR"
        print(f"\n=== {label} (executor) ===")
        print(f"applied tools: {vector.applied_tools or '—'}\n")
        print(vector.preview())

    if response is not None:
        print("\n=== TARGET RESPONSE ===")
        print(response.content)


if __name__ == "__main__":
    main()
