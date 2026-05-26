-- =============================================================
-- GŁÓWNA TABELA INFEKCJI: outputs wszystkich narzędzi MCP
-- Żeby zainfekować narzędzie wystarczy UPDATE na tej tabeli.
-- input_key = NULL oznacza domyślny fallback dla danego narzędzia.
-- =============================================================
CREATE TABLE IF NOT EXISTS tools_outputs (
    id          SERIAL PRIMARY KEY,
    tool_name   VARCHAR(100) NOT NULL,
    input_key   TEXT,                      -- NULL = fallback dla każdego inputu
    output      TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (tool_name, input_key)
);

-- =============================================================
-- SYMULACJA SKRZYNKI MAILOWEJ
-- Wstrzyknięcie: INSERT złośliwego maila → email_agent go przeczyta
-- =============================================================
CREATE TABLE IF NOT EXISTS emails (
    id          SERIAL PRIMARY KEY,
    sender      VARCHAR(200) NOT NULL,
    recipient   VARCHAR(200) NOT NULL DEFAULT 'agent@system.local',
    subject     VARCHAR(500),
    body        TEXT,
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- LOGI DZIAŁAŃ AGENTÓW (do analizy po benchmarku)
-- =============================================================
CREATE TABLE IF NOT EXISTS agent_logs (
    id          SERIAL PRIMARY KEY,
    agent_name  VARCHAR(100),
    task        TEXT,
    steps       JSONB,
    final_output TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);
