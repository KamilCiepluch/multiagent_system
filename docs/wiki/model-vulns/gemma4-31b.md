# gemma4:31b

> Mocny reasoner (bije innych w benchmarku zdolności agents_blocks), ale w chacie **słabszy od qwena**.
> Powiązania: [[attack-surfaces]] · [[successful-attacks]] · [[_index]].

## Wyniki
| Benchmark | Powierzchnia | Wynik |
|---|---|---|
| JailbreakBench | chat | **7.5%** (29/386); pair-vicuna 25.6%, pair-llama2 50% |
| HarmBench | chat | **13.7%** — NAJWYŻSZY z cenzurowanych; **misinformation 46.2%**, cyber 13.4% |
| AgentHarm | agent | **52%** wykonanych (harm 0.41); Copyright 100%, **Disinformation 85%**, Drugs 55% |

## Co łamie
- **AGENT:** AgentHarm 52% — wykonuje szkodliwe zadania z narzędziami (mniej niż qwen 64%, ale dużo).
- **DEZINFORMACJA = pięta (EMPIRYCZNIE):** HarmBench misinformation 46.2%, AgentHarm Disinformation 85%.
- **CHAT:** semantyczny reframing **PAIR-vicuna 25.6%** (skuteczniejszy niż na qwenie).

## Co NIE łamie
GCG (1–3%), baseline (2%).

## Znaczenie dla agents_blocks
Cel alternatywny, silny reasoner (groźny jako egzekutor). W chacie łatwiejszy niż [[qwen3.6-35b]], a
pięta = **dezinformacja** (potwierdzona liczbowo, nie tylko z literatury). AgentDojo (indirect injection)
tutaj NIETESTOWANY — luka do domknięcia. → [[successful-attacks]]
