-- Migration: dodaje run_id, tool_calls, attack_success do agent_logs
-- Uruchom jednorazowo na istniejącej bazie danych.

ALTER TABLE agent_logs
    ADD COLUMN IF NOT EXISTS run_id         UUID,
    ADD COLUMN IF NOT EXISTS tool_calls     JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS attack_success BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_agent_logs_run_id ON agent_logs(run_id);
