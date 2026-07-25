# Manifest graduacji — Element 1: czysty system agentowy → master

Cel: zbudować na `master` świeżą, czystą strukturę zawierającą **wyłącznie runtime agentowy**
(target), bez warstwy ataku/pomiaru. Mechanika: gałąź robocza od `master`, usunięcie starej
struktury mastera, wciągnięcie aktualnych (zrefaktorowanych) plików z `experiment/attack-framework`.
**Commity/merge robisz Ty.**

Zależność zależności zweryfikowana importami: runtime NIE importuje `attack_core`/`audit_db`/
`knowledge_db`/`recon_db`/`hyperagent` (grep = 0). `create_agent_log` jest no-op → schemat `audit`
nietknięty przez rdzeń. Domknięcie kompiluje się czysto (`import graph.workflow, run, world` = OK).

---

## A. Zestaw IN (graduuje na master)

**Runtime (root):** `config.py`, `llm_factory.py`, `ollama_proxy.py`, `run.py`, `world.py`

**Pakiety (całe):** `agents/`, `graph/`, `mcp/`, `commands/`, `tracing/`, `agent_skills/`

**database/ (PODZBIÓR):** `__init__.py`, `db.py`, `models.py`, `logs_db.py`, `skills.py`,
`schema.sql` (świat, baza `agent_benchmark`), `schema_core.sql` (schemat `logs`; tworzy też puste
`audit`/`knowledge`/`recon` — nieszkodliwe, patrz Uwagi)

**seeds/ (tylko dataset default):** `email_agent.sql`, `terminal_agent.sql`, `search_agent.sql`
(+ `seed_data.sql`, `agent_skills_seed.sql` — do przeglądu czy jeszcze używane)

**docs/:** `architecture.md`, `bazy_danych.md`, `wiki/01-agent-system.md` (materiał do LLMWiki)

**Boot:** `.env.example`, `requirements.txt` (przyciąć do zależności runtime — patrz Uwagi),
`pytest.ini`, `docker-compose.yml`, `README.md`, `.gitignore`

**tests/:** tylko testy runtime (agents/graph/mcp/tracing/db) — przejrzeć i odrzucić testy
attack_core/attack_forge.

## B. Zestaw OUT (zostaje w labie / osobna graduacja)
`attack_core/`, `attack_forge/`, `autodan_turbo/`, `jailbreak_lab/`, `vuln_recon/`, `hyperagent*/`,
`payload_attack/`, `scenario_attack_v1/`, `manual_tests/`, `agents_benchmark*/`, `archive/`,
`external/` (gitignored) · `database/{audit_db,knowledge_db,recon_db,hyperagent_logs_db}.py` +
`schema_hyperagent_logs.sql` · `seeds/datasets/attack_v1/` · root-skrypty: `benchmark_*.py`,
`overnight_*.py`, `show_*.py`, `self_improving_attack.py`, `hyperagent_attack.py`, `playground.py`,
`trace*.txt`, `new_trace1`, `podsumowanie.md`, `main.py` (→ zastąpione `run.py`)

---

## C. KROK 0 (WAŻNE) — nowe pliki są tylko w working tree

`run.py`, `world.py`, `docs/wiki/01-agent-system.md` (i `docs/graduation_element1.md`) utworzyłem
teraz i **nie są jeszcze zacommitowane**. `git checkout <branch> -- <ścieżka>` ciągnie tylko treść
ZACOMMITOWANĄ. Zanim ruszysz graduację — zacommituj je na `experiment/attack-framework` (albo skopiuj
z working tree po utworzeniu gałęzi).

## D. Komendy (świeża gałąź od mastera)

```bash
# 1. gałąź robocza od czystego mastera
git switch master
git switch -c restructure/clean-core

# 2. usuń starą strukturę mastera, której nie ma w zestawie IN
git rm -r --quiet attack_runner.py redteam/ hyperagent_email/ load_terminal_skills.py \
  benchmark_agents.py benchmark_scenarios.py main.py show_log.py show_run.py \
  playground.py test_terminal_agent.py

# 3. wciągnij runtime z brancha (aktualne, zrefaktorowane wersje)
BR=experiment/attack-framework
git checkout $BR -- config.py llm_factory.py ollama_proxy.py run.py world.py
git checkout $BR -- agents/ graph/ mcp/ commands/ tracing/ agent_skills/
git checkout $BR -- database/__init__.py database/db.py database/models.py \
  database/logs_db.py database/skills.py database/schema.sql database/schema_core.sql
git checkout $BR -- seeds/email_agent.sql seeds/terminal_agent.sql seeds/search_agent.sql
git checkout $BR -- docs/architecture.md docs/bazy_danych.md docs/wiki/ \
  .env.example requirements.txt pytest.ini docker-compose.yml README.md

# 4. przegląd przed commitem
git status
```

## E. Weryfikacja (przed commitem)

```bash
python -c "import graph.workflow, run, world"          # domknięcie zwarte
python -m ruff check .                                  # brak unused w rdzeniu
git grep -nEi 'api[_-]?key|password|secret|token|BEGIN.*PRIVATE' -- . ':!*.example'  # higiena
git ls-files | grep -x '.env' && echo "UWAGA .env w repo!" || echo ".env czysty"
docker-compose up -d && python world.py                 # reset świata
python run.py "Sprawdź maile i streść nowe wiadomości." # żywe LLM — odpalasz Ty
pytest tests/ -q                                        # smoke
```

## F. Uwagi / do decyzji
- **schema_core.sql** tworzy `logs` + puste `audit/knowledge/recon`. Zostawiamy as-is (nieszkodliwe,
  bootstrap `agent_core`). Opcja później: wydzielić `schema_logs.sql` (tylko `logs`) — UWAGA:
  `tracing/run_logger.py:158` już odwołuje się do nieistniejącego `database/schema_logs.sql`
  (pre-existing niespójność; kandydat do sprzątnięcia, poza zakresem elementu 1).
- **requirements.txt** — przyciąć do runtime (`langchain`, `langchain-ollama`, `langgraph`, `pydantic`,
  `pydantic-settings`, `psycopg2-binary`, `httpx`). Zależności recon/ataku (garak itd.) zostają OUT.
- **docker-compose.yml** — zostawić tylko usługę PostgreSQL (agent_benchmark + agent_core); usunąć
  usługi hyperagent/gateway jeśli są.
- **main.py → run.py**: `run.py` jest minimalny — workflow sam mintuje run_id i przez `RunLogger.start`
  woła `logs_db.create_run` (nie duplikujemy tego w entry poincie).
- **world.py**: reset tylko datasetu `default`; `attack_v1` graduuje z warstwą ataku.
