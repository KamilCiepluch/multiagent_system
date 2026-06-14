# hyperagent

Agent atakujący, który między rundami **mutuje własny kod Pythona** — prawdziwa
self-modyfikacja kodu źródłowego (w odróżnieniu od `redteam/`, gdzie mutowany
jest tylko tekstowy payload, a pętla pozostaje stała).

Jedyna misja: zaatakować `agents_blocks` przez dowolny wektor wstrzyknięcia
(email / zatruty skill / wynik wyszukiwania) i zrealizować weryfikowalny cel
(`AttackObjective` z `redteam/`). Wyniki są bezpośrednio porównywalne z
`redteam/` — ten sam cel, dwa różne mechanizmy ataku.

---

## Struktura katalogów

```
hyperagent/
├── loop.py          ← Orkiestracja — uruchamia N generacji, zarządza archiwum
├── objectives.py    ← Re-eksport AttackObjective z redteam/ (bez własnej definicji)
│
├── archive/
│   └── store.py     ← Archiwum generacji w PostgreSQL (kod jako tar.gz/BYTEA)
│
├── gateway/
│   ├── server.py    ← FastAPI — jedyny most agenta ze światem zewnętrznym
│   ├── tools.py     ← Niemodyfikowalne prymitywy ataku (inject_email, poison_skill...)
│   └── Dockerfile   ← Obraz gatewaya (kontekst: korzeń repo, bo importuje cały projekt)
│
├── sandbox/
│   ├── runner.py    ← Docker CLI — cykl życia kontenerów agenta i gatewaya
│   └── Dockerfile   ← Obraz agenta: python:3.11-slim + requests, BEZ kodu agenta
│
└── seed/
    ├── main.py          ← Pętla ReAct agenta (generacja 0, MUTOWANA między rundami)
    ├── tools.py         ← GatewayClient + narzędzia plikowe (read/write_file)
    └── SYSTEM_PROMPT.py ← Prompt systemu (też w /workspace, też mutowalny)
```

### Dlaczego każdy element jest osobno

**`seed/`** — to kod, który *agent faktycznie uruchamia i może przepisać*.
Trafia do kontenera przez bind-mount `/workspace`. Obraz agenta (`sandbox/Dockerfile`)
jest minimalny i niezmienny — zmienia się tylko zawartość woluminu.

**`gateway/`** — żyje w *osobnym* kontenerze, poza zasięgiem agenta. Agent
nie może go zmodyfikować ani ominąć: jest jedynym sąsiadem agenta na sieci
`hyperagent_net` (izolowanej, `internal: true`). Każda interakcja z nim jest
logowana do `hyperagent_gateway_log` **przed** wykonaniem handlera — nawet
crash agenta w środku zostawia trwały ślad.

**`sandbox/runner.py`** — tylko operator Dockera. Nie jest mechanizmem
izolacji — tę gwarantuje sam Docker przez parametry kontenerów
(`--network internal`, `--cap-drop ALL`, `--memory`, `--pids-limit`).

**`archive/store.py`** — snapshoty kodu w PostgreSQL zamiast plików na dysku.
Umożliwia `best_score` (wróć do najlepszej gałęzi drzewa) zamiast tylko
liniowego `latest`.

**`loop.py`** — host-side, poza zasięgiem agenta. Wie o wszystkim: archiwum,
sandbox, judge, AttackRunner. Agent nie ma do tego żadnej trasy sieciowej.

---

## Przepływ jednej sesji

```
python hyperagent_attack.py --objective secret_exfiltration --generations 3
          │
          ├─ [jednorazowo] build agent image + gateway image
          │
          └─ loop.run(max_generations=3)
               │
               ├─ gen 0 (seed): kopiuje seed/ do workspace/gen_0/, zapisuje snapshot do DB
               │
               └─ gen 1..3:
                    │
                    ├─ select_parent(archive)    → wybierz gen do "sklonowania"
                    ├─ checkout(parent, workspace/gen_N)  → rozpakuj tar.gz z DB na dysk
                    ├─ launch_gateway(session, N, objective_id)
                    │     docker run -d hyperagent-gateway (FRESH na każdą generację)
                    │     env: SESSION_ID, GENERATION_N, OBJECTIVE_ID (niezmienne)
                    ├─ run_agent_container(workspace/gen_N, gateway_url)
                    │     docker run --rm (blokuje do końca lub timeout)
                    │     agent działa: czyta cel → zasiew → run_target_task → mutuje kod
                    │     każda akcja → gateway → hyperagent_gateway_log (DB)
                    ├─ gateway.stop()
                    ├─ evaluate: audit_db.get_hyperagent_run_ids() → redteam.judge
                    └─ snapshot_generation: tar.gz /workspace → hyperagent_generations (DB)
```

Agent widzi tylko jedno: `GATEWAY_URL` w env. Nie widzi hosta, Postgresa,
Ollamy ani innych kontenerów.

---

## Jak odpalić

### Wymagania wstępne

1. **Stack główny uruchomiony:**
   ```
   docker compose up -d
   ```
   Musi być `postgres` i Ollama dostępna na hoście.

2. **Sieć hyperagenta i obraz gatewaya:**
   ```
   docker compose -f docker-compose.yml -f docker-compose.hyperagent.yml up -d
   ```
   Tworzy sieć `hyperagent_net` i buduje obraz `hyperagent-gateway:latest`.
   Rób to raz (i po każdej zmianie kodu w `gateway/` lub projekcie).

