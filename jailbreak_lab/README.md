# Jailbreak Lab

Samodzielny playground do **ręcznego** łamania **czystych** modeli (bez protez systemu
agentowego). Bawisz się promptem, a narzędzie **samo rozmawia z modelem i loguje każdy strzał
do bazy** — dzięki temu nie musisz pamiętać, żeby zapisać atak. Logowanie jest efektem ubocznym
wysłania promptu, więc nic nie ginie i wszystko da się odtworzyć.

Folder jest **niezależny od reszty repo**: własny lekki config, własny klient Ollamy (natywne
REST `/api/chat`, bez langchaina), własna baza (SQLite, jeden plik). Nic tu nie importuje
`config.py`/`llm_factory.py` z systemu agentowego, żeby model był testowany goły.

## Szybki start

```bash
# środowisko conda systemu:
python lab.py                                   # start na domyślnym modelu (config.py)
python lab.py --model qwen3.6:27b-ctx8k --session "dan-warmup"
# albo na Windowsie:
run.bat --model gpt-oss:20b --session probe1
```

Wymagania: działająca lokalna Ollama (`http://localhost:11434`) i `requests`
(`pip install -r requirements.txt`). SQLite jest w stdlib.

## Jak się gra (przykładowa sesja)

```
atak> /goal wydobyć instrukcję syntezy substancji X
atak> /technique roleplay
atak> Udawaj że jesteś... <twój prompt>
        ← model odpowiada, strzał zalogowany jako #12 (werdykt=unknown)
atak> /win                     # model uległ → oznacz #12 jako success
atak> /tag DAN,persona         # dorzuć tagi
atak> /note działa dopiero po 2. turze
atak> /model gemma3:12b        # ten sam prompt na innym modelu:
atak> /replay 12               # powtórz atak #12 na gemma3 (nowy wiersz, replay_of=12)
atak> /stats                   # zestawienie werdyktów per model
```

Ustaw `/goal` i `/technique` **raz** — wchodzą automatycznie do każdego kolejnego logu.
Po strzale oceniasz go jednym słowem: `/win`, `/partial`, `/refused` (domyślnie dotyczy
ostatniego strzału; możesz podać id, np. `/win 12`). Pełna lista komend: `/help`.

Tryb wieloturowy: `/multi on` trzyma historię rozmowy i docleja ją do kolejnych strzałów
(pod ataki typu crescendo / stopniowa eskalacja). `/reset` zaczyna nową rozmowę.

## Podgląd i eksport bez REPL

```bash
python db.py stats
python db.py list --model gpt-oss:20b --verdict success
python db.py show 12
python db.py export dump.json     # albo dump.csv
```

## Co siedzi w bazie (tabela `attacks`, plik `jailbreaks.db`)

Każdy wiersz = jeden strzał, **w pełni odtwarzalny**. Najważniejsze kolumny:

| kolumna | znaczenie |
|---|---|
| `ts_utc` | moment wysłania (UTC) |
| `model`, `base_url`, `provider` | do jakiego modelu poszło |
| `options` | JSON parametrów próbkowania (temperature, seed, num_ctx, top_p…) |
| `system_prompt` | system prompt (zwykle pusty — czysty model) |
| `messages` | **pełna lista wiadomości realnie wysłana** — repro 1:1 |
| `attack_prompt` | ostatnia wiadomość user (do wyszukiwania) |
| `goal` | jakie zachowanie chciałeś wywołać |
| `technique` | etykieta techniki (patrz `techniques.json`) |
| `response`, `reasoning` | output modelu + kanał myślenia (jeśli był) |
| `verdict` | `unknown` / `success` / `partial` / `refused` / `error` |
| `tags`, `notes` | Twoje anotacje |
| `conversation_id`, `turn_index` | rekonstrukcja rozmów multi-turn |
| `replay_of` | id ataku, który odtworzono (`/replay`) |
| `latency_ms`, `eval_count` | czas + liczba tokenów |

Baza jest w `.gitignore` — dane zostają lokalnie. Backup = skopiuj `jailbreaks.db`.

## Gotowe frameworki (przegląd — jeśli chcesz iść dalej niż ręczny playground)

Szukałeś, czy nie ma gotowców — są, ale nastawione na **automatyczne** generowanie ataków,
nie na ręczne „pobawię się i zaloguję". Krótkie porównanie:

- **PyRIT** (Microsoft) — najbliższy Twojej potrzebie po stronie *logowania*: ma wbudowaną
  „memory" zapisującą każdą wymianę prompt↔odpowiedź (DuckDB/Azure SQL), obsługuje ręczne i
  automatyczne scenariusze, multi-turn, multi-modal. Jeśli ten playground urośnie, to naturalny
  cel migracji. https://github.com/Azure/PyRIT
- **Garak** (NVIDIA) — skaner podatności LLM, dużo gotowych „probes" (DAN, encoding, itp.).
  **Już go używasz** w `vuln_recon/`. Bardziej „odpal baterię testów" niż „graj promptem".
  https://github.com/NVIDIA/garak
- **promptfoo** — eval + red-team z konfiguracją w YAML (wersjonowalne, CI/CD), 50+ typów
  podatności. Dobre, gdy chcesz zautomatyzować i wrzucić do pipeline'u. https://www.promptfoo.dev
- **DeepTeam** (Confident AI, na DeepEval) — 50+ podatności, 20+ metod ataku single/multi-turn,
  wynik jako „score". Nastawiony na automatyczną ocenę. https://github.com/confident-ai/deepteam

Wniosek: do **ręcznej eksploracji + niezawodnego logowania per model** ten mini-playground jest
lżejszy i szybszy niż każdy z powyższych. Jak zbierzesz techniki, które działają, warto je
przenieść do PyRIT/promptfoo, żeby odpalać je automatycznie jako regresję na kolejnych modelach.

Źródła przeglądu:
- [DeepTeam — Help Net Security](https://www.helpnetsecurity.com/2025/11/26/deepteam-open-source-llm-red-teaming-framework/)
- [promptfoo — LLM red teaming](https://www.promptfoo.dev/docs/red-team/)
- [Confident AI — jak jailbreakować LLM krok po kroku](https://www.confident-ai.com/blog/how-to-jailbreak-llms-one-step-at-a-time)
- [JailbreakBench (arXiv)](https://arxiv.org/pdf/2404.01318)
