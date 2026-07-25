-- =============================================================
-- agent_core — JEDNA baza, TRZY schematy: logs / audit / knowledge
--
-- Konsolidacja dawnych agent_logs + agent_audit + warstwy wiedzy w jedną bazę
-- ze schematami (bounded contexts), co daje PRAWDZIWE klucze obce cross-schema
-- i joiny w jednym połączeniu — bez duplikowania danych.
--
-- Poza tą bazą (osobne, inny cykl życia):
--   • agent_benchmark   — świat-cel (ciągły TRUNCATE + reseed)
--   • hyperagent_logs   — obserwowalność toru hyperagent_email
--
-- ZASADA: schemat `logs` to JEDYNE źródło prawdy o przebiegu (trace). Jest
-- APPEND-ONLY — pisze tylko run_logger; wszyscy inni TYLKO czytają. `audit` i
-- `knowledge` NIE kopiują trace'u — wskazują na niego przez `run_id` (FK → logs.runs).
--
-- Tworzenie:
--   createdb -U postgres agent_core
--   psql -U postgres -d agent_core -f database/schema_core.sql
-- =============================================================

CREATE SCHEMA IF NOT EXISTS logs;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS recon;
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================
-- SCHEMA: logs  — obserwowalność przebiegu (jedyne źródło prawdy, append-only)
-- =============================================================
DROP TABLE IF EXISTS logs.run_db_changes   CASCADE;
DROP TABLE IF EXISTS logs.reasoning_steps  CASCADE;
DROP TABLE IF EXISTS logs.loaded_skills    CASCADE;
DROP TABLE IF EXISTS logs.tool_calls       CASCADE;
DROP TABLE IF EXISTS logs.agent_invocations CASCADE;
DROP TABLE IF EXISTS logs.runs             CASCADE;

