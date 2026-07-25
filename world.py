"""
Reset i seed świata-celu czystego systemu agentowego.

Świat = tabele w bazie `agent_benchmark` (maile, kontakty, pliki, repozytoria,
wyniki wyszukiwania, tickety, spotkania, skille) — dane, na których operują agenci.

Reset: TRUNCATE ... RESTART IDENTITY CASCADE → seed z `seeds/*.sql` (dataset `default`)
→ załadowanie skilli z `agent_skills/` (jedno źródło prawdy). Idempotentne.

Ten moduł należy do czystego runtime'u agentowego: NIE dotyka schematu `audit`
(warstwa ataku) ani datasetów ataku (`seeds/datasets/attack_v1/`) — te graduują osobno.
Ekstrakt z `attack_core.runner.AttackRunner.reset_main_db`, bez warstwy ataku.

Użycie:
    python world.py
"""

from pathlib import Path

import psycopg2

from config import settings
from database import skills

_SEEDS_DIR = Path(__file__).parent / "seeds"

# Dataset `default` = oryginalny, niezmieniony świat (bez trucizny ataku).
_DEFAULT_SEEDS = [
    _SEEDS_DIR / "email_agent.sql",
    _SEEDS_DIR / "terminal_agent.sql",
    _SEEDS_DIR / "search_agent.sql",
]

_TRUNCATE = """
TRUNCATE TABLE
    emails, email_contacts, tools_outputs,
    agent_skills, repositories, github_sources,
    files, tickets, search_results, search_sources, meetings
RESTART IDENTITY CASCADE
"""


def reset_world() -> None:
    """TRUNCATE CASCADE świata + reseed datasetem `default` + załadowanie skilli.

    Skille są wspólne dla świata i ładowane z folderu `agent_skills/` (jedno źródło
    prawdy), nie z seedów — dzięki temu edycja skilla nie wymaga zmiany SQL-a."""
    conn = psycopg2.connect(dsn=settings.db_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(_TRUNCATE)
        conn.commit()
        for seed_file in _DEFAULT_SEEDS:
            sql = seed_file.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        skills.load_into(conn)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Reset świata (dataset default) → {settings.db_name}@{settings.db_host}...")
    reset_world()
    print("Gotowe.")
