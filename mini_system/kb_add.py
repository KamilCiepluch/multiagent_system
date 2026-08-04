"""Interactive console for adding knowledge-base pages by hand — human writes the content.

A companion to kb_studio (which asks a model to generate pages); here you type them yourself. Every
saved page is embedded on write (upsert_page → nomic-embed-text + FTS), so it is searchable the
instant you save it. Nothing is written without your confirmation.

You pick the target database up front, so you can fill the working world (fake_internet) or a
separate experimental one (e.g. fake_internet_realism) without touching the other.

Run:  python -m mini_system.kb_add
      python -m mini_system.kb_add --db fake_internet_realism
"""

from __future__ import annotations

import sys

from config import settings

_RULE = "  " + "-" * 68
_CONTENT_END = "."   # a line containing only this ends multi-line content entry


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nbye")
    return val or default


def _ask_multiline(prompt: str) -> str:
    print(prompt)
    print(f"  (type your text; finish with a single line containing only '{_CONTENT_END}')")
    lines: list[str] = []
    while True:
        try:
            line = input("  | ")
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() == _CONTENT_END:
            break
        lines.append(line)
    return " ".join(" ".join(lines).split())


def _choose_db() -> str:
    default = settings.fake_internet_db_name
    name = _ask(f"Target database [{default}]: ", default)
    settings.fake_internet_db_name = name
    return name


def _print_entry(page: dict) -> None:
    flag = "  [SENSITIVE]" if page["is_sensitive"] else ""
    print(_RULE)
    print(f"  {page['title']}   ({page['category']}/{page['topic']}){flag}")
    print(f"  {page['content']}")
    print(_RULE)


def _collect(db) -> dict | None:
    """Gather one page from the user. Returns the page dict, or None to go back to the menu."""
    category = _ask("Category (blank to finish): ")
    if not category:
        return None
    topic = _ask("Topic slug (unique within the category): ")
    if not topic:
        print("  [skipped: a topic slug is required]")
        return None
    title = _ask("Title: ")
    content = _ask_multiline("Content:")
    if not content:
        print("  [skipped: empty content]")
        return None

    default_sens = db.is_sensitive_category(category)
    sens_raw = _ask(f"Mark sensitive? [{'Y/n' if default_sens else 'y/N'}]: ",
                    "y" if default_sens else "n")
    is_sensitive = sens_raw.lower().startswith("y")

    return {"category": category, "topic": topic, "title": title,
            "content": content, "is_sensitive": is_sensitive}


def _exists(db, category: str, topic: str) -> bool:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pages WHERE category=%s AND topic=%s", (category, topic))
        return cur.fetchone() is not None


def _save_and_verify(db, page: dict) -> None:
    updating = _exists(db, page["category"], page["topic"])
    db.upsert_page(page)  # embeds on write
    print(f"  [{'updated' if updating else 'saved'} + embedded]")
    hits = db.search(page["title"], limit=1)
    if hits:
        h = hits[0]
        print(f"  [verify] top hit for the title: [{h.id}] {h.category}/{h.topic}  [{h.matched}]")
    else:
        print("  [verify] warning: the page did not come back from search — check the embedding model")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if "--db" in sys.argv:
        settings.fake_internet_db_name = sys.argv[sys.argv.index("--db") + 1]
        db_name = settings.fake_internet_db_name
    else:
        db_name = _choose_db()

    from mini_system import internet_db as db  # imported after the DB name is set

    db.ensure_schema()
    print(f"\nAdding pages to '{db_name}'. Content is embedded on save; nothing is written "
          f"without confirmation.\n")

    saved = 0
    while True:
        cats = db.list_categories()
        existing = ", ".join(f"{c}({n})" for c, n in cats) if cats else "(none yet)"
        print(f"Existing categories: {existing}")

        page = _collect(db)
        if page is None:
            break

        while True:
            _print_entry(page)
            action = _ask("  [s]ave  [e]dit  [n]skip  [q]uit: ", "s").lower()
            if action in ("s", "save"):
                _save_and_verify(db, page)
                saved += 1
                break
            if action in ("n", "skip"):
                print("  [skipped]")
                break
            if action in ("q", "quit"):
                print(f"\nSaved {saved} page(s) to '{db_name}'. "
                      f"View: python -m mini_system.kb_viewer")
                return
            if action in ("e", "edit"):
                page["title"] = _ask(f"  title [{page['title']}]: ", page["title"])
                new_content = _ask_multiline("  content (finish with '.'; leave empty to keep current):")
                if new_content:
                    page["content"] = new_content
                sens_raw = _ask(f"  sensitive? [{'Y/n' if page['is_sensitive'] else 'y/N'}]: ",
                                "y" if page["is_sensitive"] else "n")
                page["is_sensitive"] = sens_raw.lower().startswith("y")
        print()

    print(f"\nSaved {saved} page(s) to '{db_name}'. View: python -m mini_system.kb_viewer")


if __name__ == "__main__":
    main()
