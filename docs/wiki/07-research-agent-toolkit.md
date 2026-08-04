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
python -m mini_system.internet_db            # utwórz bazę + tabelę + seed (idempotentne)
```

**Search agent** (`SearchSimAgent`, na `BaseAgent`) — szuka w bazie: search → oceń trafienia → read.
```
python -m mini_system.search_agent "why does mars look red?"
```

**Jak działa samo wyszukiwanie** — retrieval hybrydowy w Postgresie, dwa niezależne kanały
zlewane przez RRF (`database/internet_db.py::search`):
- **leksykalny** — FTS (`tsvector`/`ts_rank_cd`, kolumna generowana `fts` + GIN). Daje stemming
  („octopuses" → „octopus"), wycina stop-wordy i dopasowuje SŁOWA, nie podłańcuchy. Jedyny kanał,
  który niezawodnie trafia rzadkie/wymyślone tokeny — czyli canary.
- **semantyczny** — pgvector, `nomic-embed-text` (768 dim) z lokalnej Ollamy, cosine. Jedyny
  kanał, który trafia parafrazę bez wspólnych słów („rusty orange planet" → Mars).

Progi (`SEM_MAX_DISTANCE`, `LEX_MIN_RANK`) są **zmierzone** na przykładowym korpusie, nie
zgadnięte — bez nich zapytanie off-topic zawsze „coś" znajdzie, bo kanał wektorowy zwraca k
najbliższych niezależnie od sensu. Zapytania jednowyrazowe są zwolnione z progu leksykalnego,
żeby canary nigdy nie wypadło. Embedding liczy się przy KAŻDYM zapisie (`upsert_page(s)` — jedyna
droga zapisu); gdyby model embeddingów był niedostępny, wyszukiwanie degraduje się do samego
kanału leksykalnego zamiast paść. Braki nadrabia `internet_db.backfill_embeddings()`.

Odporność (każdy punkt to zaobserwowany tryb awarii, nie hipoteza):
- **kategoria** rozwiązywana miękko (`resolve_category`): ignoruje wielkość liter, spacje i
  literówki; nieistniejąca → szuka po całym świecie i MÓWI o tym w wyniku, zamiast cicho
  zwrócić zero.
- **tokeny cyfra+litera** rozbijane dodatkowo („52Hz" → `52hz | 52 | hz`), bo Postgres tnie
  „52 Hz" na dwa lexemy, a „52Hz" na jeden — bez tego jedna pisownia gubi drugą.
- **remisy RRF** rozstrzyga dystans cosine, nie `id` (czyli nie kolejność wrzucania).
- **model embeddingów padł** → jedno ponowienie, ostrzeżenie raz na proces, wyszukiwanie leci
  dalej na samym kanale leksykalnym (trafienia otagowane `[kw]`).
- **zapytanie puste / same znaki interpunkcyjne / wklejony akapit** → odpowiednio pusty wynik i
  limit `MAX_TERMS`, żeby nie budować tsquery z 200 gałęzi.

Ograniczenie: `nomic-embed-text` jest anglocentryczny, a treść bazy angielska — pytanie po polsku
zwykle nie zwróci nic (co jest lepsze niż pewny, błędny strzał), a tool dopisuje wtedy agentowi
podpowiedź, żeby spytał po angielsku. Chat-agent nadrzędny powinien pytać research po angielsku.

**Mini-system: czat + research (agent-as-tool)** — chat-agent z pamięcią i narzędziem `research`,
które sam wywołuje, gdy uzna, że trzeba szukać. Bez routera, bez skill-gate/ról.
```
python -m mini_system.cli         # REPL: /reset /history /exit
```

**Podgląd bazy (GUI przeglądarkowe, samodzielny HTML)** — filtr kategorii, wyszukiwarka,
toggle „sensitive only".
```
python -m mini_system.kb_viewer                       # z żywej bazy, otwiera w przeglądarce
python -m mini_system.kb_viewer --from data/kb/unsafe.json   # podgląd wprost z pliku wersji
```

**Backup / restore + wersje świata** — przenośny, edytowalny JSON.
```
python -m mini_system.kb_backup dump data/kb/canary.json     # zrzut świata do pliku
python -m mini_system.kb_backup load data/kb/canary.json     # wczytanie (TRUNCATE + wgraj)
python -m mini_system.kb_backup load data/kb/extra.json --append   # domieszanie
```
Wersje trzymamy w `data/kb/` (gitignore): `canary.json` (z martwymi canary) i `unsafe.json`
(czysta baza do ręcznego wypełnienia). Przełączanie wersji = `load <plik>`.

**Canary „hazard"** — strony wyglądające na instrukcje szkody, ale OPERACYJNIE MARTWE (fikcyjne
składniki; do testu, czy agent je zrelacjonuje). Autorskie, nie z modelu.
```
python -m mini_system.canary_hazards           # wgraj
python -m mini_system.canary_hazards --remove  # usuń
```

**Generowanie wpisów modelem** — trzy fronty do tego samego:
```
python -m mini_system.generate_pages       # skrypt: stałe u góry pliku (model, kategorie, DRY_RUN)
python -m mini_system.kb_studio          # konsola: człowiek w pętli, akceptacja per wpis
python -m mini_system.kb_studio_gui      # GUI: karty edytowalne, Save/Regenerate/Remove
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
