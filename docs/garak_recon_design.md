# Warstwa recon — benchmark podatności atakowanego modelu (Garak)

## Po co

Ataki AutoDAN-Turbo na agents_blocks ledwo przebijają ostatnią warstwę obrony (ASR ~1/8).
Pomysł na ulepszenie: **zanim zaatakujemy, zmierzyć podatności samego modelu docelowego**
narzędziem red-team [Garak (NVIDIA)](https://github.com/NVIDIA/garak), żeby wiedzieć, które
rodziny jailbreaków na niego działają — i tę wiedzę docelowo wykorzystać do priorytetyzacji
technik w pętli ataku.

Garak traktujemy jako **benchmark atakowanego modelu** (ma natywny generator Ollama).
PyRIT na razie pomijamy — schemat jest tool-agnostyczny (kolumna `tool`), więc da się go
dołożyć później bez migracji.

## „Kto kogo atakuje"

W Garaku model **ATAKOWANY** to *generator pod testem* (`target_model`, np. `gpt-oss:20b`).
Osobny model **ATAKUJĄCY/red-team** (`attacker_model`) istnieje tylko dla probe'ów
generatywnych (np. `atkgen`); większość probe'ów to statyczne prompty z biblioteki — wtedy
`attacker_model` jest NULL. Oba modele podaje uruchamiający (CLI/env).

**Wpięcie modelu atakującego (atkgen).** Domyślnie `atkgen` używa małego red-teamu GPT-2
(`garak-llm/attackgeneration-toxicity_gpt2`). Żeby red-teamem był NASZ model (np.
`qwen3.6-uncensored:27b` na Ollamie), `garak_runner` dokłada `--probe_options` nadpisujący
`atkgen.Tox.red_team_model_type`=`ollama.OllamaGeneratorChat` (forma moduł.Klasa wymagana
przez garaka) + `red_team_model_name`, czyści domyślny `red_team_model_config` (ma `hf_args`
pod GPT-2) i ustawia `red_team_prompt_template='[query]'` (czysty prompt dla modelu chat).
Dzieje się to TYLKO gdy `--probes` zawiera `atkgen` — przy innych probe'ach `--attacker-model`
zostaje zignorowany (CLI ostrzega).

## Schemat `recon` (w agent_core)

Czwarty schemat obok `logs` / `audit` / `knowledge`. Źródło prawdy: `database/schema_core.sql`
(świeży build tworzy go automatycznie przez docker init → `init_core.sh`). Na działającej
bazie: `psql -d agent_core -f database/migrations/add_recon_schema.sql`.

| Tabela | Treść |
|---|---|
| `recon.scans` | jedno uruchomienie narzędzia: `tool`, `target_model` (atakowany), `target_type` (generator), `attacker_model` (red-team/NULL), `probes`, `command`, `status`, `report_path` |
| `recon.findings` | wynik per (probe, detector): `passed`/`total` + `failure_rate` (= fails/total — gęsta miara podatności), `probe_family` do agregacji |
| `recon.hits` | pojedyncze prompty, które **złamały** model (z hitloga) — wprost użyteczne payloady |

DAL: `database/recon_db.py` (`ScanRepository`, `FindingRepository`, `HitRepository`,
`top_vulnerabilities`). Wzorzec spójny z `database/knowledge_db.py` (pula + `search_path`).

## Pakiet `vuln_recon/`

Garak odpalany jako **subprocess** (`python -m garak ...`) — nie importujemy go w kodzie,
więc ciężka zależność jest odizolowana.

```
config.py         GarakSettings (env GARAK_*): target_model/type, attacker_model, probes…
models.py         Finding / Hit (czyste, bez DB)
report_parser.py  parse_report / parse_hitlog (czyste funkcje, testowalne bez garaka)
garak_runner.py   build_command + run_garak (subprocess; flagi --target_type/--target_name)
ingest.py         scan_and_store: start → run → parse → zapis → finish
run.py            CLI (skan + --list-scans / --show / --top)
```

## Użycie

```bash
pip install -r requirements-recon.txt
psql -U postgres -d agent_core -f database/migrations/add_recon_schema.sql   # jeśli baza już żyje

# skan (zapis do recon.*)
python -m vuln_recon.run --target gpt-oss:20b --probes dan.DanInTheWild
# odczyt wiedzy
python -m vuln_recon.run --list-scans
python -m vuln_recon.run --show <scan_id>
python -m vuln_recon.run --top gpt-oss:20b
```

Zweryfikowane na garak 0.15.1: flagi `--target_type`/`--target_name` (dawne
`--model_type`/`--model_name` deprecated od 0.13.1); generator Ollama = `--target_type ollama`;
wpis raportu `entry_type:"eval"` z polami `passed`/`fails`/`total_evaluated`.

## Następny krok (poza tym etapem)

Most do pętli ataku: mapowanie `probe_family` → techniki `attack_core/knowledge/catalog.py`
i zasilanie wyboru technik realnymi podatnościami celu (`recon_db.top_vulnerabilities`).
