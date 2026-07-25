# Mapa repo — co graduuje na master, a co zostaje w labie

> Materiał źródłowy do LLMWiki + przewodnik migracji. Stan: 2026-07-25.
> Zasada: `master` = czysty, działający podzbiór (system + jak go mierzymy + wyniki). Reszta żyje na
> branchu `experiment/attack-framework` (pełny backup) i graduuje świadomie, element po elemencie.

**Backup / bezpieczeństwo:** pełna działająca wersja = branch `experiment/attack-framework` (+ `origin`).
Stara historia mastera = `archive/legacy-master`. Nic nie ginie przy chudzeniu mastera.

---

## A. JUŻ NA MASTERZE — element 1: czysty rdzeń
`agents/ graph/ mcp/ commands/ tracing/ database/(db,models,logs_db,skills,schema,schema_core)`
`config.py llm_factory.py ollama_proxy.py run.py world.py agent_skills/ seeds/(default)`
`tests/(podzbiór runtime) docs/(architecture,bazy_danych,wiki,graduation)` + boot.

## B. MIGROWAĆ TERAZ — element 2: pomiar (wysoka wartość, ZERO sprzężenia z atakiem)
| Co | Dlaczego | Uwagi |
|----|----------|-------|
| `agents_benchmark/` | jak testujemy system (harness, per-agent cases+seed, e2e) | zależy TYLKO od rdzenia; własny reset (nie AttackRunner) |
| `agents_benchmark_results/` | **źródła info o systemie** (wyniki testów) — świetne pod wiki/Obsidian | curated: zostaw `runs/`; `*/old/` = rozważ odrzucić duplikaty |
| docs pomiarowe | `e2e_model_compare_2026-07-14`, `orchestration_fix_2026-06-28`, `orchestration_langchain_notes` | narracja „system + jak sprawdzany + wyniki" |

## C. MIGROWAĆ PÓŹNIEJ — element 3+: warstwa ataku (działa, ale cięższe + sprzężenie)
- `attack_core/` (runner/judge/goals/severity/injection_points/objectives/primitives/strategies/knowledge) — potrzebuje schematu `audit`.
- `attack_forge/` — najbardziej rozwinięty silnik ofensywny (S1→S2→executor, judge, surfaces).
- `autodan_turbo/` — baseline AutoDAN-Turbo (logi gitignored).
- `jailbreak_lab/` — **KOD** floor modelu; `overnight_logs/` (multi-MB) NIE.
- `vuln_recon/` — recon Garak (logs/ gitignored) + `requirements-recon.txt`.
- `database/(audit_db, knowledge_db, recon_db)` — zasilają je atak/recon (schematy już puste w schema_core).
- `seeds/datasets/attack_v1/` — świat ataku (`world.py` używa `default`).
- docs ataku: `attack_plan`, `attack_analysis_*`, `secret_guard_defense_sweep`, `autodan_*`, `garak_recon_design`, `knowledge_layer_design`, `agent_attack_methods_sources`, `attack_scenarios`.

## D. NIE MIGROWAĆ — lab-only (nie wyszło / dev-only / stare)
- **Linia hyperagenta („średnie", nie wyszło):** `hyperagent/`, `hyperagent_email/`, `hyperagent_attack.py`, `show_hyperagent_email.py`, `database/hyperagent_logs_db.py` + `schema_hyperagent_logs.sql` + `migrations/add_hyperagent_tables.sql` + `docker-compose.hyperagent.yml`.
- **Cudze klony:** `external/` (203M, już gitignored) — NIGDY.
- **Stare podejścia:** `payload_attack/`, `scenario_attack_v1/`, `self_improving_attack.py`, `benchmark_agents.py`, `benchmark_scenarios.py` (zastąpione `agents_benchmark/`), `main.py` (→ `run.py`).
- **Dev/ad-hoc:** `manual_tests/`, `playground.py`, `overnight_atkgen.py`, `show/`, `show_log.py`, `show_run.py`, `trace_run.py`, `check_skill_usage.py`, `test_terminal_agent.py`, `ollama_bearer_test/` (gitignored), `archive/`.
- **Notatki/dumpy:** `trace*.txt`, `new_trace1`, `podsumowanie.md` (część gitignored).

## E. NIGDY (artefakty) — `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`, `*.log`, `overnight_logs/`.

---

## Kolejność graduacji (rekomendacja)
1. ✅ **Element 1** — rdzeń (zrobione).
2. **Element 2** — pomiar: `agents_benchmark/` + `agents_benchmark_results/` + docs pomiarowe. Lekkie, domyka „system + jak mierzymy".
3. **Element 3** — atak core: `attack_core/` + `attack_forge/` (+ audit DB, attack_v1). Największy blok.
4. **Element 4** — okołoatakowe: `autodan_turbo/`, `jailbreak_lab/` (kod), `vuln_recon/` — wg tego, co dalej rozwijamy.
