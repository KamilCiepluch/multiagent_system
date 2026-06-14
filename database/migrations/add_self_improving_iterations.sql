-- Migration: dodaje tabelę self_improving_iterations do agent_audit.
-- Uruchom jednorazowo na istniejącej bazie audytowej:
--   psql -U postgres -d agent_audit -f database/migrations/add_self_improving_iterations.sql

CREATE TABLE IF NOT EXISTS self_improving_iterations (
    id                 SERIAL      PRIMARY KEY,
    attack_id          UUID        NOT NULL REFERENCES attack_runs(id),
    iteration_n        INT         NOT NULL,
    run_id             UUID,
    payload            TEXT        NOT NULL,
    verdict            TEXT        NOT NULL,  -- BLOCKED | ATTACK_SUCCESS | PARTIAL | UNCLEAR
    evidence           JSONB       NOT NULL DEFAULT '[]',
    judge_reasoning    TEXT,
    mutation_rationale TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_self_improving_attack_id ON self_improving_iterations(attack_id);
