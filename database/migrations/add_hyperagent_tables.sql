-- Migration: dodaje tabele hyperagenta do agent_audit.
-- Uruchom jednorazowo na istniejącej bazie audytowej:
--   psql -U postgres -d agent_audit -f database/migrations/add_hyperagent_tables.sql

-- =============================================================
-- BEZWARUNKOWY LOG GATEWAYA
-- To jest mechanizm "niełamliwych adnotacji": gateway zapisuje tu
-- KAŻDE wywołanie PRZED jego wykonaniem — agent (zamknięty w osobnym
-- kontenerze, bez dostępu do tej bazy) nie ma żadnej drogi, by ten
-- wpis ominąć, podmienić czy usunąć, niezależnie od tego, jak bardzo
-- przepisze własny kod.
-- =============================================================
CREATE TABLE IF NOT EXISTS hyperagent_gateway_log (
    id            SERIAL      PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES attack_runs(id),
    generation_n  INT,
    endpoint      TEXT        NOT NULL,
    request       JSONB,
    response      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hyperagent_gateway_log_session ON hyperagent_gateway_log(session_id);

-- =============================================================
-- ARCHIWUM GENERACJI (kod + wynik + rodowód)
-- Odpowiednik archive.jsonl z HyperAgents — tu kod każdej generacji
-- jest przechowywany jako spakowany snapshot drzewa /workspace.
-- =============================================================
CREATE TABLE IF NOT EXISTS hyperagent_generations (
    id            SERIAL      PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES attack_runs(id),
    generation_n  INT         NOT NULL,
    parent_n      INT,
    code_archive  BYTEA       NOT NULL,
    score         TEXT,       -- BLOCKED | ATTACK_SUCCESS | PARTIAL | UNCLEAR | NULL (seed)
    evidence      JSONB       NOT NULL DEFAULT '[]',
    run_ids       JSONB       NOT NULL DEFAULT '[]',
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hyperagent_generations_session ON hyperagent_generations(session_id);

-- =============================================================
-- WŁASNA HISTORIA AGENTA
-- Append-only z definicji: nie istnieje żadna ścieżka UPDATE/DELETE
-- (ani tutaj, ani w gatewayu) — agent może czytać całość i dopisywać,
-- ale nigdy nie zmodyfikować ani usunąć wcześniejszego wpisu.
-- =============================================================
CREATE TABLE IF NOT EXISTS hyperagent_history_entries (
    id            SERIAL      PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES attack_runs(id),
    generation_n  INT         NOT NULL,
    entry_type    TEXT        NOT NULL,
    content       TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hyperagent_history_session ON hyperagent_history_entries(session_id);
