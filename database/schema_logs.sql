-- =============================================================
-- LOGS DB SCHEMA — agent_logs
-- Dedykowana baza obserwowalności systemu agentowego.
-- Logowana ZAWSZE przy każdym przebiegu workflow — niezależnie od tego,
-- czy przebieg jest częścią ataku (attack_runner) czy zwykłym uruchomieniem.
-- Niezależna od agent_benchmark (resetowalna) i agent_audit (forensika ataków).
--
-- Tworzenie bazy:
--   createdb -U postgres agent_logs
--   psql -U postgres -d agent_logs -f database/schema_logs.sql
--
-- Schemat znormalizowany — odwzorowuje strukturę idealnego logu:
--   1.   runs.task                  — zadanie całego systemu
--   2.   agent_invocations          — kolejność i zagnieżdżenie wywołań agentów
--   2.1  agent_invocations.input    — to co trafia do agenta
--   2.2  loaded_skills              — wczytane skille
--   2.3  tool_calls                 — uruchomienia narzędzi
--   2.3.1 tool_calls.input/output/is_error — wejście, wyjście, flaga błędu
--   (+)  agent_invocations.thinking — opcjonalny thinking agenta (debug)
--   (+)  run_db_changes            — co zostało zapisane do agent_benchmark w trakcie
-- =============================================================

-- =============================================================
-- RESET — usuwa wszystko i tworzy od nowa (kolejność wg zależności FK)
-- =============================================================
DROP TABLE IF EXISTS run_db_changes   CASCADE;
DROP TABLE IF EXISTS loaded_skills    CASCADE;
DROP TABLE IF EXISTS tool_calls       CASCADE;
DROP TABLE IF EXISTS agent_invocations CASCADE;
DROP TABLE IF EXISTS runs             CASCADE;

-- =============================================================
-- RUNS — jeden przebieg systemu agentowego (jedno workflow.invoke)
-- =============================================================
CREATE TABLE runs (
    run_id      UUID        PRIMARY KEY,
    task        TEXT        NOT NULL,                  -- zadanie zlecone całemu systemowi (pkt 1)
    mode        TEXT,                                  -- 'orchestrator' | 'supervisor'
    status      TEXT        NOT NULL DEFAULT 'running',-- running | completed | error
    result      TEXT,                                  -- końcowy output systemu
    error       TEXT,                                  -- treść wyjątku jeśli przebieg się wywalił
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

-- =============================================================
-- AGENT_INVOCATIONS — pojedyncze wywołanie agenta w obrębie przebiegu
-- seq        — globalna kolejność wywołań w przebiegu (pkt 2: kolejność agentów)
-- parent_id  — zagnieżdżenie: supervisor → agent podrzędny (NULL = wywołanie najwyższego poziomu)
-- =============================================================
CREATE TABLE agent_invocations (
    id            SERIAL      PRIMARY KEY,
    run_id        UUID        NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    parent_id     INT         REFERENCES agent_invocations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,                 -- kolejność w obrębie przebiegu (1-based)
    agent_name    TEXT        NOT NULL,
    input         TEXT,                                 -- to co trafia do agenta (pkt 2.1)
    output        TEXT,                                 -- dokładny output agenta
    thinking      TEXT,                                 -- opcjonalny thinking (pkt: debug)
    status        TEXT        NOT NULL DEFAULT 'running',-- running | completed | error
    error         TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ
);

CREATE INDEX idx_inv_run    ON agent_invocations(run_id);
CREATE INDEX idx_inv_parent ON agent_invocations(parent_id);

-- =============================================================
-- TOOL_CALLS — uruchomienie pojedynczego narzędzia MCP przez agenta (pkt 2.3)
-- Wpis powstaje PRZED wykonaniem narzędzia (on_tool_start) i jest uzupełniany
-- po zakończeniu (on_tool_end / on_tool_error) — ślad próby istnieje nawet gdy
-- narzędzie zawiśnie lub rzuci wyjątek.
-- =============================================================
CREATE TABLE tool_calls (
    id            SERIAL      PRIMARY KEY,
    invocation_id INT         NOT NULL REFERENCES agent_invocations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,                 -- kolejność wywołań w obrębie agenta
    tool_name     TEXT        NOT NULL,
    input         JSONB,                                -- argumenty wejściowe (pkt 2.3.1)
    output        TEXT,                                 -- wynik narzędzia (pkt 2.3.1)
    is_error      BOOLEAN     NOT NULL DEFAULT FALSE,   -- flaga błędu (pkt 2.3.1)
    error         TEXT,                                 -- treść błędu jeśli is_error
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ
);

CREATE INDEX idx_tc_inv ON tool_calls(invocation_id);

-- =============================================================
-- LOADED_SKILLS — wczytane / wylistowane skille agenta (pkt 2.2)
-- Wyodrębnione z tool_calls: list_skills / load_skill są narzędziami, ale
-- z punktu widzenia logu to osobna kategoria — "jakie procedury agent wczytał".
-- action: 'list' (wylistowanie dostępnych) | 'load' (wczytanie pełnej treści)
-- =============================================================
CREATE TABLE loaded_skills (
    id            SERIAL      PRIMARY KEY,
    invocation_id INT         NOT NULL REFERENCES agent_invocations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,
    action        TEXT        NOT NULL,                 -- 'list' | 'load'
    skill_name    TEXT,                                 -- NULL dla 'list'
    content       TEXT,                                 -- treść wczytanego skilla / wynik listy
    is_error      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_skills_inv ON loaded_skills(invocation_id);

-- =============================================================
-- RUN_DB_CHANGES — co dany przebieg zapisał do agent_benchmark
-- Pełna historia mutacji (INSERT/UPDATE/DELETE) wykonanych w trakcie przebiegu,
-- z dowiązaniem do agenta (invocation_id), który je spowodował.
-- old_value = NULL przy INSERT, new_value = NULL przy DELETE.
-- =============================================================
CREATE TABLE run_db_changes (
    id            SERIAL      PRIMARY KEY,
    run_id        UUID        NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    invocation_id INT         REFERENCES agent_invocations(id) ON DELETE SET NULL,
    seq           INT         NOT NULL,
    table_name    TEXT        NOT NULL,
    operation     TEXT        NOT NULL,                 -- INSERT | UPDATE | DELETE
    record_key    TEXT,
    old_value     JSONB,
    new_value     JSONB,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dbchg_run ON run_db_changes(run_id);
CREATE INDEX idx_dbchg_inv ON run_db_changes(invocation_id);
