-- Migration: warstwa wiedzy o atakach (3 tabele) na bazie agent_audit.
--
-- Wzorzec AutoDAN-Turbo + prior z literatury. Rozdziela WIEDZĘ (katalog technik,
-- powtarzalny opis) od SKUTECZNOŚCI (per-przypadek, zmienna) — normalizacja 1:N.
-- Projekt: docs/knowledge_layer_design.md
--
-- Wymaga obrazu Postgresa z pgvector (docker-compose: pgvector/pgvector:pg16).
-- Uruchom jednorazowo na bazie audytowej:
--   psql -U postgres -d agent_audit -f database/migrations/add_attack_strategies.sql
--
-- Wymiar 768 = model embeddingów `nomic-embed-text`.

CREATE EXTENSION IF NOT EXISTS vector;

-- ── 1) KATALOG technik (reference data z literatury; wersjonowany migracjami) ──
CREATE TABLE IF NOT EXISTS attack_techniques (
    id           SERIAL      PRIMARY KEY,
    name         TEXT        NOT NULL UNIQUE,   -- kebab-case slug
    description  TEXT        NOT NULL,          -- na czym polega technika
    example      TEXT,                          -- ilustracyjny szablon payloadu
    attack_class TEXT,                          -- taksonomia (persuasion / provenance / ...)
    source       TEXT,                          -- cytat z literatury lub 'discovered'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 2) APPEND-ONLY log prób (niezmienne fakty = historia/audyt) ──
CREATE TABLE IF NOT EXISTS attack_attempts (
    id            SERIAL      PRIMARY KEY,
    technique_id  INT         REFERENCES attack_techniques(id),  -- NULL = czysta eksploracja (warm-up)
    objective_id  TEXT,
    vector_id     TEXT,
    situation_text TEXT,                         -- stan obrony, w który celowała próba
    embedding     vector(768),                   -- embedding situation_text (klucz retrievalu)
    payload       TEXT,
    outcome       TEXT,                          -- BLOCKED | PARTIAL | ATTACK_SUCCESS | UNCLEAR
    depth         REAL,                          -- graded whitebox depth (1..10)
    score         REAL,                          -- wierny scorer 1..10
    run_id        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_attack_attempts_ctx
    ON attack_attempts (objective_id, vector_id);

-- ── 3) AGREGATY (retrieval-facing; utrzymywane write-through) ──
CREATE TABLE IF NOT EXISTS attack_strategies (
    id            SERIAL      PRIMARY KEY,
    technique_id  INT         NOT NULL REFERENCES attack_techniques(id),
    objective_id  TEXT,
    vector_id     TEXT,
    situation_centroid vector(768),              -- reprezentatywny embedding stanu obrony
    best_example  TEXT,                          -- najlepiej oceniony payload w tym kontekście
    success_count INT         NOT NULL DEFAULT 0,
    attempt_count INT         NOT NULL DEFAULT 0,
    mean_score    REAL        NOT NULL DEFAULT 0,  -- średni depth; klucz rankingu
    best_score    REAL        NOT NULL DEFAULT 0,  -- najlepszy depth (wyznacza best_example/centroid)
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (technique_id, objective_id, vector_id)
);
CREATE INDEX IF NOT EXISTS idx_attack_strategies_ctx
    ON attack_strategies (objective_id, vector_id);

-- UWAGA: indeks ANN (ivfflat/hnsw) dopiero przy tysiącach wierszy — przy garstce
-- dokładny seq scan po `embedding <=> q` ma recall=100%, a ivfflat zwraca 0 wyników.