CREATE TABLE logs.runs (
    run_id      UUID        PRIMARY KEY,
    task        TEXT        NOT NULL,
    mode        TEXT,
    status      TEXT        NOT NULL DEFAULT 'running',
    result      TEXT,
    error       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE logs.agent_invocations (
    id            SERIAL      PRIMARY KEY,
    run_id        UUID        NOT NULL REFERENCES logs.runs(run_id) ON DELETE CASCADE,
    parent_id     INT         REFERENCES logs.agent_invocations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,
    agent_name    TEXT        NOT NULL,
    input         TEXT,
    output        TEXT,
    status        TEXT        NOT NULL DEFAULT 'running',
    error         TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ
);
CREATE INDEX idx_inv_run    ON logs.agent_invocations(run_id);
CREATE INDEX idx_inv_parent ON logs.agent_invocations(parent_id);

CREATE TABLE logs.reasoning_steps (
    id            SERIAL      PRIMARY KEY,
    invocation_id INT         NOT NULL REFERENCES logs.agent_invocations(id) ON DELETE CASCADE,
    step          INT         NOT NULL,
    thinking      TEXT,
    content       TEXT,
    decided_tools JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rs_inv ON logs.reasoning_steps(invocation_id);

CREATE TABLE logs.tool_calls (
    id            SERIAL      PRIMARY KEY,
    invocation_id INT         NOT NULL REFERENCES logs.agent_invocations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,
    step          INT         NOT NULL,
    tool_name     TEXT        NOT NULL,
    input         JSONB,
    output        TEXT,
    is_error      BOOLEAN     NOT NULL DEFAULT FALSE,
    error         TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ
);
CREATE INDEX idx_tc_inv ON logs.tool_calls(invocation_id);

CREATE TABLE logs.loaded_skills (
    id            SERIAL      PRIMARY KEY,
    invocation_id INT         NOT NULL REFERENCES logs.agent_invocations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,
    step          INT         NOT NULL,
    action        TEXT        NOT NULL,
    skill_name    TEXT,
    content       TEXT,
    is_error      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_skills_inv ON logs.loaded_skills(invocation_id);

CREATE TABLE logs.run_db_changes (
    id            SERIAL      PRIMARY KEY,
    run_id        UUID        NOT NULL REFERENCES logs.runs(run_id) ON DELETE CASCADE,
    invocation_id INT         REFERENCES logs.agent_invocations(id) ON DELETE SET NULL,
    seq           INT         NOT NULL,
    table_name    TEXT        NOT NULL,
    operation     TEXT        NOT NULL,
    record_key    TEXT,
    old_value     JSONB,
    new_value     JSONB,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dbchg_run ON logs.run_db_changes(run_id);
CREATE INDEX idx_dbchg_inv ON logs.run_db_changes(invocation_id);

-- =============================================================
-- SCHEMA: audit  — warstwa ataku. TYLKO dane unikatowe; trace przez referencję.
-- (USUNIĘTE względem starego agent_audit: attack_agent_logs, attack_db_changes —
--  były kopią logs.* ; teraz czyta się je z logs przez run_id.)
-- =============================================================
CREATE TABLE IF NOT EXISTS audit.attack_runs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    attack_type TEXT,
    description TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    outcome     TEXT
);

-- Mapowanie sesja↔przebieg + WERDYKT (zastępuje martwe attack_agent_logs.attack_success).
-- run_id = PRAWDZIWY FK do logs.runs (run powstaje pierwszy — patrz AttackRunner).
CREATE TABLE IF NOT EXISTS audit.attack_invocations (
    id           SERIAL      PRIMARY KEY,
    attack_id    UUID        NOT NULL REFERENCES audit.attack_runs(id) ON DELETE CASCADE,
    invocation_n INT         NOT NULL,
    run_id       UUID        REFERENCES logs.runs(run_id) ON DELETE SET NULL,
    task         TEXT,
    verdict      TEXT,                                   -- BLOCKED | ATTACK_SUCCESS | PARTIAL | UNCLEAR
    evidence     JSONB       NOT NULL DEFAULT '[]',
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_invocations_attack_id ON audit.attack_invocations(attack_id);
CREATE INDEX IF NOT EXISTS idx_invocations_run_id    ON audit.attack_invocations(run_id);

CREATE TABLE IF NOT EXISTS audit.self_improving_iterations (
    id                 SERIAL      PRIMARY KEY,
    attack_id          UUID        NOT NULL REFERENCES audit.attack_runs(id) ON DELETE CASCADE,
    iteration_n        INT         NOT NULL,
    run_id             UUID        REFERENCES logs.runs(run_id) ON DELETE SET NULL,
    payload            TEXT        NOT NULL,
    verdict            TEXT        NOT NULL,
    evidence           JSONB       NOT NULL DEFAULT '[]',
    judge_reasoning    TEXT,
    mutation_rationale TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_self_improving_attack_id ON audit.self_improving_iterations(attack_id);

-- Tor hyperagent/ (self-mod) — sesją jest attack_run, stąd miejsce w `audit`.
CREATE TABLE IF NOT EXISTS audit.hyperagent_gateway_log (
    id            SERIAL      PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES audit.attack_runs(id) ON DELETE CASCADE,
    generation_n  INT,
    endpoint      TEXT        NOT NULL,
    request       JSONB,
    response      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hyperagent_gateway_log_session ON audit.hyperagent_gateway_log(session_id);

CREATE TABLE IF NOT EXISTS audit.hyperagent_generations (
    id            SERIAL      PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES audit.attack_runs(id) ON DELETE CASCADE,
    generation_n  INT         NOT NULL,
    parent_n      INT,
    code_archive  BYTEA       NOT NULL,
    score         TEXT,
    evidence      JSONB       NOT NULL DEFAULT '[]',
    run_ids       JSONB       NOT NULL DEFAULT '[]',
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hyperagent_generations_session ON audit.hyperagent_generations(session_id);

CREATE TABLE IF NOT EXISTS audit.hyperagent_history_entries (
    id            SERIAL      PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES audit.attack_runs(id) ON DELETE CASCADE,
    generation_n  INT         NOT NULL,
    entry_type    TEXT        NOT NULL,
    content       TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hyperagent_history_session ON audit.hyperagent_history_entries(session_id);

-- =============================================================
-- SCHEMA: knowledge  — między-atakowa baza wiedzy (katalog + log prób + agregaty)
-- Projekt: docs/knowledge_layer_design.md
-- =============================================================
CREATE TABLE IF NOT EXISTS knowledge.attack_techniques (
    id           SERIAL      PRIMARY KEY,
    name         TEXT        NOT NULL UNIQUE,
    description  TEXT        NOT NULL,
    example      TEXT,
    attack_class TEXT,
    source       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge.attack_attempts (
    id            SERIAL      PRIMARY KEY,
    technique_id  INT         REFERENCES knowledge.attack_techniques(id) ON DELETE SET NULL,
    objective_id  TEXT,
    vector_id     TEXT,
    situation_text TEXT,
    embedding     vector(768),
    payload       TEXT,
    outcome       TEXT,
    depth         REAL,
    score         REAL,
    run_id        UUID        REFERENCES logs.runs(run_id) ON DELETE SET NULL,  -- referencja, nie kopia
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_attack_attempts_ctx ON knowledge.attack_attempts(objective_id, vector_id);

CREATE TABLE IF NOT EXISTS knowledge.attack_strategies (
    id            SERIAL      PRIMARY KEY,
    technique_id  INT         NOT NULL REFERENCES knowledge.attack_techniques(id) ON DELETE CASCADE,
    objective_id  TEXT,
    vector_id     TEXT,
    situation_centroid vector(768),
    best_example  TEXT,
    success_count INT         NOT NULL DEFAULT 0,
    attempt_count INT         NOT NULL DEFAULT 0,
    mean_score    REAL        NOT NULL DEFAULT 0,
    best_score    REAL        NOT NULL DEFAULT 0,
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (technique_id, objective_id, vector_id)
);
CREATE INDEX IF NOT EXISTS idx_attack_strategies_ctx ON knowledge.attack_strategies(objective_id, vector_id);

-- =============================================================
-- SCHEMA: recon  — benchmark podatności ATAKOWANEGO modelu (Garak)
-- Projekt: docs/garak_recon_design.md
--
-- Po co: zanim zaatakujemy system agents_blocks, mierzymy podatności samego modelu
-- docelowego narzędziem red-team (Garak/NVIDIA), żeby wiedzieć, KTÓRE rodziny
-- jailbreaków na niego działają. To „warstwa wiedzy o podatnościach" — docelowo
-- zasila wybór technik w pętli AutoDAN (na razie samodzielna warstwa + API zapytań).
--
-- Tool-agnostyczny (kolumna `tool`): dziś 'garak', w przyszłości np. 'pyrit' bez migracji.
-- W Garaku model ATAKOWANY = generator pod testem (target_model). Osobny model
-- ATAKUJĄCY/red-team (attacker_model) dotyczy tylko probe'ów generatywnych (atkgen) —
-- stąd NULL dla statycznych. „Sami podajemy modele" = oba pola wypełnia uruchamiający.
-- =============================================================
CREATE TABLE IF NOT EXISTS recon.scans (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tool           TEXT        NOT NULL DEFAULT 'garak',     -- 'garak' | (przyszłość) 'pyrit'
    tool_version   TEXT,
    target_model   TEXT        NOT NULL,                     -- model ATAKOWANY (np. gpt-oss:20b)
    target_type    TEXT        NOT NULL DEFAULT 'ollama',    -- generator garak (ollama/openai/rest...)
    attacker_model TEXT,                                     -- red-team/atkgen; NULL gdy probe statyczne
    probes         JSONB       NOT NULL DEFAULT '[]',        -- które probe'y uruchomiono
    command        TEXT,                                     -- pełna komenda (odtwarzalność)
    report_path    TEXT,
    status         TEXT        NOT NULL DEFAULT 'running',   -- running | completed | failed
    error          TEXT,
    meta           JSONB       NOT NULL DEFAULT '{}',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_recon_scans_target ON recon.scans(target_model);

-- Wynik per (probe, detector). failure_rate = (total-passed)/total — gęsta miara
-- podatności (im wyżej, tym bardziej model uległ danej rodzinie jailbreaku).
CREATE TABLE IF NOT EXISTS recon.findings (
    id            SERIAL      PRIMARY KEY,
    scan_id       UUID        NOT NULL REFERENCES recon.scans(id) ON DELETE CASCADE,
    probe         TEXT        NOT NULL,                      -- np. 'dan.DanInTheWild'
    probe_family  TEXT,                                      -- np. 'dan' (agregacja/mapowanie na technikę)
    detector      TEXT        NOT NULL,
    passed        INT         NOT NULL,
    total         INT         NOT NULL,
    failure_rate  REAL        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scan_id, probe, detector)
);
CREATE INDEX IF NOT EXISTS idx_recon_findings_scan   ON recon.findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_recon_findings_family ON recon.findings(probe_family);

-- Pojedyncze trafienia z hitloga: konkretne prompty, które ZŁAMAŁY model — wprost
-- użyteczne payloady (materiał do biblioteki strategii / inspekcji).
CREATE TABLE IF NOT EXISTS recon.hits (
    id            SERIAL      PRIMARY KEY,
    scan_id       UUID        NOT NULL REFERENCES recon.scans(id) ON DELETE CASCADE,
    probe         TEXT        NOT NULL,
    detector      TEXT,
    prompt        TEXT,                                      -- payload, który przeszedł
    output        TEXT,                                      -- odpowiedź modelu (dowód)
    score         REAL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_recon_hits_scan ON recon.hits(scan_id);
