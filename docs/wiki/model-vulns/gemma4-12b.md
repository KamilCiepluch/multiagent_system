# gemma4:12b

> Mniejsza gemma4 — w chacie umiarkowanie podatna. Powiązania: [[attack-surfaces]] · [[_index]].

## Wyniki
| Benchmark | Wynik |
|---|---|
| JailbreakBench | **9.6%** (37/386) |
| — by_source | baseline 5%, gcg-llama2 1%, gcg-vicuna 5%, **pair-vicuna 30.5%**, pair-llama2 25% |
| HarmBench | **10.7%** |

## Co łamie
PAIR-vicuna 30.5% (najwyższy z gemma4). Baseline 5% (przepuszcza trochę wprost).

## Co NIE łamie
GCG (1–5%).

## Znaczenie
Lżejszy wariant do szybkich iteracji. Podobny profil do [[gemma4-31b]], nieco bardziej podatny w chacie,
słabszy jako reasoner/agent.
