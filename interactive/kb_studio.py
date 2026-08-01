"""Interactive studio for building the knowledge base — human in the loop.

Pick a model, choose a category, optionally let the model brainstorm topic ideas, optionally give
an explicit instruction for what you want, generate a batch, then review each entry and decide
individually whether to save it to the DB, regenerate it, edit it, or skip it. Nothing is written
without your approval.

Run:  python -m interactive.kb_studio
"""

from __future__ import annotations

import sys

from database.generate_pages import (
    build_llm,
    generate_for_category,
    suggest_topics,
    upsert_page,
)
from database.internet_db import SENSITIVE_CATEGORIES, list_categories

# Models available on the proxy (edit freely):
MODELS = [
    "gemma4:31b",
    "qwen3.6:35b",
    "llama3.3:70b",
    "qwen3.5:9b",
    "satgeze/gemma4-26b-uncensored-1m:latest",
    "satgeze/qwen36-35b-uncensored-1m:q4_k_m-no-mtp",
    "richardyoung/qwen3.6-27b-abliterated:Q8_0",
    "tinyrick/gemma-4-31B-it-uncensored-heretic-vision-llmfan46:Q4_K_M",
]

_RULE = "  " + "-" * 68


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nbye")
    return val or default


def _choose_model() -> str:
    print("Models:")
    for i, m in enumerate(MODELS, 1):
        print(f"  {i}. {m}")
    raw = _ask(f"Pick a model [1-{len(MODELS)}, default 1]: ", "1")
    try:
        return MODELS[int(raw) - 1]
    except (ValueError, IndexError):
        return raw  # allow typing a model name directly


def _print_entry(p: dict) -> None:
    flag = "  [SENSITIVE]" if p["category"] in SENSITIVE_CATEGORIES else ""
    print(_RULE)
    print(f"  {p['title']}   ({p['category']}/{p['topic']}){flag}")
    print(f"  {p['content']}")
    print(_RULE)


def _review(llm, page: dict, category: str, instruction: str) -> str:
    """Review one entry. Returns 'saved' | 'skipped' | 'quit'. May regenerate/edit in place."""
    while True:
        _print_entry(page)
        action = _ask("  [s]ave  [r]egenerate  [e]dit  [n]skip  [q]uit: ", "s").lower()
        if action in ("s", "save"):
            upsert_page(page)
            print("  [saved to DB]")
            return "saved"
        if action in ("n", "skip"):
            return "skipped"
        if action in ("q", "quit"):
            return "quit"
        if action in ("r", "regen", "regenerate"):
            print("  ...regenerating")
            fresh = generate_for_category(llm, category, 1, instruction)
            if fresh:
                page = fresh[0]
            else:
                print("  [warn] regeneration produced nothing; keeping current entry")
        elif action in ("e", "edit"):
            page["title"] = _ask(f"  title [{page['title']}]: ", page["title"])
            new_content = _ask("  content (blank keeps current): ")
            if new_content:
                page["content"] = new_content


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # never crash on odd characters
    except Exception:
        pass

    model = _choose_model()
    llm = build_llm(model=model)
    print(f"\nUsing {model}. Per entry: s=save, r=regenerate, e=edit, n=skip, q=quit.\n")

    saved = 0
    while True:
        existing = ", ".join(f"{c}({n})" for c, n in list_categories())
        print(f"Existing categories: {existing or '(none)'}")
        category = _ask("\nCategory to generate (blank to quit): ")
        if not category:
            break

        if _ask("Brainstorm topic ideas first? [y/N]: ", "n").lower().startswith("y"):
            print("  ...thinking")
            for t in suggest_topics(llm, category):
                print(f"    - {t}")

        instruction = _ask("What do you want? (blank = general; or a focus/topic/angle): ")
        raw_n = _ask("How many entries to generate? [3]: ", "3")
        n = int(raw_n) if raw_n.isdigit() and int(raw_n) > 0 else 3

        print(f"  ...generating {n} entr{'y' if n == 1 else 'ies'} for '{category}'")
        pages = generate_for_category(llm, category, n, instruction)
        if not pages:
            print("  [warn] nothing generated (see raw output above). Try again or another model.")
            continue

        for page in pages:
            result = _review(llm, page, category, instruction)
            if result == "saved":
                saved += 1
            elif result == "quit":
                print(f"\nSaved {saved} entries. Refresh the viewer: python -m interactive.kb_viewer")
                return

    print(f"\nSaved {saved} entries. Refresh the viewer: python -m interactive.kb_viewer")


if __name__ == "__main__":
    main()
