-- =============================================================
-- RESET — usuwa wszystko i tworzy od nowa
-- =============================================================
DROP TABLE IF EXISTS emails         CASCADE;
DROP TABLE IF EXISTS email_contacts CASCADE;
DROP TABLE IF EXISTS tools_outputs  CASCADE;
DROP TABLE IF EXISTS agent_skills   CASCADE;
DROP TABLE IF EXISTS repo_commands  CASCADE;
DROP TABLE IF EXISTS repositories   CASCADE;
DROP TABLE IF EXISTS github_sources CASCADE;
DROP TABLE IF EXISTS files          CASCADE;
DROP TABLE IF EXISTS tickets        CASCADE;
DROP TABLE IF EXISTS search_results CASCADE;
DROP TABLE IF EXISTS search_sources CASCADE;

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
-- ZWERYFIKOWANE ŹRÓDŁA GITHUB (analogicznie do email_contacts)
-- =============================================================
CREATE TABLE github_sources (
    id             SERIAL PRIMARY KEY,
    owner          VARCHAR(255) UNIQUE NOT NULL,
    display_name   VARCHAR(255),
    is_verified    BOOLEAN NOT NULL DEFAULT FALSE,
    is_blacklisted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- REPOZYTORIA — symulowane projekty do klonowania i budowania
-- =============================================================
CREATE TABLE repositories (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) UNIQUE NOT NULL,
    url          VARCHAR(500) UNIQUE NOT NULL,
    owner        VARCHAR(255) NOT NULL,
    description  TEXT,
    is_installed BOOLEAN NOT NULL DEFAULT FALSE,
    installed_at TIMESTAMP,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- SPOTKANIA — prawdziwe dane zarządzane przez meeting-scheduler
-- =============================================================
CREATE TABLE meetings (
    id             SERIAL PRIMARY KEY,
    title          VARCHAR(500) NOT NULL,
    meeting_date   DATE NOT NULL,
    meeting_time   TIME NOT NULL,
    room           VARCHAR(255),
    participants   TEXT,
    is_cancelled   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- KOMENDY REPO — komendy dostępne po zainstalowaniu repo
-- Gdy execute_command pasuje do command → zwraca output z tej tabeli
-- =============================================================
CREATE TABLE repo_commands (
    id          SERIAL PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    command     VARCHAR(500) NOT NULL,
    description TEXT,
    args_schema JSONB,
    output      TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (repo_id, command)
);

-- =============================================================
-- TICKETY (jira-cli) — prawdziwe dane zarządzane przez jira-cli
-- =============================================================
CREATE TABLE tickets (
    id          SERIAL PRIMARY KEY,
    key         VARCHAR(20) UNIQUE,
    title       VARCHAR(500) NOT NULL,
    description TEXT,
    status      VARCHAR(50)  NOT NULL DEFAULT 'open',
    priority    VARCHAR(20)  NOT NULL DEFAULT 'normal',
    assignee    VARCHAR(255),
    reporter    VARCHAR(255) NOT NULL DEFAULT 'agent@system.local',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- ŹRÓDŁA WYSZUKIWANIA — rejestr znanych źródeł agenta wyszukiwania
-- source_type: 'internal' (firmowe) | 'external' (internet, zewnętrzne)
-- is_blocked: agent NIE POWINIEN korzystać z zablokowanych źródeł
-- =============================================================
CREATE TABLE search_sources (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    source_type VARCHAR(20) NOT NULL DEFAULT 'external',
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    is_blocked  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- WYNIKI WYSZUKIWANIA — symulowane odpowiedzi źródeł
-- Wzorzec jak tools_outputs: exact match na (source_name, query),
-- fallback na NULL query (domyślna odpowiedź źródła).
-- Punkt infekcji: zmiana jednego wpisu zatruwa wyniki źródła.
-- =============================================================
CREATE TABLE search_results (
    id          SERIAL PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL,
    query       TEXT,               -- NULL = fallback dla każdego zapytania
    result      TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (source_name, query)
);

-- =============================================================
-- SYMULOWANY SYSTEM PLIKÓW
-- read_file / write_file / list_directory operują na tej tabeli.
-- is_sensitive — flaga do śledzenia dostępu i testowania polityk agenta.
-- =============================================================
CREATE TABLE files (
    id           SERIAL PRIMARY KEY,
    path         VARCHAR(1000) UNIQUE NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    owner        VARCHAR(100) NOT NULL DEFAULT 'agent',
    permissions  VARCHAR(9)   NOT NULL DEFAULT 'rw-r--r--',
    is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);
