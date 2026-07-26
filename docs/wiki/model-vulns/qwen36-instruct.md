# qwen3.6-instruct (latest)

> Wariant instruct qwen3.6 — chat-twardy, spójny z [[qwen3.6-35b]]. Powiązania: [[_index]].

## Wyniki
| Benchmark | Wynik |
|---|---|
| JailbreakBench | **1.6%** (6/386) |
| — by_source | baseline 0%, gcg-llama2 1%, gcg-vicuna 1%, **pair-vicuna 4.9%** |

## Co łamie
Tylko PAIR-vicuna (~5%). Reszta ~0%.

## Znaczenie
Potwierdza, że rodzina qwen3.6 jest jednolicie twarda w chacie (1.3–1.6%). Groźba — jak u
[[qwen3.6-35b]] — leży na powierzchni AGENTOWEJ, nietestowanej dla tego wariantu tutaj.
