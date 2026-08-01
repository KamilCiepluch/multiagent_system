"""Enrich the fake_internet knowledge base with model-generated pages.

A model on the Ollama proxy writes short encyclopedia-style entries for each category and they are
upserted into the `pages` table. Everything you tune is a hardcoded constant at the top.

Run:  python -m database.generate_pages          # generate + insert
      (set DRY_RUN = True below to preview without touching the DB)

Afterwards refresh the viewer:  python -m interactive.kb_viewer
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from config import settings
from database.internet_db import SENSITIVE_CATEGORIES, get_conn

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — edit these
# ══════════════════════════════════════════════════════════════════════════════

# Model (uncomment ONE; all served by the Ollama proxy — see reference_proxy_models):
MODEL = "gemma4:31b"
# MODEL = "qwen3.6:35b"
# MODEL = "llama3.3:70b"
# MODEL = "qwen3.5:9b"
# MODEL = "satgeze/gemma4-26b-uncensored-1m:latest"
# MODEL = "satgeze/qwen36-35b-uncensored-1m:q4_k_m-no-mtp"
# MODEL = "richardyoung/qwen3.6-27b-abliterated:Q8_0"
# MODEL = "tinyrick/gemma-4-31B-it-uncensored-heretic-vision-llmfan46:Q4_K_M"

# Categories to generate example information for (add/remove freely):
CATEGORIES = [
    "astronomy",
    "chemistry",
    "biology",
    "world-geography",
    "sports",
    "art",
    "literature",
    "economics",
    "architecture",
    "mathematics",
]

PAGES_PER_CATEGORY = 4
TEMPERATURE = 0.7
DRY_RUN = False  # True → print generated pages, do NOT write to the DB

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


def build_llm() -> ChatOllama:
    """ChatOllama pointed at the proxy (base_url/bearer from settings), with MODEL overridden."""
    extra: dict = {}
    if settings.ollama_bearer_token:
        from ollama_proxy import AsyncSanitizingTransport, SanitizingTransport

        extra["client_kwargs"] = {"headers": {"Authorization": f"Bearer {settings.ollama_bearer_token}"}}
        extra["sync_client_kwargs"] = {"transport": SanitizingTransport()}
        extra["async_client_kwargs"] = {"transport": AsyncSanitizingTransport()}
    return ChatOllama(
        model=MODEL,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        temperature=TEMPERATURE,
        reasoning=False,
        **extra,
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")[:60] or "entry"


def generate_for_category(llm: ChatOllama, category: str, n: int) -> list[dict]:
    """Ask the model for `n` entries and parse them into page dicts."""
    prompt = f"CATEGORY: {category}\nGenerate {n} entries."
    text = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]).content
    pages = []
    for m in _BLOCK_RE.finditer(text):
        content = " ".join(m.group("content").split())
        if not content:
            continue
        pages.append({
            "category": category,
            "topic": _slug(m.group("topic")),
            "title": m.group("title").strip(),
            "content": content,
        })
    return pages


def upsert_page(page: dict) -> None:
    is_sensitive = page["category"] in SENSITIVE_CATEGORIES
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pages (category, topic, title, content, is_sensitive) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (category, topic) DO UPDATE SET "
            "title=EXCLUDED.title, content=EXCLUDED.content, is_sensitive=EXCLUDED.is_sensitive",
            (page["category"], page["topic"], page["title"], page["content"], is_sensitive),
        )


def main() -> None:
    llm = build_llm()
    print(f"Generating with model={MODEL} · {PAGES_PER_CATEGORY}/category · dry_run={DRY_RUN}\n")
    total = 0
    for category in CATEGORIES:
        pages = generate_for_category(llm, category, PAGES_PER_CATEGORY)
        print(f"[{category}] {len(pages)} entries")
        for p in pages:
            print(f"    - {p['topic']}: {p['title']}")
            if not DRY_RUN:
                upsert_page(p)
        total += len(pages)
    print(f"\n{'Would upsert' if DRY_RUN else 'Upserted'} {total} pages.")
    if not DRY_RUN:
        print("Refresh the viewer:  python -m interactive.kb_viewer")


if __name__ == "__main__":
    main()
