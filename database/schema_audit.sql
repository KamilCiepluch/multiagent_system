-- =============================================================
-- AUDIT DB SCHEMA — agents_audit
-- Baza nigdy nie jest resetowana.
-- Przechowuje pełną historię ataków, wywołań i zmian w agents_db.
--
-- Tworzenie bazy:
--   createdb -U postgres agent_audit
--   psql -U postgres -d agent_audit -f database/schema_audit.sql
-- =============================================================

-- =============================================================
-- SCENARIUSZE ATAKÓW
-- Jeden rekord = jeden test (np. "prompt_injection_via_log").
-- =============================================================
CREATE TABLE IF NOT EXISTS attack_runs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    attack_type TEXT,
    description TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    outcome     TEXT        -- 'succeeded' | 'blocked' | 'partial' | 'error' | 'unknown'
);

-- =============================================================
-- WYWOŁANIA W RAMACH ATAKU
-- Jeden atak może mieć N wywołań (N zadań agenta).
-- run_id mapuje do run_id z workflow — pozwala skrzyżować z agent_logs.
-- =============================================================
CREATE TABLE IF NOT EXISTS attack_invocations (
    id           SERIAL      PRIMARY KEY,
    attack_id    UUID        NOT NULL REFERENCES attack_runs(id),
    invocation_n INT         NOT NULL,
    run_id       UUID,
    task         TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_invocations_attack_id ON attack_invocations(attack_id);

-- =============================================================
-- LOGI AGENTÓW (kopia z agents_db.agent_logs per wywołanie)
-- =============================================================
CREATE TABLE IF NOT EXISTS attack_agent_logs (
    id             SERIAL      PRIMARY KEY,
    invocation_id  INT         NOT NULL REFERENCES attack_invocations(id),
    agent_name     TEXT,
    task           TEXT,
    tool_calls     JSONB       NOT NULL DEFAULT '[]',
    final_output   TEXT,
    attack_success BOOLEAN,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_logs_invocation ON attack_agent_logs(invocation_id);

-- =============================================================
-- ZMIANY W BAZIE DANYCH (diff per operacja)
-- Rejestruje co dokładnie zmieniło się w agents_db.
-- old_value = NULL przy INSERT, new_value = NULL przy DELETE.
-- =============================================================
CREATE TABLE IF NOT EXISTS attack_db_changes (
    id             SERIAL      PRIMARY KEY,
    invocation_id  INT         NOT NULL REFERENCES attack_invocations(id),
    table_name     TEXT        NOT NULL,
    operation      TEXT        NOT NULL,  -- INSERT | UPDATE | DELETE
    record_key     TEXT,                  -- czytelny klucz rekordu (np. "execute_command/ls -la")
    old_value      JSONB,
    new_value      JSONB,
    changed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_db_changes_invocation ON attack_db_changes(invocation_id);
CREATE INDEX IF NOT EXISTS idx_db_changes_table      ON attack_db_changes(table_name);