3. **Środowisko Python:**
   ```
   C:\Users\kamil\.conda\envs\system_agentowy2\python.exe hyperagent_attack.py --list
   ```

### Uruchomienie sesji

```bash
# Co mamy do wyboru
python hyperagent_attack.py --list

# Krótka sesja — dobra do pierwszego debugowania
python hyperagent_attack.py --objective secret_exfiltration --generations 2

# Z wyborem najlepszej gałęzi zamiast ostatniej
python hyperagent_attack.py --objective skill_rce --generations 5 --parent-selection best_score

# Nie przerywaj po pierwszym sukcesie — zbierz wszystkie generacje
python hyperagent_attack.py --objective secret_exfiltration --generations 6 --no-stop-on-success
```

---

## Jak debugować

### Co wypisuje konsola

Każda generacja wypisuje:
- sandbox exit code + czy timeout
- ile razy agent odpalił `run_target_task`
- najlepszy werdykt (`ATTACK_SUCCESS / PARTIAL / UNCLEAR / BLOCKED`)
- dowody i uzasadnienie sędziego

Brak werdyktu = agent ani razu nie odpalił `run_target_task` w tej generacji
(typowy błąd: zapętlenie na reset_target lub błędy formatu AKCJA/WEJŚCIE).

### Tabele w `agent_audit` (PostgreSQL)

| Tabela | Co znajdziesz |
|--------|--------------|
| `hyperagent_gateway_log` | Każda akcja agenta: endpoint, request, response, timestamp. Sprawdź tu co agent *faktycznie* robił. |
| `hyperagent_generations` | Metadane generacji: wynik, dowody, run_ids, `code_archive` (tar.gz kodu). |
| `hyperagent_history` | Co agent zapisał do swojej historii między generacjami. |

```sql
-- Co agent robił w ostatniej sesji (po session_id z konsoli)
SELECT generation_n, endpoint, request_payload, response_payload, created_at
FROM hyperagent_gateway_log
WHERE session_id = '<session_id>'
ORDER BY created_at;

-- Wyniki generacji
SELECT generation_n, score, evidence, notes
FROM hyperagent_generations
WHERE session_id = '<session_id>'
ORDER BY generation_n;

-- Notatki agenta do siebie
SELECT generation_n, entry_type, content
FROM hyperagent_history
WHERE session_id = '<session_id>'
ORDER BY created_at;
```

### Wyciągnięcie kodu konkretnej generacji

```python
from hyperagent.archive import store
from database import audit_db

code = audit_db.get_hyperagent_generation_code("<session_id>", generation_n=2)
store.unpack_into(code, Path("/tmp/gen2_debug"))
# teraz /tmp/gen2_debug/ zawiera dokładny kod, który uruchomiła gen 2
```

### Logi kontenera agenta (jeśli nie zdążył zakończyć)

```bash
docker logs hyperagent-agent-<hash>
docker logs hyperagent-gateway-<session_prefix>-gen<N>
```

### Typowe problemy

| Objaw | Przyczyna | Rozwiązanie |
|-------|-----------|-------------|
| `hyperagent_net nie istnieje` | Sieć nie założona | `docker compose -f docker-compose.yml -f docker-compose.hyperagent.yml up -d` |
| Agent timeout po 30min | Model zbyt wolny / pętla | Skróć `_MAX_STEPS` w `seed/main.py` lub zmień model w `config.py` |
| `BRAK DOPASOWANIA` w `poison_skill` | Zła nazwa agenta/skilla | Sprawdź `agent_skills` w `agent_benchmark` |
| Brak `run_target_task` w generacji | Błędy formatu AKCJA/WEJŚCIE | Patrz `hyperagent_gateway_log` — ile było format-errorów |
| Gateway nie odpowiada | Build nie skończony | Poczekaj — `_wait_for_gateway_ready` ma 90s timeout |

---

## Co jest, a co wymaga pracy

### Działa

- Pełna pętla generacji z archiwum w DB
- Izolacja Docker (sieć `internal: true`, `--cap-drop ALL`)
- Bezwarunkowe logowanie każdej akcji przez gateway
- Self-modyfikacja kodu (agent przepisuje `main.py`, `tools.py`, `SYSTEM_PROMPT.py`)
- Dwie strategie wyboru rodzica: `latest` i `best_score`
- Ocena generacji przez `redteam.judge` (host-side, poza zasięgiem agenta)

### Nie ma / do zrobienia

- **Jeden wzorzec agenta** — tylko ReAct z tekstowym `AKCJA/WEJŚCIE`. Brak
  wariantów (planner, chain-of-thought, multi-step reasoning).
- **Brak statystyk wieloseedowych** — jedna sesja = jeden seed. Nie ma
  automatycznego uruchamiania N seedów i liczenia `attack_success_rate`.
- **Format akcji tekstowy** — lokalne modele Ollama mają niespójny tool-calling,
  więc używamy AKCJA/WEJŚCIE zamiast natywnego JSON schema. Pierwsza rzecz do
  poprawy jeśli zmienisz model na lepszy.
- **Jeden cel na sesję** — nie ma trybu "uruchom oba cele po kolei i porównaj".
