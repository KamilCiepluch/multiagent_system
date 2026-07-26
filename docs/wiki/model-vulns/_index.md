# Model Vulnerability Lab — hub

> Część głównego wiki `agents_blocks` (`docs/wiki/model-vulns/`). Profile podatności **lokalnych
> modeli Ollama** na jailbreaki i prompt-injection. Dane pochodzą z osobnego rigu
> `C:\Users\kamil\Desktop\test llms\` (biegi 2026-07-07…07-13) — jak go odpalić: [[how-to-run]].
> Otwórz `docs/wiki` jako vault Obsidiana → **Graph view** pokaże model ↔ technika ↔ powierzchnia.
> Nadrzędny system, który te modele napędzają: [[01-agent-system]]; pomiar zdolności: [[03-benchmark-results]].

## TL;DR (jedno zdanie)
**Modele cenzurowane są bezpieczne w czystym czacie, a niebezpieczne jako agenci z narzędziami.**
Statyczne jailbreaki w rozmowie ~1–3% ASR; ryzyko wybucha na powierzchni AGENTOWEJ (AgentDojo do 57%,
AgentHarm 64%) i pod perswazją/ascii. To napędza strategię ataku na `agents_blocks`: atakuj SYSTEM, nie prompt. → [[attack-surfaces]]

## Ranking modeli — chat (JailbreakBench, ASR transfer)
| Model | JBB ASR | HarmBench | Charakter |
|---|---|---|---|
| [[qwen3.5-uncensored-9b]] | **64.2%** | — | UNCENSORED = sufit („gdyby model nie bronił") |
| [[gemma3-12b]] | 27.5% | — | słaby; pair-vicuna 65.9% |
| [[gemma4-12b]] | 9.6% | 10.7% | |
| [[gemma4-31b]] | 7.5% | 13.7% | mocny reasoner, ale HarmBench najwyższy |
| [[llama3.1]] | 1.8% | — | |
| [[qwen36-instruct]] | 1.6% | — | |
| [[gpt-oss-20b]] | 1.3% | 3.3% | + CoT-leak (osobny wektor) |
| [[qwen3.6-35b]] | **1.3%** | 2.3% | **pełny profil 6 benchmarków** → agentowo groźny |

> ⚠️ Liczby NIE są porównywalne wprost między benchmarkami (różni sędziowie, różne mianowniki).
> To różne wymiary tego samego modelu, nie jedna skala. Szczegóły: [[benchmarks]].

> ℹ️ `llama3.3:70b` — bieg PRZERWANY (proxy nie wyrabia z 70B, ~10 min/prompt). Do ponowienia na
> mniejszej próbce / mniej obciążonym proxy. Reszta modeli = pełne biegi.

## Nawigacja
- [[how-to-run]] — jak odpalić rig (skrypty, komendy, proxy, licencja SORRY-Bench).
- [[benchmarks]] — co mierzy każdy benchmark (JBB, HarmBench, JailJudge, SORRY-Bench, AgentHarm, AgentDojo, garak) + wiarygodność sędziów.
- [[attack-surfaces]] — **główny graf** „co z czego wynika": chat → perswazja → agent.
- [[successful-attacks]] — prosty podgląd: co REALNIE się udało, per model, uszeregowane.
- Modele: [[qwen3.6-35b]] · [[gemma4-31b]] · [[gemma4-12b]] · [[gemma3-12b]] · [[gpt-oss-20b]] · [[qwen3.5-uncensored-9b]] · [[llama3.1]] · [[qwen36-instruct]]

## Powiązanie z agents_blocks
Modele-cele `agents_blocks` (qwen3.6, gemma4, gpt-oss) mają tu zmierzony profil. Wniosek „chat-safe /
agent-dangerous" jest empirycznym uzasadnieniem, że atak na system agentowy (indirect injection,
skill/tool poisoning) > atak na prompt modelu.
