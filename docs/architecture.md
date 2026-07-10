# Architektura systemu agentowego (agents_blocks)

Referencja techniczna: jak działa runtime agentów i orkiestracja. Cel — móc szybko
dociekać „co się stało" bez trzymania narracji w komentarzach kodu. Kod ma być czysty;
tu jest „dlaczego". Aktualizuj przy zmianach architektury.

---

## 1. Mapa: dwa tryby uruchomienia

Oba budowane w [`graph/workflow.py`](../graph/workflow.py); agenci wspólni (`_init_agents`).

| Tryb | Builder | Przepływ | Kto decyduje o delegacji |
|------|---------|----------|--------------------------|
| **Orchestrator** (router 1:1) | `build_workflow()` | START → orchestrate → [terminal\|email\|search] → finalize → END | `Orchestrator.route()` — LLM zwraca 1 słowo |
| **Supervisor** (wieloetapowy) | `build_supervisor_workflow()` | START → supervisor → END | supervisor-LLM sam woła agentów wielokrotnie, w dowolnej kolejności |

Orchestrator to prosty router (jedno zadanie → jeden agent, bez współpracy). Supervisor to
pełny ReAct agent, którego „narzędziami" są inni agenci — to on realizuje scenariusze
wieloetapowe (np. mail → weryfikacja roli → delegacja wykonania).

## 2. Provider LLM

Tylko **Ollama** (lokalny stack). Fabryka: [`llm_factory.build_system_llm()`](../llm_factory.py).
NVIDIA/ChatNVIDIA usunięte 2026-07 (patrz historia gita). Pokrętła w [`config.py`](../config.py):

- `ollama_model` (domyślnie `gpt-oss:20b`), `ollama_num_ctx` (16384 — mały kontekst → model gubi reguły/zapętla),
- `agent_temperature` (0.2 — domyślne ~0.8 Ollamy za wysokie, sypie tool-calle i structured output),
- `capture_thinking` (reasoning do osobnego kanału → agent_logs; wymaga modelu rozumującego),
- `agent_recursion_limit` (100 super-kroków ≈ ~50 tool-calli),
- `completion_guard` (domyślnie **False**, patrz §5),
- `benchmark_dataset` (świat-cel; rejestr `attack_core/runner.py::DATASETS`).

## 3. Cykl życia `Agent.run()` (BaseAgent)

[`agents/base_agent.py`](../agents/base_agent.py). Konstrukcja agenta = `create_agent(llm, tools, system_prompt, middleware=[SkillGate], response_format=RESPONSE_SCHEMA?)`.

Przebieg `run(task)`:

1. **`run_graph_collecting`** — uruchamia graf **strumieniowo (`stream`, nie `invoke`)**, akumulując
   snapshoty stanu. Powód: przy przekroczeniu `recursion_limit` `invoke` rzuciłby `GraphRecursionError`
   i **zgubiłby ground-truth** (faktycznie wykonane tool-calle — np. udany odczyt sekretu). Zamiast tego
   zwraca ostatni stan + `truncated=True`.
2. **`StructuredOutputValidationError`** (structured output niezgodny ze schematem) — **nie crashuje**:
   dołącza surową finalną wiadomość modelu jako fallback (supervisor odczyta rolę/prośbę z treści).
3. Z ostatniego stanu: `messages` → `_extract_tool_calls` (parowanie AIMessage.tool_calls↔ToolMessage),
   `structured_response` → `last_structured` → `_render_structured` (patrz §4).
4. Logowanie DWIEMA ścieżkami:
   - **RunLogger** (obserwowalność/trace, schemat `logs` / agent_logs) — callbacki + start/finish agenta,
   - **`create_agent_log`** (audyt, schemat `audit` / agent_audit) — forensika, `show_run.py`.

`run()` **zawsze zwraca `str`** (nigdy obiektu Pydantic). Zob. §4.

## 4. Structured output: `RESPONSE_SCHEMA` + `_render_structured`

Każdy agent wykonawczy ma `RESPONSE_SCHEMA` (Pydantic): `SearchAnswer`, `TerminalAnswer`, `EmailAnswer`.

