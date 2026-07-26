import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.search_agent import SearchAgent
from agents_benchmark.harness import run_suite
from agents_benchmark.search_agent import cases

SEED = Path(__file__).parent / "seed.sql"

GROUPS = {
    "tools": ("tools", cases.TOOL_CASES),
    "skills": ("skills", cases.SKILL_CASES),
    "roles": ("domain boundaries (whether it refuses role/user questions)", cases.ROLE_CASES),
    "permissions": ("security guardrails (blocked sources)", cases.PERMISSION_CASES),
    "all": ("everything", cases.ALL_CASES),
}


def main():
    p = argparse.ArgumentParser(description="Behavioral benchmark of search_agent")
    p.add_argument("group", choices=list(GROUPS), help="what to test")
    p.add_argument("--only", default=None,
                   help="run only the case with this name (e.g. search_internal)")
    args = p.parse_args()

    label, selected = GROUPS[args.group]
    if args.only:
        selected = [c for c in selected if c.name == args.only]
        if not selected:
            p.error(f"no case named '{args.only}' in group '{args.group}'")

    print(f"Starting the {label} test of search_agent ({len(selected)} cases × paraphrases)...")
    run_suite(SearchAgent, SEED, selected)


if __name__ == "__main__":
    main()
