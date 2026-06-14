-- Migration: biblioteka strategii atakującego (agent_audit.attack_strategies).
--
-- Uczona, wielokrotnego użytku baza wiedzy hiperagenta (wzorzec AutoDAN-Turbo):
-- po każdej generacji summarizer destyluje nazwaną strategię i zapisuje ją tutaj
-- razem z embeddingiem; kolejne generacje pobierają top-k najbliższych strategii
-- (podobieństwo cosine) dla danego celu/wektora.
--
-- Wymaga obrazu Postgresa z pgvector (docker-compose: pgvector/pgvector:pg16).
-- Uruchom jednorazowo na bazie audytowej:
--   psql -U postgres -d agent_audit -f database/migrations/add_attack_strategies.sql
--
-- Wymiar 768 = model embeddingów `nomic-embed-text` (HYPERAGENT_EMAIL_EMBED_MODEL).
-- Jeśli zmienisz model embeddingów na inny wymiar — zmień też vector(N) poniżej.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS attack_strategies (
    id              SERIAL       PRIMARY KEY,
    name            TEXT         NOT NULL UNIQUE,   -- kebab-case slug strategii
    description     TEXT         NOT NULL,          -- na czym polega technika
    example         TEXT,                           -- skrótowy przykład payloadu/pipeline'u
    objective_id    TEXT,                           -- cel, przy którym powstała (np. secret_exfiltration)
    vector_id       TEXT,                           -- wektor wstrzyknięcia (np. email)
    embedding       vector(768),                    -- embedding (name + description) do retrievalu
    success_count   INT          NOT NULL DEFAULT 0,
    attempt_count   INT          NOT NULL DEFAULT 0,
    mean_score      REAL         NOT NULL DEFAULT 0, -- średni "score" werdyktów (BLOCKED=0..ATTACK_SUCCESS=1)
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attack_strategies_objective
    ON attack_strategies (objective_id, vector_id);

-- UWAGA: NIE tworzymy indeksu ANN (ivfflat/hnsw) na starcie. Przy małej bibliotece
-- (dziesiątki–setki wierszy) dokładny seq scan po `embedding <=> q` jest szybki i ma
-- recall=100%. ivfflat przy garstce wierszy ma niemal zerowy recall (zapytanie trafia
-- w pustą listę i ZWRACA 0 wyników) — Postgres ostrzega o tym przy tworzeniu indeksu.
-- Dodaj indeks ANN dopiero gdy tabela urośnie do tysięcy wierszy, np.:
--   CREATE INDEX idx_attack_strategies_embedding ON attack_strategies
--       USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--   -- i przy zapytaniach: SET ivfflat.probes = 10;
