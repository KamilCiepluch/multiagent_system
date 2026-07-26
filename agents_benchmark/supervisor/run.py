import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents_benchmark.harness import run_suite, build_supervisor, supervisor_frame
from agents_benchmark.supervisor import cases

SEED = Path(__file__).parent / "seed.sql"

GROUPS = {
    "routing": ("routing (the right agent for the domain)", cases.ROUTING_CASES),
    "verify": ("role verification before an action", cases.VERIFY_CASES),
    "orchestration": ("multi-agent orchestration", cases.ORCHESTRATION_CASES),
    "synthesis": ("final-answer synthesis", cases.SYNTHESIS_CASES),
    "security": ("the last line of defense", cases.SECURITY_CASES),
    "all": ("everything", cases.ALL_CASES),
}


def main():
    p = argparse.ArgumentParser(description="Behavioral benchmark of the supervisor")
    p.add_argument("group", choices=list(GROUPS), help="what to test")
    p.add_argument("--only", default=None,
                   help="run only the case with this name")
    args = p.parse_args()

    label, selected = GROUPS[args.group]
    if args.only:
        selected = [c for c in selected if c.name == args.only]
        if not selected:
            p.error(f"no case named '{args.only}' in group '{args.group}'")

    print(f"Starting the {label} test of the supervisor ({len(selected)} cases × paraphrases)...")
    run_suite(None, SEED, selected, build_fn=build_supervisor, frame=supervisor_frame)


if __name__ == "__main__":
    main()
