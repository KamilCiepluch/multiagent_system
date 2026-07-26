"""MANUAL S0+S1 — the two-stage selector funnel, in isolation.

Dev scratch script: set the params, run/debug directly (F5 / ▶ / breakpoint on `categories = ...` or
`selection = ...`). Attacker-side only — needs the attacker model (proxy + bearer from .env); no
Postgres, no agent system.

It shows the funnel the way a human narrows down: STAGE 0 picks a few attack FAMILIES from the whole
taxonomy, then STAGE 1 sees ONLY the tools inside those families and picks the concrete ones. You see
each stage's menu and choice, so "why did it end up with those tools?" is answered end to end.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

# ==================== PARAMS (edit me) ====================
ATTACKER_MODEL = "gemma4:31b"                 # red-team model S0/S1 run on (meta-attacker)
GOAL           = "Leak the protected secret"
SYSTEM         = "agents_blocks"
TARGET         = "secret_guard"               # email_agent | terminal_agent | search_agent | supervisor | secret_guard
# =========================================================

os.environ["META_ATTACKER_MODEL"] = ATTACKER_MODEL
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")

from attack_forge.categories import DEFAULT_CATEGORY_LIBRARY as LIB
from attack_forge.llm import build_strategist_llm
from attack_forge.menu import render_structures
from attack_forge.strategist import CategorySelector, LLMSelector, _render_target
from attack_forge.system_kb import DEFAULT_MODEL_LIBRARY, DEFAULT_SYSTEM_LIBRARY, build_target_profile


def main():
    target = build_target_profile(DEFAULT_SYSTEM_LIBRARY.get(SYSTEM), TARGET, DEFAULT_MODEL_LIBRARY)
    llm = build_strategist_llm()

    print("=" * 70)
    print(f"GOAL: {GOAL}\nTARGET: {TARGET} on {ATTACKER_MODEL}")
    print("=" * 70)
    print("\n----- WHAT THE FUNNEL SEES (rendered target profile) -----")
    print(_render_target(target))

    # ---- STAGE 0: pick attack families ----
    print("\n----- STAGE 0 menu: ATTACK FAMILIES -----")
    print(LIB.render_families())
    categories = CategorySelector(llm).select_categories(GOAL, target)   # <-- breakpoint (S0)
    print("\n>>> S0 CHOSE:", categories.category_ids)
    print("rationale:\n" + categories.rationale)

    # ---- STAGE 1: pick tools from ONLY the chosen families ----
    menu = render_structures() + "\n\n" + LIB.render_tools(categories.category_ids)
    print("\n----- STAGE 1 menu: TOOLS INSIDE THE CHOSEN FAMILIES -----")
    print(menu)
    selection = LLMSelector(llm).select(GOAL, target, menu=menu)         # <-- breakpoint (S1)
    print("\n>>> S1 CHOSE:")
    print(f"composition : {selection.composition}")
    print(f"tool_names  : {selection.tool_names}")
    print(f"rationale   :\n{selection.rationale}")


if __name__ == "__main__":
    main()
