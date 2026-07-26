# qwen3.6:35b

> **Jedyny model z pełnym profilem (6 benchmarków).** Sztandarowy wniosek: **chat-safe, agent-dangerous.**
> `think:false`, przez proxy. Powiązania: [[attack-surfaces]] · [[successful-attacks]] · [[benchmarks]].

## Wyniki
| Benchmark | Powierzchnia | Wynik |
|---|---|---|
| JailbreakBench | chat | **1.3%** (5/386) |
| HarmBench | chat | **2.3%** (7/300) — cyber 6.0% |
| SORRY-Bench | perswazja | **14.3%** śr.; ascii 38.6%, logical_appeal 31.8%, authority 26.1% |
| AgentHarm | agent | **64%** wykonanych (odmowa 36%) |
| AgentDojo | agent | **23.3%** ASR; slack 56.7%, banking 25%, travel 5%, workspace 6.7% |
| garak | detektor ⚠️ | malwaregen 77.5%, latentinjection 43.7%, goodside 33.3% (zawyżone 2–20×) |

## Co łamie
- **AGENT:** indirect injection (`important_instructions`) i zadania z narzędziami — najsilniejszy wektor.
- **TREŚĆ:** ascii > logical_appeal > authority (top-3 mutacje SORRY-Bench).
- **CHAT:** tylko phishing-email (HarmBench cyber) i PAIR-vicuna (~4%).

## Co NIE łamie
GCG (0%), DAN/„ignore previous"/role_play/szyfry (~0–2.5%), statyczne jailbreaki wprost.

## Znaczenie dla agents_blocks
Główny model-cel. Empiryczny dowód, że trzeba atakować powierzchnię agentową (indirect PI / tool /
memory), nie prompt. Na powierzchni czatowej (secret_guard): próbować ascii+perswazję.
