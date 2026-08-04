"""Backup / restore the fake_internet knowledge base to and from a JSON file.

The JSON is a portable, human-editable snapshot of the `pages` table — so you can keep several
versions of the world (e.g. an inert 'canary' set and a separate one you fill yourself) and switch
between them for testing.

Run:
    python -m mini_system.kb_backup dump data/kb/canary.json
    python -m mini_system.kb_backup load data/kb/canary.json          # replaces the live DB
    python -m mini_system.kb_backup load data/kb/extra.json --append   # merge without wiping
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mini_system.internet_db import all_pages, ensure_schema, get_conn, upsert_pages


def dump(path: str) -> int:
    """Write every page to `path` as JSON. Returns the number of pages."""
    pages = all_pages()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(pages)


def load(path: str, *, replace: bool = True) -> int:
    """Load pages from `path`. replace=True wipes the table first; False merges (upsert).
    Missing is_sensitive is inferred from the category. Embeddings are recomputed on load,
    so a snapshot stays portable between machines. Returns the number of pages loaded."""
    pages = json.loads(Path(path).read_text(encoding="utf-8"))
    ensure_schema()
    if replace:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE pages RESTART IDENTITY")
    return upsert_pages(pages)


def _usage() -> None:
    print("usage: python -m mini_system.kb_backup {dump|load} <path.json> [--append]")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2 or args[0] not in ("dump", "load"):
        _usage()
        sys.exit(1)
    cmd, path = args[0], args[1]
    if cmd == "dump":
        print(f"Dumped {dump(path)} pages -> {path}")
    else:
        n = load(path, replace="--append" not in args)
        mode = "merged" if "--append" in args else "replaced DB with"
        print(f"Loaded {n} pages ({mode} {path}).")
