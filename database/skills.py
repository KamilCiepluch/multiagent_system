"""
Loader for agent skills from the `agent_skills/<agent>/<name>.md` folder → `agent_skills` table.

SINGLE SOURCE OF TRUTH: one skill = one .md file (front-matter `description:` + content).
Readable and editable; the loader inserts them with a clean, parameterized INSERT — instead of hundreds
of lines of dollar-quoted SQL in the seeds. Used by `reset_main_db` (skills are SHARED across all
datasets). For docker initdb (which does not run Python) we generate `seeds/agent_skills_seed.sql` via
`python -m database.skills emit`.
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "agent_skills"
_DOLLAR_TAG = "$skillbody$"


def _parse(text: str) -> tuple[str, str]:
    """From a skill file returns (description, content). Front-matter: '---\\ndescription: ...\\n---'."""
    description, body = "", text
    if text.startswith("---"):
        parts = text.split("---", 2)  # ['', front-matter, body]
        if len(parts) == 3:
            fm, body = parts[1], parts[2]
            for line in fm.splitlines():
                s = line.strip()
                if s.lower().startswith("description:"):
                    description = s.split(":", 1)[1].strip()
    return description, body.strip()


def iter_skills() -> list[tuple[str, str, str, str]]:
    """List of (agent_name, name, description, content) — stably sorted (agent, file name)."""
    out: list[tuple[str, str, str, str]] = []
    if not SKILLS_DIR.is_dir():
        return out
    for agent_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        for f in sorted(agent_dir.glob("*.md")):
            desc, content = _parse(f.read_text(encoding="utf-8"))
            out.append((agent_dir.name, f.stem, desc, content))
    return out


def load_into(conn) -> int:
    """Inserts all skills into `agent_skills` (assumes a prior TRUNCATE). Returns the count."""
    rows = iter_skills()
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO agent_skills (agent_name, name, description, content) VALUES (%s,%s,%s,%s)",
                rows,
            )
    return len(rows)


def emit_sql() -> str:
    """Generates SQL (INSERT) from the folder — for docker initdb. Content is dollar-quoted ($skillbody$)."""
    lines = [
        "-- GENERATED from agent_skills/ by `python -m database.skills emit` — do NOT edit by hand.",
        "-- Source of truth: the agent_skills/<agent>/<name>.md folder (one skill = one file).",
        "",
    ]
    for agent, name, desc, content in iter_skills():
        assert _DOLLAR_TAG not in content, f"dollar-tag collision in skill {agent}/{name}"
        d = desc.replace("'", "''")
        lines.append(
            "INSERT INTO agent_skills (agent_name, name, description, content) VALUES\n"
            f"  ('{agent}', '{name}', '{d}', {_DOLLAR_TAG}{content}{_DOLLAR_TAG});"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "emit":
        out = SKILLS_DIR.parent / "seeds" / "agent_skills_seed.sql"
        out.write_text(emit_sql(), encoding="utf-8")
        print(f"Wrote {out} ({len(iter_skills())} skills)")
    else:
        for a, n, d, c in iter_skills():
            print(f"{a}/{n}: {d[:60]} ({len(c)} chars)")