- Na Ollamie idzie **natywny structured output** (`response_format=SCHEMA`, ProviderStrategy) → model
  produkuje **zwalidowany obiekt** w `state['structured_response']`, w JEDNYM przebiegu (bez
  stratnego „post-hoc re-formatu" drugim wywołaniem LLM).
- **Dlaczego na zewnątrz string, nie obiekt:** konsumentem jest supervisor-LLM, który woła agentów jak
  narzędzia — wynik narzędzia (`ToolMessage`) MUSI być tekstem. Obiekt i tak trzeba zserializować.
- `_render_structured(obj, fallback, tool_calls)` = **deterministyczny render obiekt→string** (bez 2.
  wywołania LLM). Obiekt zostaje odłożony w `agent.last_structured` (inspekcja; `harness.build_pipeline`
  zwraca referencje agentów właśnie po to).

Rendery per agent:

| Agent | Render (skrót) |
|-------|----------------|
| search | `odpowiedz` + `Źródła:` + `[Poza zakresem]` + `[eskalacja]` |
| terminal | `odpowiedz` + `Komendy:` + `[Odmowa: …]` + `[Eskalacja]` |
| **email** | `odpowiedz` + **`Użytkownik: <email> (rola: X)`** + **`[DO REALIZACJI → <agent>]: <prośba>`** + `Wykonane:` + `[Odmowa]` + `[Eskalacja]` |

**Email jest kluczowy** ([`email_agent.py::_render_structured`](../agents/email_agent.py)):
- nadawcę i rolę bierze **deterministycznie z wyniku `get_contact_role`** (źródło prawdy), nie z pola,
  które wpisał model → propaguje PRAWDZIWĄ rolę, nie konfabulację;
- składa marker **`[DO REALIZACJI → terminal_agent]`**, który łapie regex supervisora (§5).

Agent BEZ `RESPONSE_SCHEMA` → `_render_structured` domyślnie zwraca `fallback_text` (zero zmian).

## 5. Orkiestracja i handoff (Supervisor)

[`agents/supervisor.py`](../agents/supervisor.py). Protokół pracy jest w `SUPERVISOR_PREAMBLE`
(KROK 0 tożsamość → 1 dekompozycja → 2 delegacja wg domeny → 3 ocena → 4 dokończenie łańcucha →
5 finalna odpowiedź). System prompt budowany dynamicznie z listy agentów (NAME + DESCRIPTION).

Mechanizmy kodowe:
- **`_make_agent_tool`** — zamienia agenta w `StructuredTool`. `_TaskInput` ma `extra="allow"`: gdy
  supervisor przekaże kontekst/rolę jako OSOBNY argument (nie w `task`), doklejamy go na początek
  zadania, żeby rola dotarła do egzekutora (inaczej egzekutor traktuje zlecającego jak viewera).
- **Handoff dwuhopowy:** email robi triaż (rola + prośba + sugerowany egzekutor jako marker
  `[DO REALIZACJI → X]`); supervisor MUSI oddelegować 2. hop do wskazanego egzekutora z kontekstem roli.
- **Completion-guard** (`_complete_dropped_handoff`) — **domyślnie WYŁĄCZONY** (`completion_guard=False`).
  Siatka na wariancję: gdy email zwrócił marker, a supervisor nie wywołał egzekutora, dopina 2. hop
  deterministycznie (regex `_HANDOFF_RE` + `_USERCTX_RE` z prozy). Fail-open (nigdy nie wywraca
  przebiegu). Bezpieczny dla deny — egzekutor sam egzekwuje uprawnienia (rola/plik poufny/blacklist).
  Wyłączony celowo: o delegacji ma decydować MODEL, żeby test modeli był rzetelny.

## 6. SkillGate (wymuszanie procedur)

[`agents/skill_gate.py`](../agents/skill_gate.py), middleware `before_agent`, domyślne dla WSZYSTKICH
agentów (`BaseAgent._build_middleware`).

- **Wymusza `list_skills`:** Ollama IGNORUJE `tool_choice`, więc katalog procedur wstrzykujemy jako
  ROZWIĄZANE wywołanie `list_skills` w historii (AIMessage tool_call + ToolMessage z katalogiem), tak
  jakby agent wykonał je sam. To jedyny deterministyczny sposób na Ollamie.
- **`load_skill` zostaje autonomiczny** — agent sam decyduje, którą procedurę wczytać (i czy w ogóle).
- **Fail-open:** agent bez procedur → `None` (nic nie wstrzykujemy).
- Dedup w base_agent: powtórne `list_skills`/`load_skill` (ta sama nazwa) w jednym przebiegu jest
  ucinane — inaczej model się zapętla.

## 7. Znane kompromisy / kierunki (do rozważenia)

- **object-vs-string w guardzie.** Completion-guard reparsuje wyrenderowaną PROZĘ regexem, żeby odzyskać
  egzekutora i kontekst użytkownika (round-trip obiekt→string→regex). Dla kanału LLM proza jest właściwa
  (model lepiej wykonuje zdanie-dyrektywę niż JSON), ale kod deterministyczny mógłby czytać
  `agent.last_structured` wprost (`structured.sugerowany_agent`, `structured.rola_uzytkownika`) — bez
  regexu i bez ryzyka rozjazdu formatu markera między renderem a regexem. Hybryd: proza dla modelu,
  obiekt dla guardu. Nie pali się (guard domyślnie off), ale to najkruchsze ogniwo.
- Marker `[DO REALIZACJI → X]` żyje w DWÓCH miejscach (render email + regex supervisor) — muszą trzymać
  identyczny format.

## 8. Gdzie czego szukać przy debugowaniu

- **Ślad przebiegu / kolejność agentów, reasoning:** RunLogger → agent_logs (schemat `logs`).
- **Audyt (tool_calls, final_output per agent):** `create_agent_log` → agent_audit (schemat `audit`);
  render forensiczny: `show_run.py`.
- **Co agent NAPRAWDĘ wykonał** (nawet przy zapętleniu/truncation): `_extract_tool_calls` z `messages`
  — ground-truth zachowany dzięki `run_graph_collecting` (§3).
- **Surowy obiekt structured** po runie: `agent.last_structured` (pipeline z `harness.build_pipeline`).
- **Kluczowe pliki:** `agents/base_agent.py` (runtime), `agents/supervisor.py` (orkiestracja),
  `agents/skill_gate.py` (procedury), `llm_factory.py` + `config.py` (model i pokrętła),
  `graph/workflow.py` (tryby).
