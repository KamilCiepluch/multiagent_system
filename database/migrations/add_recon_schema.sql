-- =============================================================
-- Migracja: schemat `recon` — benchmark podatności atakowanego modelu (Garak).
--
-- Kanoniczne źródło to database/schema_core.sql (świeży build dostaje recon stamtąd,
-- przez docker init → init_core.sh). Ta migracja jest IDEMPOTENTNA (IF NOT EXISTS) i
-- służy WYŁĄCZNIE do nałożenia schematu na JUŻ DZIAŁAJĄCĄ bazę bez pełnego wipe'u:
--
--   psql -U postgres -d agent_core -f database/migrations/add_recon_schema.sql
--
-- Projekt: docs/garak_recon_design.md
-- =============================================================

CREATE SCHEMA IF NOT EXISTS recon;

CREATE TABLE IF NOT EXISTS recon.scans (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tool           TEXT        NOT NULL DEFAULT 'garak',
    tool_version   TEXT,
    target_model   TEXT        NOT NULL,
    target_type    TEXT        NOT NULL DEFAULT 'ollama',
    attacker_model TEXT,
    probes         JSONB       NOT NULL DEFAULT '[]',
    command        TEXT,
    report_path    TEXT,
    status         TEXT        NOT NULL DEFAULT 'running',
    error          TEXT,
    meta           JSONB       NOT NULL DEFAULT '{}',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_recon_scans_target ON recon.scans(target_model);

CREATE TABLE IF NOT EXISTS recon.findings (
    id            SERIAL      PRIMARY KEY,
    scan_id       UUID        NOT NULL REFERENCES recon.scans(id) ON DELETE CASCADE,
    probe         TEXT        NOT NULL,
    probe_family  TEXT,
    detector      TEXT        NOT NULL,
    passed        INT         NOT NULL,
    total         INT         NOT NULL,
    failure_rate  REAL        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scan_id, probe, detector)
);
CREATE INDEX IF NOT EXISTS idx_recon_findings_scan   ON recon.findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_recon_findings_family ON recon.findings(probe_family);

CREATE TABLE IF NOT EXISTS recon.hits (
    id            SERIAL      PRIMARY KEY,
    scan_id       UUID        NOT NULL REFERENCES recon.scans(id) ON DELETE CASCADE,
    probe         TEXT        NOT NULL,
    detector      TEXT,
    prompt        TEXT,
    output        TEXT,
    score         REAL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_recon_hits_scan ON recon.hits(scan_id);
