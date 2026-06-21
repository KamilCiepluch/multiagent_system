"""
Seed katalogu technik ataku do bazy (agent_audit.attack_techniques).

Idempotentny — upsert po unikalnej nazwie, więc można odpalać wielokrotnie po
aktualizacji `catalog.py`. Wymaga bazy agent_core ze schematem `knowledge`
(database/schema_core.sql) — katalog to reference data, nie idzie przez docker init.

Uruchomienie:
    python -m attack_core.knowledge.seed
"""

from __future__ import annotations

from attack_core.knowledge.catalog import TECHNIQUES
from database.knowledge_db import TechniqueRepository


def seed_catalog() -> int:
    for t in TECHNIQUES:
        TechniqueRepository.upsert(
            name=t["name"],
            description=t["description"],
            example=t.get("example"),
            attack_class=t.get("attack_class"),
            source=t.get("source"),
        )
    return len(TECHNIQUES)


if __name__ == "__main__":
    n = seed_catalog()
    print(f"Zaseedowano {n} technik. Katalog liczy {TechniqueRepository.count()} wpisów.")
