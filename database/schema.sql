-- =============================================================
-- RESET — usuwa wszystko i tworzy od nowa
-- =============================================================
DROP TABLE IF EXISTS agent_logs    CASCADE;
DROP TABLE IF EXISTS emails        CASCADE;
DROP TABLE IF EXISTS email_contacts CASCADE;
DROP TABLE IF EXISTS tools_outputs CASCADE;
DROP TABLE IF EXISTS agent_skills  CASCADE;

-- =============================================================
-- GŁÓWNA TABELA INFEKCJI: outputs wszystkich narzędzi MCP
-- =============================================================
CREATE TABLE tools_outputs (
    id          SERIAL PRIMARY KEY,
    tool_name   VARCHAR(100) NOT NULL,
    input_key   TEXT,
    output      TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (tool_name, input_key)
);

-- =============================================================
-- SKRZYNKA MAILOWA
-- =============================================================
CREATE TABLE emails (
    id           SERIAL PRIMARY KEY,
    sender       VARCHAR(200) NOT NULL,
    recipient    VARCHAR(200) NOT NULL DEFAULT 'agent@system.local',
    subject      VARCHAR(500),
    body         TEXT,
    is_read      BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted   BOOLEAN NOT NULL DEFAULT FALSE,
    thread_id    INTEGER,
    in_reply_to  INTEGER REFERENCES emails(id),
    created_at   TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- BAZA ZWERYFIKOWANYCH I ZABLOKOWANYCH ADRESÓW EMAIL
-- =============================================================
CREATE TABLE email_contacts (
    id             SERIAL PRIMARY KEY,
    email          VARCHAR(255) UNIQUE NOT NULL,
    name           VARCHAR(255),
    is_verified    BOOLEAN NOT NULL DEFAULT FALSE,
    is_blacklisted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- SKILLE AGENTÓW — procedury obsługi zadań
-- =============================================================
CREATE TABLE agent_skills (
    id          SERIAL PRIMARY KEY,
    agent_name  VARCHAR(100) NOT NULL,
    name        VARCHAR(100) UNIQUE NOT NULL,
    description TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- LOGI DZIAŁAŃ AGENTÓW
-- =============================================================
CREATE TABLE agent_logs (
    id           SERIAL PRIMARY KEY,
    agent_name   VARCHAR(100),
    task         TEXT,
    steps        JSONB,
    final_output TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);
