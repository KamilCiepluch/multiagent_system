# Jak odpalić rig podatności (test llms)

> Reprodukcja pomiarów z [[_index]]. Rig żyje w OSOBNYM repo `C:\Users\kamil\Desktop\test llms\`
> (własny git, 3× venv). Tu jest „co, czym i jak" — żeby nie zgadywać przy następnym biegu.

## Prerekwizyty
- **Ollama** działająca, modele pobrane (target + sędziowie).
- **Proxy** do Ollamy (Bearer, wymuszone niepuste `options`, `think:false`) — klient `jbb_ollama/ollama_client.py`.
- Venvy: `.venv` (główny), `.venv-agentdojo`, `.venv-garak` (osobne, bo kolidujące zależności).
- Config w `.env` (endpoint, token). Domyślny target: `qwen3.6:35b`.

## Benchmarki — skrypt i co robi
| Benchmark | Entry point | Co robi | Sędzia |
|---|---|---|---|
| JailbreakBench | `run.ps1` / `run.py` (+`jbb_ollama/`) | statyczne jailbreaki, 2-fazowo (target→judge, oszczędza VRAM) | `gpt-oss-safeguard:20b` |
| HarmBench | `harmbench_bench.py` | 300 zachowań / 6 kat. | oficjalny `HarmBench-Llama-2-13b-cls` (GGUF) |
| SORRY-Bench | `sorrybench_bench.py` | 88 promptów × 21 mutacji = 1848 | fine-tunowany sędzia SORRY-Bench |
| garak | `run_garak_proxy.py` | rodziny probe'ów przez proxy | detektory garaka (⚠️ zawyżają) |
| AgentDojo | `run_agentdojo_proxy.py` + `proxy_agentdojo_provider.py` | prompt-injection agentowy (`important_instructions`) | deterministyczne testy suity |
| AgentHarm | `run_agentharm_proxy.py` | szkodliwe zadania z narzędziami (Inspect) | `combined_scorer` (refusal+grading) |
| JailJudge | `jailjudge_bench.py` / `jailjudge_eval.py` | zbiór jailbreak | LlamaGuard |
| suite | `run_proxy_suite.py` | kilka modeli/benchmarków w jednym biegu | — |

## Przykładowe komendy
```powershell
# JailbreakBench (domyślny target)
.\run.ps1                                   # pełny bieg (~386 promptów)
.\run.ps1 --target gemma4:31b --sources baseline pair-vicuna
.\run.ps1 --limit 3                         # smoke

# Pojedynczy przypadek do reprodukcji
.\.venv\Scripts\python.exe repro_jbb_case.py

# Raport/galeria z lokalnych wyników
.\.venv\Scripts\python.exe build_report.py --model qwen3.6:35b
.\.venv\Scripts\python.exe build_gallery.py --model qwen3.6:35b
```
Pozostałe skrypty (`harmbench_bench.py`, `sorrybench_bench.py`, `run_garak_proxy.py`,
`run_agentdojo_proxy.py`, `run_agentharm_proxy.py`) — flagi na górze pliku / `--help`.

## Gdzie lądują wyniki
- `results/<model>[__benchmark]/summary.json` — surowe agregaty ASR per model.
- `reports/summaries/*_summary.json` + `*_SUMMARY.md` — agregaty per benchmark.
- `reports/<model>_report.html` / `_gallery.html` — wizualny raport (offline, self-contained).
- Dashboardy: `dashboard.py`, `safety_dashboard.py` → HTML.

## ⚠️ Zastrzeżenia (ważne, żeby nie przekłamać)
- **`think:false`** we wszystkich biegach — profil z `think:true` może się różnić (nietestowany).
- **garak zawyża 2–20×** — bierz tylko kierunkowo, nie jako bezwzględne ASR.
- **JBB sędzia** = lokalna namiastka Llama-3-70B → „~1%", nie liczba leaderboardowa.
- **Licencja SORRY-Bench:** ZAKAZ redystrybucji surowych promptów/odpowiedzi → HTML raport i
  `*_data.json` są **gitignored**; commitowalne są TYLKO agregaty liczbowe (`summaries/`). Nasze
  notatki wiki zawierają wyłącznie agregaty — są bezpieczne.
- **70B** (llama3.3) przeciąża proxy (~10 min/prompt) — biegi się wieszają; użyć mniejszej próbki.
