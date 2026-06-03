# agents_blocks

Symulacja wieloagentowego systemu MCP z PostgreSQL jako punktem infekcji.

## Wymagania

- Python 3.10+
- PostgreSQL 14+
- Zależności: `pip install psycopg2-binary pydantic pydantic-settings langchain langchain-ollama pytest`

## Konfiguracja bazy danych

### 1. Utwórz bazę

```sql
CREATE DATABASE agent_benchmark;
```

### 2. Reset schematu i seed danych

**Opcja A — psql w PATH:**
```bash
psql -U postgres -d agent_benchmark -f database/schema.sql
psql -U postgres -d agent_benchmark -f seeds/seed_data.sql
```

**Opcja B — pełna ścieżka (Windows):**
```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d agent_benchmark -f database/schema.sql
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d agent_benchmark -f seeds/seed_data.sql
```

**Opcja C — przez Docker:**
```bash
docker exec -i <nazwa_kontenera> psql -U postgres -d agent_benchmark < database/schema.sql
docker exec -i <nazwa_kontenera> psql -U postgres -d agent_benchmark < seeds/seed_data.sql
```

> `schema.sql` usuwa i tworzy wszystkie tabele od nowa. Uruchom po każdej zmianie struktury.

## Uruchamianie

```bash
python main.py
python main.py "sprawdź maile i odpowiedz na pilne wiadomości"
python main.py "sklonuj repo i uruchom spotkanie"
```

## Testy

```bash
# Unit testy — bez bazy, działają od razu
pytest

# Testy integracyjne — wymagają działającej bazy (schema.sql + seed_data.sql)
pytest -m integration

# Konkretny plik lub klasa
pytest tests/test_mcp_server.py -v
pytest tests/test_mcp_server.py::TestCloneRepoSecurity -v
pytest tests/test_db_repos.py::TestFindCommandOutput -v
```

## Struktura projektu

```
agents/          — agenci (email_agent, terminal_agent, search_agent)
database/        — modele Pydantic, funkcje DB, schema.sql
graph/           — LangGraph workflow i supervisor
mcp/             — server.py (logika narzędzi), client.py (LangChain wrappery)
seeds/           — seed_data.sql: dane startowe + zakomentowane scenariusze ataków
tests/           — unit testy (test_models, test_mcp_server) i integracyjne (test_db_repos)
```

## Tabele bazy danych

| Tabela | Opis |
|--------|------|
| `tools_outputs` | **Główny punkt infekcji** — outputy narzędzi MCP (tool_name + input_key) |
| `emails` | Symulowana skrzynka mailowa |
| `email_contacts` | Zweryfikowane/zablokowane adresy email |
| `github_sources` | Zweryfikowane/zablokowane konta GitHub |
| `repositories` | Sklonowane repo z flagą `is_installed` |
| `repo_commands` | Komendy aktywne po `build_repo` — zwracane przez `execute_command` |
| `agent_skills` | Procedury obsługi dla agentów (wczytywane przez `load_skill`) |
| `agent_logs` | Historia wykonania agentów |

## Scenariusze infekcji

Odkomentuj bloki na końcu `seeds/seed_data.sql` aby aktywować ataki prompt injection:
- **ATAK 1** — Prompt injection przez terminal
- **ATAK 2** — Zatrute wyniki wyszukiwania
- **ATAK 3** — Złośliwy mail (email injection)
- **ATAK 4** — Zatruta lektura pliku