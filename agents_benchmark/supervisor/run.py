import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents_benchmark.harness import run_suite, build_supervisor, supervisor_frame
from agents_benchmark.supervisor import cases

SEED = Path(__file__).parent / "seed.sql"

GROUPS = {
    "routing": ("routingu (właściwy agent do domeny)", cases.ROUTING_CASES),
    "verify": ("weryfikacji roli przed akcją", cases.VERIFY_CASES),
    "orchestration": ("orkiestracji wieloagentowej", cases.ORCHESTRATION_CASES),
    "synthesis": ("syntezy finalnej odpowiedzi", cases.SYNTHESIS_CASES),
    "security": ("ostatniej linii obrony", cases.SECURITY_CASES),
    "all": ("wszystkiego", cases.ALL_CASES),
}


def main():
    p = argparse.ArgumentParser(description="Behawioralny benchmark supervisora")
    p.add_argument("group", choices=list(GROUPS), help="co testować")
    p.add_argument("--only", default=None,
                   help="uruchom tylko przypadek o tej nazwie")
    args = p.parse_args()

    label, selected = GROUPS[args.group]
    if args.only:
        selected = [c for c in selected if c.name == args.only]
        if not selected:
            p.error(f"brak przypadku o nazwie '{args.only}' w grupie '{args.group}'")

    print(f"Start testu {label} supervisora ({len(selected)} przypadków × parafrazy)...")
    run_suite(None, SEED, selected, build_fn=build_supervisor, frame=supervisor_frame)


if __name__ == "__main__":
    main()
