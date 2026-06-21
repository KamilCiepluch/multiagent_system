# Architektura baz danych

System używa **trzech fizycznych baz** (jeden silnik Postgres + pgvector):

| Baza | Po co | Cykl życia |
|---|---|---|
| **`agent_core`** | obserwowalność + audyt ataków + wiedza (3 schematy) | trwała, append-only |
| **`agent_benchmark`** | świat-cel, na którym działają agenci (skrzynka, pliki, skille…) | ciągły TRUNCATE + reseed |
| **`hyperagent_logs`** | obserwowalność osobnego toru `hyperagent_email` | trwała |

`agent_benchmark` i `hyperagent_logs` są osobno celowo (inny cykl życia / inny bounded context).

## `agent_core` — jedna baza, trzy schematy

```
logs       → runs, agent_invocations, tool_calls, reasoning_steps, loaded_skills, run_db_changes
audit      → attack_runs, attack_invocations (+verdict/evidence), self_improving_iterations, hyperagent_*
knowledge  → attack_techniques, attack_attempts, attack_strategies
```

Jedna baza ze schematami (zamiast wielu baz) daje **prawdziwe klucze obce cross-schema**
i joiny w jednym połączeniu, bez duplikowania danych:

- `audit.attack_invocations.run_id` → **FK** `logs.runs(run_id)`
- `knowledge.attack_attempts.run_id` → **FK** `logs.runs(run_id)`

### Adresowanie (DAL)
Każdy moduł DAL łączy się z `agent_core` z `search_path` ustawionym na swój schemat
(w DSN: `?options=-c search_path=<schemat>`), więc zapytania w module są bez kwalifikacji.
Cross-schema (FK w DDL, joiny) kwalifikujemy jawnie (`logs.agent_invocations`).
- `logs_db.py` → schemat `logs`
- `audit_db.py` → schemat `audit`
- `knowledge_db.py` → schemat `knowledge`

## ZASADA: logi są APPEND-ONLY (jedyne źródło prawdy)

> **Każde przejście zadania przez system agentowy jest ZAWSZE logowane do schematu `logs`
> (pisze tylko `run_logger`). Logi są niezmienne: raz zapisane — TYLKO czytamy, nigdy nie
> modyfikujemy ani nie kopiujemy.**

Dlaczego to istotne:
- `logs` to **jedyne źródło prawdy** o tym, co faktycznie zrobił system (agenci, tool-calle).
  Sędzia (`attack_core.judge`) i depth-scorer liczą ground-truth **z tych danych** — jeśli je
  zmodyfikujemy/zduplikujemy, zaczniemy zakłamywać rzeczywistość i podejmować decyzje na
  fałszywych danych.
- `audit` i `knowledge` **nie kopiują** trace'u — wskazują na niego przez `run_id`
  (referencja, nie duplikat). Odczyt trace'u zawsze przez `logs_db.get_run_logs(run_id)`.
- Werdykt sędziego (unikatowa dana atakowa) żyje w `audit.attack_invocations.verdict`, nie w logach.

Praktyczne reguły:
- Nie pisz do `logs.*` z niczego poza `run_logger`em.
- Nie dubluj danych przebiegu do innych schematów/baz — dodaj referencję `run_id`.
- Czytając trace, używaj `logs_db` (read-only API), nie surowego SQL na kopiach.

## Komendy

```bash
# świeże środowisko (docker tworzy agent_core ze schema_core.sql)
docker compose up -d postgres
# seed katalogu wiedzy (reference data — nie idzie przez docker init)
python -m attack_core.knowledge.seed
# podgląd przebiegów / trace
python show_run.py            # lista
python show_run.py <run_id>   # trace
```

Schemat: [database/schema_core.sql](../database/schema_core.sql). Geneza konsolidacji:
dawne `agent_logs` + `agent_audit` duplikowały trace (`attack_agent_logs`, `attack_db_changes`)
— usunięte na rzecz referencji `run_id`.
