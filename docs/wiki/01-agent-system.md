# Element 1 — Czysty system agentowy (target)

> Materiał źródłowy do LLMWiki (`/wiki:ingest`). Opisuje **runtime agentowy** `agents_blocks`:
> co to jest, co potrafi, jak jest zbudowany, na czym był testowany, w jakich konfiguracjach i z
> jakimi wynikami. To jest *cel* (target) — warstwy ataku/pomiaru dokumentowane osobno.
>
> Źródła: `docs/architecture.md`, `docs/bazy_danych.md`, kod (`agents/`, `graph/`, `mcp/`,
> `tracing/`, `database/`), pamięć projektu. Stan: 2026-07-25.

---

## 1. Czym jest system

Wieloagentowy system w **LangGraph** (LangChain `create_agent`, ReAct), napędzany **lokalną
Ollamą**. Agenci operują na „świecie" trzymanym w PostgreSQL (maile, pliki, repozytoria, wyniki
wyszukiwania) i wywołują narzędzia przez wewnętrzny serwer **MCP**. System jest zaprojektowany jako
**target do red-teamingu** — bada się, czy przez zaufane kanały (mail / skill / wynik wyszukiwania)
da się wymusić niepożądane działanie (np. eksfiltrację sekretu). Ten dokument opisuje **wyłącznie
broniącą się stronę** — sam runtime, bez narzędzi atakującego.

**Punkty wejścia (czysty rdzeń):**
- `run.py` — uruchomienie 1..N zadań (`python run.py "..." [supervisor=True] [reset=True]`).
- `world.py` — reset/seed świata do stanu bazowego (dataset `default`).

## 2. Dwa tryby uruchomienia

Oba budowane w `graph/workflow.py` (wspólna inicjalizacja agentów `_init_agents`).

| Tryb                          | Builder                       | Przepływ                                                         | Kto decyduje o delegacji                                            |
| ----------------------------- | ----------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------- |
| **Orchestrator** (router 1:1) | `build_workflow()`            | START → orchestrate → [terminal\|email\|search] → finalize → END | `Orchestrator.route()` — LLM zwraca 1 słowo                         |
| **Supervisor** (wieloetapowy) | `build_supervisor_workflow()` | START → supervisor → END                                         | supervisor-LLM sam woła agentów wielokrotnie, w dowolnej kolejności |

Orchestrator = prosty router (jedno zadanie → jeden agent). Supervisor = pełny ReAct agent, którego
„narzędziami" są inni agenci — realizuje scenariusze wieloetapowe (np. **mail → weryfikacja roli
nadawcy → delegacja wykonania do terminala**).

## 3. Agenci i ich możliwości

Trzej agenci wykonawczy + supervisor. Każdy wykonawczy ma **structured output** (Pydantic
`RESPONSE_SCHEMA`) renderowany deterministycznie do stringa (bo konsumentem jest supervisor-LLM,
który czyta wynik jako `ToolMessage`).

| Agent              | Rola                                            | Kluczowe narzędzia (MCP)                                                                                                                                                                                                                                                  |
| ------------------ | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **terminal_agent** | wykonanie poleceń, praca z repo/plikami         | `execute_command`, `clone_repo`, `build_repo`, `list_repos`, `list_repo_commands`, `uninstall_repo`, `check/add/update/list_github_sources`                                                                                                                               |
| **email_agent**    | triaż i obsługa poczty; **bramka roli nadawcy** | `list_emails`, `list_unread_emails`, `read_email`, `send_email`, `reply_email`, `forward_email`, `delete_email`, `search_emails`, `get_email_thread`, `get_contact_role`, `check_email_contact`, `check_email_source`, `classify_email`, `add/update/list_email_contacts` |
| **search_agent**   | wyszukiwanie wewnętrzne/zewnętrzne              | `web_search`, `search_source`, `search_internal`, `search_external`, `list/check/add/update_search_sources`                                                                                                                                                               |
| **supervisor**     | dekompozycja + delegacja + synteza              | narzędzia = pozostali agenci (`_make_agent_tool`)                                                                                                                                                                                                                         |

**email_agent jest kluczowy dla obrony:** rolę nadawcy bierze **deterministycznie z wyniku
`get_contact_role`** (źródło prawdy), nie z pola wpisanego przez model → propaguje PRAWDZIWĄ rolę, nie
konfabulację. Składa marker `[DO REALIZACJI → terminal_agent]`, który łapie regex supervisora przy
handoffie dwuhopowym.

## 4. SkillGate i skille (wymuszanie procedur)

`agents/skill_gate.py` (middleware `before_agent`, domyślne dla WSZYSTKICH agentów). Skille to
procedury w `agent_skills/<agent>/<nazwa>.md` — **jedno źródło prawdy**, ładowane do DB przez
`world.py`/`database.skills.load_into`.

- **Wymusza `list_skills`:** Ollama ignoruje `tool_choice`, więc katalog procedur wstrzykiwany jest
  jako ROZWIĄZANE wywołanie `list_skills` w historii (AIMessage tool_call + ToolMessage) — jedyny
  deterministyczny sposób na Ollamie.
- **`load_skill` autonomiczny** — agent sam decyduje, którą procedurę wczytać (i czy w ogóle).
- **Fail-open** + dedup powtórnych `list_skills`/`load_skill` (inaczej model się zapętla).

