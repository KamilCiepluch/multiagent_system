-- =============================================================
-- HYPERAGENT LOGS DB SCHEMA — hyperagent_logs
-- Dedykowana baza obserwowalności pętli `hyperagent_email` (samodoskonalący
-- się atakujący przez treść maila). NIEZALEŻNA od agent_audit/agent_logs:
-- hyperagent CZYTA przebieg atakowanego systemu z tamtych baz, więc WŁASNE
-- logi (co zrobił, co trafiło do deterministycznych prymitywów ataku i co te
-- prymitywy zwróciły) trzyma osobno.
--
-- NIE logujemy tu tego, co dzieje się WEWNĄTRZ atakowanego systemu — to jest
-- już w agent_logs/attack_agent_logs i wskazujemy na nie przez generations.run_id.
--
-- Tworzenie bazy:
--   createdb -U postgres hyperagent_logs
--   psql -U postgres -d hyperagent_logs -f database/schema_hyperagent_logs.sql
--
-- Warstwy odporności (patrz hyperagent_email/gen_logger.py):
--   * w pełni odporne na self-modyfikację (host-side): sessions, generations,
--     primitive_calls — wołane wyłącznie z loop.py, agent nie ma jak ich ominąć,
--   * best-effort (host-bound callback): agent_llm_turns — wnętrze agenta LangChain.
-- =============================================================

-- =============================================================
-- RESET — usuwa wszystko i tworzy od nowa (kolejność wg zależności FK)
-- =============================================================
DROP TABLE IF EXISTS agent_llm_turns  CASCADE;
DROP TABLE IF EXISTS primitive_calls  CASCADE;
DROP TABLE IF EXISTS generations      CASCADE;
DROP TABLE IF EXISTS sessions         CASCADE;

-- =============================================================
-- SESSIONS — jedno uruchomienie loop.main (zakres generacji)
-- attack_id jest LUŹNYM cross-refem do agent_audit.attack_runs (TEXT, bez FK) —
-- baza ma być niezależna od agent_audit, którą można w przyszłości zmienić/usunąć.
-- =============================================================
CREATE TABLE sessions (
    session_id           UUID        PRIMARY KEY,
    attack_id            TEXT,                              -- cross-ref do agent_audit (opcjonalny)
    model                TEXT,                              -- typ LLM napędzającego hyperagenta
    objective            TEXT,                              -- opis celu ataku
    start_gen            INT,                               -- pierwsza generacja tej sesji
    planned_generations  INT,                               -- ile generacji zaplanowano
    status               TEXT        NOT NULL DEFAULT 'running', -- running | completed | error
    final_outcome        TEXT,                              -- succeeded | blocked | partial | unknown
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at          TIMESTAMPTZ
);

-- =============================================================
-- GENERATIONS — jedna generacja (pełny cykl życia hosta:
-- adopcja self-mod -> payload -> bramka -> inject -> run -> judge)
-- =============================================================
CREATE TABLE generations (
    id                        SERIAL      PRIMARY KEY,
    session_id                UUID        NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    generation_n              INT         NOT NULL,
    status                    TEXT        NOT NULL DEFAULT 'running', -- running | completed | error
    verdict                   TEXT,       -- ATTACK_SUCCESS | BLOCKED | PARTIAL | UNCLEAR | NO_VALID_PAYLOAD | ERROR | UNKNOWN
    -- adopcja self-modyfikacji poprzedniej generacji
    self_mod_adopted          BOOLEAN,                       -- TRUE=przyjęto, FALSE=rollback, NULL=brak danych
    self_mod_rejection_reason TEXT,                          -- powód odrzucenia + rollbacku (gdy adopted=FALSE)
    -- payload wygenerowany przez agenta
    parse_ok                  BOOLEAN,
    parse_error               TEXT,
    attempts                  INT,                           -- ile prób parsowania formatu
    refusal                   BOOLEAN,
    sender                    TEXT,
    subject                   TEXT,
    body                      TEXT,
    rationale                 TEXT,
    raw_response              TEXT,                          -- surowa finalna odpowiedź agenta
    -- bramka hosta
    gate_problem              TEXT,                          -- powód odrzucenia przez bramkę (NULL=przeszła)
    -- ocena
    run_id                    TEXT,                          -- run atakowanego systemu (-> agent_logs/attack_agent_logs)
    judge_reasoning           TEXT,
    evidence                  JSONB,
    host_notice               TEXT,                          -- uwaga przekazana następnej generacji
    error                     TEXT,                          -- traceback wyjątku hosta (gdy status=error)
    started_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at               TIMESTAMPTZ
);

CREATE INDEX idx_gen_session ON generations(session_id);

-- =============================================================
-- PRIMITIVE_CALLS — KLUCZOWA tabela. Każde wywołanie niemodyfikowalnego
-- prymitywu ataku (reset_target / inject_email / run_target_task / …) w obrębie
-- generacji. Wpis input powstaje PRZED wywołaniem, output/error PO — ślad
-- istnieje nawet gdy prymityw rzuci wyjątek. To odpowiedź na pytanie operatora:
-- czy do deterministycznego narzędzia trafiły poprawne dane i co zwróciło.
-- =============================================================
CREATE TABLE primitive_calls (
    id            SERIAL      PRIMARY KEY,
    generation_id INT         NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
    seq           INT         NOT NULL,                      -- kolejność w obrębie generacji (1-based)
    name          TEXT        NOT NULL,                      -- reset_target | inject_email | run_target_task | …
    input         JSONB,                                     -- dokładne kwargs (co trafiło do narzędzia)
    output        JSONB,                                     -- dokładny zwrot (co narzędzie zwróciło)
    is_error      BOOLEAN     NOT NULL DEFAULT FALSE,
    error         TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    duration_ms   INT
);

CREATE INDEX idx_prim_gen ON primitive_calls(generation_id);

-- =============================================================
-- AGENT_LLM_TURNS — wewnętrzna pętla agenta LangChain (best-effort, z callbacku
-- wpiętego w obiekt llm przez hosta). Jedna tura = jedno wywołanie modelu.
-- Wyjścia narzędzi agenta (read_file/write_file/list_files) wracają jako
-- ToolMessage w input_messages KOLEJNEJ tury — cały ReAct da się odtworzyć
-- z samych tur LLM, nawet po przepisaniu workspace/agent.py.
-- =============================================================
CREATE TABLE agent_llm_turns (
    id             SERIAL      PRIMARY KEY,
    generation_id  INT         NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
    seq            INT         NOT NULL,                     -- kolejność tur w obrębie generacji
    attempt_n      INT,                                      -- która próba parsowania formatu (1..MAX)
    input_messages JSONB,                                    -- skrót wiadomości wysłanych do modelu (z ToolMessage)
    output_content TEXT,                                     -- treść AIMessage (finalna odpowiedź modelu)
    thinking       TEXT,                                     -- reasoning/thinking (gdy model rozumujący)
    tool_calls     JSONB,                                    -- narzędzia zażądane przez model (nazwa+argumenty)
    is_error       BOOLEAN     NOT NULL DEFAULT FALSE,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_turn_gen ON agent_llm_turns(generation_id);
