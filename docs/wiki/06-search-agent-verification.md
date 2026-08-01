# Search agent + weryfikacja groundingu (fake_internet)

> Jak zbudowaliśmy prosty search-agent na bazie „symulującej internet" i jak UDOWODNILIŚMY,
> że czyta z bazy zamiast zmyślać. Powiązane: [[01-agent-system]] (runtime), [[03-benchmark-results]]
> (inne benchmarki). Kod: `agents/search_sim_agent.py`, `database/internet_db.py`,
> benchmark `agents_benchmark/search_sim_agent/`.

## Co powstało

- **`fake_internet`** — OSOBNA baza Postgres symulująca internet: `pages(category, topic, title, content)`,
  33 strony / 11 kategorii (animals, space, technology, history, plants, human_body, weather, music,
  geography, mythology + `curiosities`=canary). Idempotentny seed: `python -m database.internet_db`.
- **`SearchSimAgent(BaseAgent)`** — konstruowany jak inni agenci (`SearchSimAgent(llm, all_mcp_tools)`),
  wpina się w pipeline przez odziedziczone `run(task)`, wspiera skille (skill-gate). Cztery proste toole
  DB: `list_categories`, `classify_content` (deterministyczny routing po kategorii), `search_internet`,
  `read_page`. Flow: classify → search → read → odpowiedź z cytatem strony.
- **`ConversationAgent`** (wielotu­rowy chat) — patrz osobny wątek; też podklasa BaseAgent
  (`StatefulAgent`), pamięć rozmowy przez wymienialny `ConversationStore`.

## Najważniejszy wniosek metodyczny — jak dowieść groundingu

**Zaliczenie „fakt jest w odpowiedzi" NIE dowodzi, że agent wziął go z bazy.** Nasze pierwsze
fakty (88 klawiszy, 206 kości, Everest 8849 m) to wiedza ogólna, którą model zna z treningu — więc
mógł je „wiedzieć" niezależnie od bazy, a tool wywołać na pokaz. Do prawdziwej pewności potrzeba
trzech niezależnych warstw dowodu:

1. **Proweniencja (twarde kryterium)** — oczekiwany fakt musi wystąpić w **WYJŚCIU narzędzia**
   (`grounded=True`), nie tylko w finalnej odpowiedzi. To oddziela „odczyt z bazy" od „z pamięci modelu".
2. **Canary (nie do podrobienia)** — strony z faktami **fikcyjnymi**, których model nie może znać
   z treningu (zorblax: 7 oczu / 3 ogony / świeci violet; miasto Qintara: 47 213; metal brennium: 1742°C).
   Poprawna odpowiedź = dowód, że przeczytał bazę.
3. **Anty-halucynacja (brak w bazie)** — pytania o byty spoza bazy (Fakelandia, ptak „flumbernaut",
   „Qwenland Empire") → agent MUSI przyznać „nie znalazłem", a nie fabrykować.

## Benchmark „test generalny" — 4 warstwy, 38 pytań

`agents_benchmark/search_sim_agent/` (`cases.py` + `run.py`). Harness loguje pełny trace (sekwencja
tool-calli z I/O + finalna odpowiedź + powody pass/fail) do `results/<ts>/{trace.md,results.jsonl,summary.md}`
— żeby dało się sprawdzić DLACZEGO model coś zwrócił.

| Warstwa | # | Sprawdza |
|---|---|---|
| baseline | 20 | jeden fakt: użycie narzędzi + dokładna treść (+ proweniencja) |
| extended | 6 | wiele faktów naraz / wiele wyszukiwań |
| grounding | 8 | 5× canary (grounded) + 3× brak-w-bazie (not_found) |
| security | 4 | blokujący skill na temat 'octopus': 3× odmowa bez wycieku + 1 kontrolny odpowiada |

**Wynik 2026-08-01 (qwen3.6:35b, thinking off, przez proxy): 38/38.**
- Grounding: canary 5/5 z `grounded=True` → **agent czyta bazę, nie zmyśla**. Absent 3/3 „nie znalazłem".
- Security 4/4: model robił `list_skills → load_skill → odmowa`, `retrieved_forbidden=False` (nie tknął
  nawet strony octopus), a kontrolne pytanie (pszczoły) mimo aktywnego skilla odpowiedział → brak nad-blokowania.
- Uwaga o pomiarze: dwa fałszywe FAIL-e po drodze były **artefaktami asercji** (np. „4 strings" vs słowo
  „four"; „no known bird… fictional" nie łapane przez wąską listę fraz not-found), nie błędami agenta →
  naprawione na warianty. Lekcja: asercje na treść LLM rób jako any-of, nie exact.

## Jak odpalić

```
python -m database.internet_db                                   # seed świata (idempotentny)
python -m agents_benchmark.search_sim_agent.run                 # pełny benchmark (4 warstwy)
python -m agents_benchmark.search_sim_agent.run --layer grounding   # sam decydujący test
python -m agents.search_sim_agent "why does mars look red?"     # pojedyncze pytanie
```

## Zastrzeżenia / dalej

- To **jeden model, jeden przebieg** (temp 0.2). Twardsza pewność: `--repeat N` (spójność) + drugi
  model do cross-checku (wzór z [[03-benchmark-results]], gdzie gemma4 bije qwena).
- Skill-block wstrzykiwany do `agent_skills` per przebieg i kasowany w `finally` (gate czyta skille live).
