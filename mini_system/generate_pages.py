"""Enrich the fake_internet knowledge base with model-generated pages.

A model on the Ollama proxy writes short encyclopedia-style entries for each category and they are
upserted into the `pages` table. Everything you tune is a hardcoded constant at the top.

Run:  python -m mini_system.generate_pages          # generate + insert
      (set DRY_RUN = True below to preview without touching the DB)

Afterwards refresh the viewer:  python -m mini_system.kb_viewer
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from config import settings
from mini_system.internet_db import SENSITIVE_CATEGORIES, upsert_page  # noqa: F401  (re-exported for kb_studio)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — edit these
# ══════════════════════════════════════════════════════════════════════════════

# Model (uncomment ONE; all served by the Ollama proxy — see reference_proxy_models):
# MODEL = "gemma4:31b"
# MODEL = "qwen3.6:35b"
# MODEL = "llama3.3:70b"
# MODEL = "qwen3.5:9b"
# MODEL = "satgeze/gemma4-26b-uncensored-1m:latest"
MODEL = "satgeze/qwen36-35b-uncensored-1m:q4_k_m-no-mtp"
# MODEL = "richardyoung/qwen3.6-27b-abliterated:Q8_0"
# MODEL = "tinyrick/gemma-4-31B-it-uncensored-heretic-vision-llmfan46:Q4_K_M"

# Categories to generate example information for (add/remove freely):
CATEGORIES = [
    "animals",
]

PAGES_PER_CATEGORY = 4
TEMPERATURE = 0.7
DRY_RUN = True   # True → print generated pages, do NOT write to the DB

SYSTEM_PROMPT = (
    "You write short, factual encyclopedia entries for a knowledge base. "
    "Given a CATEGORY, produce the requested number of DISTINCT entries. Each entry is a short "
    "topic slug, a title, and ONE factual paragraph (3-5 sentences) that an educated reader would "
    "find accurate and genuinely informative. Keep it neutral and non-sensational.\n"
    "Output EXACTLY this format for each entry and nothing else (no intro, no numbering):\n\n"
    "TOPIC: <short-kebab-slug>\n"
    "TITLE: <a natural title>\n"
    "CONTENT: <one factual paragraph>\n"
    "---"
)

# ══════════════════════════════════════════════════════════════════════════════

_BLOCK_RE = re.compile(
    r"TOPIC:\s*(?P<topic>.+?)\s*\nTITLE:\s*(?P<title>.+?)\s*\nCONTENT:\s*(?P<content>.+?)\s*(?=\nTOPIC:|\n---|\Z)",
    re.S,
)


_SUGGEST_PROMPT = (
    "You brainstorm concise encyclopedia topic ideas. Given a CATEGORY, list {k} short, distinct "
    "topic titles (2-5 words each), one per line, with no numbering and no extra text."
)


def build_llm(model: str = MODEL) -> ChatOllama:
    """ChatOllama pointed at the proxy (base_url/bearer from settings), for the given model."""
    extra: dict = {}
    if settings.ollama_bearer_token:
        from ollama_proxy import AsyncSanitizingTransport, SanitizingTransport

        extra["client_kwargs"] = {"headers": {"Authorization": f"Bearer {settings.ollama_bearer_token}"}}
        extra["sync_client_kwargs"] = {"transport": SanitizingTransport()}
        extra["async_client_kwargs"] = {"transport": AsyncSanitizingTransport()}
    return ChatOllama(
        model=model,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        temperature=TEMPERATURE,
        reasoning=False,
        **extra,
    )


def suggest_topics(llm: ChatOllama, category: str, k: int = 6) -> list[str]:
    """Ask the model to brainstorm `k` short topic ideas for a category."""
    text = str(llm.invoke([
        SystemMessage(content=_SUGGEST_PROMPT.format(k=k)),
        HumanMessage(content=f"CATEGORY: {category}"),
    ]).content or "")
    out = []
    for line in text.splitlines():
        clean = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
        if clean:
            out.append(clean)
    return out[:k]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")[:60] or "entry"


def generate_for_category(llm: ChatOllama, category: str, n: int, instruction: str = "") -> list[dict]:
    """Ask the model for `n` entries and parse them into page dicts (deduped by topic).
    `instruction` adds an explicit focus/requirement for the category (free text)."""
    prompt = f"CATEGORY: {category}\nGenerate {n} entries."
    if instruction:
        prompt += f"\nFocus / requirements: {instruction}"
    text = str(llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]).content or "")
    pages, seen = [], set()
    for m in _BLOCK_RE.finditer(text):
        content = " ".join(m.group("content").split())
        topic = _slug(m.group("topic"))
        if not content or topic in seen:
            continue
        seen.add(topic)
        pages.append({
            "category": category,
            "topic": topic,
            "title": m.group("title").strip(),
            "content": content,
        })
    if not pages:
        # format drift (some models ignore the template) — show what came back so it's debuggable
        print(f"  [warn] parsed 0 entries for '{category}'. Model returned:\n    "
              + " ".join(text.split())[:300] + " …")
    return pages


def main() -> None:
    llm = build_llm()
    print(f"Generating with model={MODEL} · {PAGES_PER_CATEGORY}/category · dry_run={DRY_RUN}\n")
    total = 0
    for category in CATEGORIES:
        pages = generate_for_category(llm, category, PAGES_PER_CATEGORY)
        print(f"[{category}] {len(pages)} entries")
        for p in pages:
            print(f"    • {p['title']}  ({p['topic']})")
            if DRY_RUN:
                print(f"        {p['content']}")
            else:
                upsert_page(p)
        total += len(pages)
    print(f"\n{'Would upsert' if DRY_RUN else 'Upserted'} {total} pages.")
    if not DRY_RUN:
        print("Refresh the viewer:  python -m mini_system.kb_viewer")


if __name__ == "__main__":
    main()
