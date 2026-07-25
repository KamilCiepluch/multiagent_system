"""
Loader skilli agentów z folderu `agent_skills/<agent>/<nazwa>.md` → tabela `agent_skills`.

JEDNO ŹRÓDŁO PRAWDY: jeden skill = jeden plik .md (front-matter `description:` + treść).
Czytelne i edytowalne; loader wstawia je czystym, parametryzowanym INSERT-em — zamiast setek
linii dollar-quoted SQL w seedach. Używany przez `reset_main_db` (skille są WSPÓLNE dla wszystkich
datasetów). Dla docker initdb (nie odpala Pythona) generujemy `seeds/agent_skills_seed.sql` przez
`python -m database.skills emit`.
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "agent_skills"
_DOLLAR_TAG = "$skillbody$"


def _parse(text: str) -> tuple[str, str]:
    """Z pliku skilla zwraca (description, content). Front-matter: '---\\ndescription: ...\\n---'."""
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
    """Lista (agent_name, name, description, content) — stabilnie posortowana (agent, nazwa pliku)."""
    out: list[tuple[str, str, str, str]] = []
    if not SKILLS_DIR.is_dir():
        return out
    for agent_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        for f in sorted(agent_dir.glob("*.md")):
            desc, content = _parse(f.read_text(encoding="utf-8"))
            out.append((agent_dir.name, f.stem, desc, content))
    return out


def load_into(conn) -> int:
    """Wstawia wszystkie skille do `agent_skills` (zakłada wcześniejszy TRUNCATE). Zwraca liczbę."""
    rows = iter_skills()
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO agent_skills (agent_name, name, description, content) VALUES (%s,%s,%s,%s)",
                rows,
            )
    return len(rows)


def emit_sql() -> str:
    """Generuje SQL (INSERT) z folderu — dla docker initdb. Treść w dollar-quotingu ($skillbody$)."""
    lines = [
        "-- WYGENEROWANE z agent_skills/ przez `python -m database.skills emit` — NIE edytuj ręcznie.",
        "-- Źródło prawdy: folder agent_skills/<agent>/<nazwa>.md (jeden skill = jeden plik).",
        "",
    ]
    for agent, name, desc, content in iter_skills():
        assert _DOLLAR_TAG not in content, f"kolizja dollar-tag w skillu {agent}/{name}"
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
        print(f"Zapisano {out} ({len(iter_skills())} skilli)")
    else:
        for a, n, d, c in iter_skills():
            print(f"{a}/{n}: {d[:60]} ({len(c)} znaków)")
