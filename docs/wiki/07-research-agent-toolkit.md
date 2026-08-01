# Research agent + KB toolkit — how to use

> Praktyczny przewodnik po prostym systemie agentowym: research-agent nad bazą `fake_internet`,
> mini-system czatu z wyszukiwaniem, oraz narzędzia do budowania/oglądania/wersjonowania bazy
> wiedzy. Powiązane: [[01-agent-system]] (runtime), [[06-search-agent-verification]] (jak
> dowiedliśmy groundingu), kod w `agents/`, `database/`, `interactive/`.

Wszystko przez lokalny stack / proxy Ollamy (model z `.env`, domyślnie `qwen3.6:35b`; Bearer +
sanitizer w `llm_factory`). Środowisko: conda `system_agentowy2`.

## Elementy i komendy

**Świat wiedzy (`fake_internet`)** — osobna baza Postgres, tabela `pages(category, topic, title,
content, is_sensitive)`.
```
python -m database.internet_db            # utwórz bazę + tabelę + seed (idempotentne)
```

**Search agent** (`SearchSimAgent`, na `BaseAgent`) — szuka w bazie: classify → search → read.
```
python -m agents.search_sim_agent "why does mars look red?"
```

**Mini-system: czat + research (agent-as-tool)** — chat-agent z pamięcią i narzędziem `research`,
które sam wywołuje, gdy uzna, że trzeba szukać. Bez routera, bez skill-gate/ról.
```
python -m interactive.mini_system         # REPL: /reset /history /exit
```

**Podgląd bazy (GUI przeglądarkowe, samodzielny HTML)** — filtr kategorii, wyszukiwarka,
toggle „sensitive only".
```
python -m interactive.kb_viewer                       # z żywej bazy, otwiera w przeglądarce
python -m interactive.kb_viewer --from data/kb/unsafe.json   # podgląd wprost z pliku wersji
```

**Backup / restore + wersje świata** — przenośny, edytowalny JSON.
```
python -m database.kb_backup dump data/kb/canary.json     # zrzut świata do pliku
python -m database.kb_backup load data/kb/canary.json     # wczytanie (TRUNCATE + wgraj)
python -m database.kb_backup load data/kb/extra.json --append   # domieszanie
```
Wersje trzymamy w `data/kb/` (gitignore): `canary.json` (z martwymi canary) i `unsafe.json`
(czysta baza do ręcznego wypełnienia). Przełączanie wersji = `load <plik>`.

**Canary „hazard"** — strony wyglądające na instrukcje szkody, ale OPERACYJNIE MARTWE (fikcyjne
składniki; do testu, czy agent je zrelacjonuje). Autorskie, nie z modelu.
```
python -m database.canary_hazards           # wgraj
python -m database.canary_hazards --remove  # usuń
```

**Generowanie wpisów modelem** — trzy fronty do tego samego:
```
python -m database.generate_pages       # skrypt: stałe u góry pliku (model, kategorie, DRY_RUN)
python -m interactive.kb_studio          # konsola: człowiek w pętli, akceptacja per wpis
python -m interactive.kb_studio_gui      # GUI: karty edytowalne, Save/Regenerate/Remove
```
Nic nie ląduje w bazie bez akceptacji (konsola/GUI) lub `DRY_RUN=False` (skrypt). `is_sensitive`
liczone z kategorii (`SENSITIVE_CATEGORIES` w `internet_db`).

**Benchmark weryfikacyjny** — 4 warstwy (baseline/extended/grounding/security), pełny trace.
```
python -m agents_benchmark.search_sim_agent.run [--layer baseline|extended|security|grounding]
```
Szczegóły i wyniki (38/38, dowód groundingu): [[06-search-agent-verification]].

## Typowy przepływ
1. `internet_db` (seed) → 2. wzbogać bazę (`kb_studio`/`kb_studio_gui`) → 3. `kb_viewer` (obejrzyj)
→ 4. `kb_backup dump` (zrób wersję) → 5. `mini_system` (rozmawiaj z systemem) →
6. `agents_benchmark…run` (zmierz) / red-team (patrz [[05-attack-experiments]]).
