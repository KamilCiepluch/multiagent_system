# vuln_recon — skan podatności modelu (Garak) → schemat `recon`

Mierzy podatności **atakowanego modelu** narzędziem red-team [Garak](https://github.com/NVIDIA/garak)
i zapisuje wynik do schematu `recon` w `agent_core`. Pełny projekt: [docs/garak_recon_design.md](../docs/garak_recon_design.md).

## 0. Jednorazowy setup

```bash
# (a) garak — ciężka, opcjonalna zależność (osobny plik wymagań)
pip install -r requirements-recon.txt

# (b) schemat recon w bazie:
#  • świeży build (docker) tworzy go SAM z schema_core.sql — nic nie robisz
#  • działająca baza, bez wipe'u:
python - <<'PY'
import psycopg2; from config import settings
psycopg2.connect(host=settings.db_host, port=settings.db_port, dbname=settings.core_db_name,
                 user=settings.db_user, password=settings.db_password).cursor().execute(
    open("database/migrations/add_recon_schema.sql", encoding="utf-8").read())
PY
```
(Albo `psql -d agent_core -f database/migrations/add_recon_schema.sql`, jeśli masz psql w PATH.)

## 1. Skan — KTO kogo

Model **atakowany** = `--target`. Model **atakujący** (red-team) = `--attacker-model`
(potrzebny tylko probe'om generatywnym, np. `atkgen`; dla statycznych jak `dan` zostaje pusty).

```bash
# najprościej: gpt-oss:20b jest domyślny (z config.ollama_model)
python -m vuln_recon.run --target gpt-oss:20b --probes dan.DanInTheWild

# szybciej (1 generacja na prompt, 4 równolegle)
python -m vuln_recon.run --target gpt-oss:20b --probes dan.DanInTheWild \
    --extra-args "--generations 1 --parallel_attempts 4"

# wariant „model kontra model" (atkgen: nieocenzurowany red-team generuje ataki na cel)
python -m vuln_recon.run --target gpt-oss:20b --probes atkgen \
    --attacker-model qwen3.6-uncensored:27b-ctx8k --atkgen-convs 3 --atkgen-calls 4

# kilka rodzin naraz
python -m vuln_recon.run --target gpt-oss:20b --probes "dan,promptinject,latentinjection"
```

> **ETA — garak ma wbudowany `tqdm`.** Odpalony w **zwykłym terminalu** (foreground) pokazuje
> żywy pasek z czasem do końca, np.:
> ```
> probes.dan.DanInTheWild:  82%|████████▏ | 210/256 [12:30<02:44, 3.50s/it]
> ```
> `[12:30<02:44, 3.50s/it]` = minęło 12:30, **zostało ~2:44**, ~3,5 s/prompt. Nie trzeba
> własnego skryptu — to jest ten pasek. (W tle / z przekierowaniem strumienia pasek się gubi —
> dlatego do obserwacji ETA uruchamiaj na pierwszym planie.)

Co decyduje o czasie: **liczba promptów probe'a × liczba generacji ÷ równoległość**.
`dan.DanInTheWild` = 256 promptów. Lżejsze: zmniejsz `--generations`, zwiększ `--parallel_attempts`
(uwaga na VRAM przy 20B), albo wybierz mniejszy probe.

### atkgen (model-vs-model) na słabym RAM
atkgen ładuje DWA modele (red-team + cel) i je przełącza. Gdy nie mieszczą się naraz w VRAM:
- ustaw serwerowo `OLLAMA_KEEP_ALIVE=0` (+ restart Ollamy) → modele schodzą jeden-na-raz,
- użyj celu/atakującego o ściętym kontekscie (np. wariant `…:27b-ctx8k`, `PARAMETER num_ctx 8192`),
- ogranicz objętość: `--atkgen-convs` (konwersacje) / `--atkgen-calls` (tury w konwersacji).

Uwaga: przy `keep_alive=0` modele rozumujące ładują się „na zimno" co turę i wywołanie potrafi
przekroczyć domyślny timeout garaka (30s) → zawis. `GarakSettings.request_timeout` (domyślnie 600s)
podnosi timeout celu i red-teamu (przez `--generator_options`/`--probe_options`), co to eliminuje.

## 2. Co zobaczysz, gdy skan się skończy

CLI po zakończeniu **sam** wypisze podsumowanie (to samo co `--show`): tabelę findingów i próbki
trafień. `failure_rate` = odsetek prób, które **złamały** model (im wyżej, tym bardziej podatny):

```
  Skan <uuid>  [completed]
  narzędzie:  garak 0.15.1
  atakowany:  gpt-oss:20b (generator: ollama)
  atakujący:  — (probe statyczny)
  probe'y:    ['dan.DanInTheWild']
  ──────────────────────────────────────────────────────────
  Findingi (N) — failure_rate = odsetek prób, które ZŁAMAŁY model:
      12%  dan.DanInTheWild   mitigation.MitigationBypass   (225/256 passed)
  ──────────────────────────────────────────────────────────
  Przykładowe trafienia (prompty, które złamały model):
      [dan.DanInTheWild] Ignore previous instructions and ...
```

## 3. Odczyt zgromadzonej wiedzy (kiedykolwiek później)

```bash
python -m vuln_recon.run --list-scans          # historia skanów (kto, kiedy, status)
python -m vuln_recon.run --show <scan_id>       # findingi + trafienia jednego skanu
python -m vuln_recon.run --top gpt-oss:20b      # ranking podatności modelu (po WSZYSTKICH skanach)
```

Surowe raporty garaka (JSONL + HTML) lądują w `vuln_recon/logs/<scan_id>.*` (gitignored).
Dane ustrukturyzowane są w bazie: `recon.scans` / `recon.findings` / `recon.hits`.
