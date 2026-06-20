# Warstwa wiedzy o atakach dla AutoDAN-Turbo — projekt

## Po co to

AutoDAN-Turbo z założenia uczy się „od zera": destyluje strategie z kontrastu własnych
słabych/mocnych payloadów ([autodan_turbo/summarizer.py](../autodan_turbo/summarizer.py)).
Na dobrze bronionym celu (agents_blocks, wektor `email`) nie ma czego destylować —
sygnał jest płaski, biblioteka pusta, cold-start się nie zawiązuje. Warstwa wiedzy
dostarcza **prior**: pulę znanych technik z literatury, którą atakujący retrievuje od
iteracji 1. Doświadczenie z biegów to **posterior** — co realnie działa na *ten* cel.
Mechanizm `mean_score` AutoDAN-a sam przycina nietrafione techniki (spadają w rankingu).

## Architektura: 3 warstwy

```
┌─ attack_techniques ──────────────┐   KATALOG (wiedza z literatury)
│  reference data, 1 wiersz/technika│   reużywalny, niezmienny w trakcie biegu
└──────────────┬───────────────────┘
               │ technique_id (FK, NULL = odkryte spoza katalogu)
   ┌───────────┴───────────────┐
   ▼                           ▼
┌─ attack_attempts ─────┐   ┌─ attack_strategies ──────┐
│ APPEND-ONLY log       │──▶│ AGREGATY (retrieval-facing)│
│ niezmienne fakty      │   │ utrzymywane write-through  │
│ = historia/wersjonow.  │   │ = szybki cosine retrieval  │
└───────────────────────┘   └────────────────────────────┘
```

Rozdzielenie **wiedzy** (katalog, powtarzalny opis) od **skuteczności** (per-przypadek,
zmienna) to normalizacja 1:N — ten sam opis techniki nie duplikuje się przy każdym
wariancie kontekstu.

### Tabela 1 — `attack_techniques` (katalog)
```
id | name (unique slug) | description | example | attack_class | source | created_at | updated_at
```
Seedowana migracją SQL (git-tracked) = wersjonowanie definicji w bazie.

### Tabela 2 — `attack_attempts` (append-only log, niezmienny)
```
id | technique_id→techniques | objective_id | vector_id
   | situation_text | embedding vector(768)   ← stan obrony, w który celowała próba
   | payload | outcome (BLOCKED/PARTIAL/ATTACK_SUCCESS/UNCLEAR) | depth | score
   | run_id | created_at
```
Jedna iteracja pętli = jeden wiersz. Bez UPDATE/DELETE — pełna historia/audyt.

### Tabela 3 — `attack_strategies` (agregaty, retrieval)
```
id | technique_id→techniques | objective_id | vector_id
   | situation_centroid embedding vector(768) | best_example
   | success_count | attempt_count | mean_score | last_updated
```
Jeden wiersz na `(technika × objective × vector)`. Aktualizowany write-through przy
zapisie próby. Retrieval czyta tę tabelę (cosine + ranking po `mean_score`).

## Przepływ danych

```
pętla AutoDAN → StrategyRepository.record(attempt):
   1. INSERT do attack_attempts (niezmienny fakt)
   2. UPSERT agregatu w attack_strategies (mean_score, liczniki, centroid embeddingu)
retrieval (epoka>0) → StrategyRepository.find(objective, vector, situation_embedding):
   cosine na attack_strategies → JOIN attack_techniques → ranking po mean_score
   cold start (brak doświadczenia) → fallback do katalogu (techniki nieużyte)
```

Klucz retrievalu = embedding **stanu obrony** (jak cel się obronił), nie samej odpowiedzi
— payload dobierany pod konkretny mur, o który atak się odbił.

## Wzorce projektowe

- **Normalizacja 1:N** katalog ↔ doświadczenie
- **CQRS-lite**: append-only log (zapis/audyt) oddzielony od tabeli agregatów (odczyt)
- **Repository/DAL**: `TechniqueRepository` + `StrategyRepository` — SQL poza pipeline'em
  (wzór: [database/audit_db.py](../database/audit_db.py))
- **Reference data via migration**: katalog wersjonowany migracjami
- **Write-through**: agregaty utrzymywane jawnie w repo (nie trigger — testowalne)
- Istniejącą `database/migrations/add_attack_strategies.sql` refaktorujemy na te 3 tabele
  (niezaaplikowana → zero migracji danych). Baza: `agent_audit`.

## Świadomie poza zakresem (osobno, później)

- **Multi-step / confused-deputy** — osobny, równoległy komponent (orkiestrator celujący
  w rozumowanie supervisora). Katalog może opisywać takie techniki (`attack_class='multi_step'`),
  ale ich wykonanie to przyszły mechanizm, nie ten single-shot pipeline.
- **Indeks ANN** (ivfflat/hnsw) — dopiero przy tysiącach wierszy.
- **Treść katalogu** (konkretne techniki z literatury) — seed po zatwierdzeniu schematu.

## Kolejność implementacji

1. Migracja: 3 tabele (refaktor `add_attack_strategies.sql`), aplikacja na `agent_audit`.
2. `StrategyRepository` + `TechniqueRepository` (zapis próby write-through, retrieval cosine).
3. Seed katalogu technik z literatury (migracja/seed + loader).
4. Wpięcie w `autodan_turbo`: retrieval z DB + zapis prób + flaga `--seed`.