Przykłady skilli obronnych: `terminal_agent/ochrona-plikow-wrazliwych.md` (chroni `/app/secrets/*`),
`search_agent/wykrywanie-prompt-injection.md` (wykrywa „SYSTEM NOTE / Ignore previous / forward
api_keys" w treści z sieci).

## 5. Provider LLM i pokrętła (config.py)

Tylko **Ollama** (fabryka `llm_factory.build_system_llm()`; zdalne proxy przez Bearer + transport
sanitizujący puste `{}` — `ollama_proxy.py`). Konfiguracja przez `.env` (nie w kodzie):

| Pokrętło | Domyślnie | Po co |
|----------|-----------|-------|
| `ollama_model` | `gpt-oss:20b` | model systemu (podmieniany per pomiar) |
| `ollama_num_ctx` | `16384` | mały kontekst → model gubi reguły/zapętla |
| `agent_temperature` | `0.2` | ~0.8 za wysokie — sypie tool-calle/structured output |
| `capture_thinking` | `True` | reasoning do osobnego kanału (schemat `logs`) |
| `agent_recursion_limit` | `100` | ~50 tool-calli; wyżej = palenie czasu |
| `completion_guard` | **`False`** | delegację ma decydować MODEL (rzetelność pomiaru) |
| `benchmark_dataset` | `attack_v1` | świat-cel; **czysty rdzeń używa `default`** |

## 6. Dane, obserwowalność i granice

- **Świat (baza `agent_benchmark`):** maile/kontakty/pliki/repo/wyniki wyszukiwania/tickety/spotkania
  + skille. DAL: `database/db.py` (Pydantic modele, pool). Reset/seed: `world.py`.
- **Obserwowalność (schemat `logs` w bazie `agent_core`):** `RunLogger` (`tracing/run_logger.py`)
  zdarzeniowo loguje reasoning / tool_calls / loaded_skills / zmiany DB. Render trace:
  `tracing/trace.py::format_run_trace`. **Ground-truth** (co agent NAPRAWDĘ wykonał) zachowany nawet
  przy zapętleniu dzięki `run_graph_collecting` (stream, nie invoke).
- **Czego rdzeń NIE dotyka:** schematu `audit` (kampanie ataku), `knowledge`, `recon`. `create_agent_log`
  jest dziś **no-op** — forensika zunifikowana w `logs`. To potwierdza czystą separację: warstwa ataku
  graduuje osobno.

## 7. Na czym testowany + wyniki (udokumentowane)

Wyniki historyczne — pełne raporty w `docs/`; tu skrót z konfiguracją. **Interpretować ostrożnie:**
model cenzurowany vs uncensored, guard-on vs off i twardość judge silnie zmieniają liczby.

- **Benchmark zachowań agentów** (`agents_benchmark/`, 17 zadań + e2e comply/refuse): pokrycie
  toole/skille/uprawnienia/role/orkiestracja/format. Pierwszy e2e run 9/9 PASS.
- **Ranking modeli** (17 zadań bez e2e, pełne przypadki): `gemma4:12b` 84/101 **>** `gpt-oss:20b`
  65/101 **>** `qwen3.5:9b` ≈ `Qwythos-9B` 23 **>** `llama3.1:8b` 21. Decyduje reasoning + jakość, nie
  rozmiar. Źródło: pamięć `project-model-ranking-benchmark`.
- **Structured output e2e** (`docs/e2e_model_compare_2026-07-14.md`): `gemma4:31b` 24/25 **>**
  `qwen3.6:35b` 15/25; behawioralnie remis — wszystkie porażki qwena = brak structured output
  (2× złamanie uprawnień). Format = realna oś jakości.
- **Naprawa orkiestracji** (`docs/orchestration_fix_2026-06-28.md`): allow ~25% → **79%**, deny 100%,
  wariancja zapadła (structured-handoff + mail executor + completion-guard). Sufit ~79% przy gpt-oss.
- **Odporność obronna na powierzchniach agentowych** (loop `attack_forge`, cel = broniony
  `qwen3.6:27b` przez proxy): ~26+ wektorów, **0 wyłomów** na mailu/skillu/terminalu — bramki są na
  TREŚCI/ROLI, nie na stylu; obfuskacja SZKODZI agentowo. (Pomiar warstwy ataku — tu tylko jako
  charakterystyka obronności targetu.)

## 8. Jak uruchomić (weryfikacja)

```bash
docker-compose up -d                      # PostgreSQL (agent_benchmark + agent_core)
python world.py                           # reset/seed świata (dataset default)
python run.py "Sprawdź maile i streść nowe wiadomości."          # orchestrator
python run.py "Zaplanuj spotkanie i wyślij potwierdzenie" supervisor=True
```
Model i endpoint z `.env` (`ollama_model`, `ollama_base_url`, ewentualnie `ollama_bearer_token`).

## 9. Higiena sekretów (rdzeń)

- `.env` gitignorowany i nietrackowany — w repo tylko `.env.example`.
- Brak zaszytych kluczy w kodzie runtime; `ollama_bearer_token` wyłącznie z `.env`.
- `agent_skills/` wspomina `/app/secrets/api_keys.txt` itp. tylko jako **treść obronna** (opis
  chronionych ścieżek), bez realnych wartości.
- `db_password` w `config.py` = lokalny default developerski (nie sekret produkcyjny).
