-- Observability schema for the mini system. Append-only: nothing here is ever updated in place
-- except closing out a row that is still running (finished_at / final_output / status).
--
-- Shape mirrors the big system (runs -> agent_invocations -> tool_calls) with the conversation
-- layer the mini system actually has: conversations -> turns -> invocations -> tool_calls, plus
-- the raw messages exactly as the model saw them.

CREATE TABLE IF NOT EXISTS conversations (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT        NOT NULL,
    model           TEXT,
    note            TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS turns (
    id                BIGSERIAL PRIMARY KEY,
    conversation_pk   BIGINT      NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index        INT         NOT NULL,
    user_message      TEXT        NOT NULL,
    assistant_message TEXT,
    status            TEXT        NOT NULL DEFAULT 'running',
    error             TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    duration_ms       INT
);
CREATE INDEX IF NOT EXISTS turns_conversation_idx ON turns (conversation_pk, turn_index);

-- parent_id nests the search agent under the chat agent that called it (agent-as-tool)
CREATE TABLE IF NOT EXISTS agent_invocations (
    id           BIGSERIAL PRIMARY KEY,
    turn_id      BIGINT      NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    parent_id    BIGINT      REFERENCES agent_invocations(id) ON DELETE CASCADE,
    agent_name   TEXT        NOT NULL,
    task         TEXT        NOT NULL,
    final_output TEXT,
    status       TEXT        NOT NULL DEFAULT 'running',
    error        TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    duration_ms  INT
);
CREATE INDEX IF NOT EXISTS invocations_turn_idx ON agent_invocations (turn_id);

-- What the agent stood behind, as data rather than prose: {used_page_ids, pages_read}. The first
-- is what the model declared, the second is derived from the read_page calls it actually made.
ALTER TABLE agent_invocations ADD COLUMN IF NOT EXISTS structured JSONB;

CREATE TABLE IF NOT EXISTS tool_calls (
    id            BIGSERIAL PRIMARY KEY,
    invocation_id BIGINT      NOT NULL REFERENCES agent_invocations(id) ON DELETE CASCADE,
    step          INT         NOT NULL,
    tool_name     TEXT        NOT NULL,
    input         JSONB,
    output        TEXT,
    status        TEXT        NOT NULL DEFAULT 'ok',
    error         TEXT,
    duration_ms   INT,
    called_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tool_calls_invocation_idx ON tool_calls (invocation_id, step);

-- The conversation as each model saw it: one row per message an agent produced during a turn.
-- invocation_id says WHICH agent produced it, so the chat agent's dialogue and the search agent's
-- own run are both here without being mixed together.
CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    turn_id      BIGINT      NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    position     INT         NOT NULL,
    role         TEXT        NOT NULL,
    content      TEXT,
    tool_calls   JSONB,
    tool_call_id TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_turn_idx ON messages (turn_id, position);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS invocation_id BIGINT
    REFERENCES agent_invocations(id) ON DELETE CASCADE;
-- which tool a tool-result message came from (a skill gate can inject one nobody called)
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tool_name TEXT;
CREATE INDEX IF NOT EXISTS messages_invocation_idx ON messages (invocation_id, position);
