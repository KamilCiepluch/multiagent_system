import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.search_agent import SearchAgent
from agents_benchmark.harness import run_suite
from agents_benchmark.search_agent import cases

SEED = Path(__file__).parent / "seed.sql"

GROUPS = {
    "tools": ("narzędzi", cases.TOOL_CASES),
    "skills": ("skilli", cases.SKILL_CASES),
    "roles": ("granic domeny (czy odmawia pytań o role/użytkowników)", cases.ROLE_CASES),
    "permissions": ("guardraili bezpieczeństwa (zablokowane źródła)", cases.PERMISSION_CASES),
    "all": ("wszystkiego", cases.ALL_CASES),
}


def main():
    p = argparse.ArgumentParser(description="Behawioralny benchmark search_agent")
    p.add_argument("group", choices=list(GROUPS), help="co testować")
    p.add_argument("--only", default=None,
                   help="uruchom tylko przypadek o tej nazwie (np. search_internal)")
    args = p.parse_args()

    label, selected = GROUPS[args.group]
    if args.only:
        selected = [c for c in selected if c.name == args.only]
        if not selected:
            p.error(f"brak przypadku o nazwie '{args.only}' w grupie '{args.group}'")

    print(f"Start testu {label} search_agent ({len(selected)} przypadków × parafrazy)...")
    run_suite(SearchAgent, SEED, selected)


if __name__ == "__main__":
    main()
