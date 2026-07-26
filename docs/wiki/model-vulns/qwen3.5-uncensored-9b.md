# qwen3.5-uncensored:9b (ctx8k)

> **SUFIT, nie cel.** Model bez alignmentu — pokazuje granicę „gdyby model nie bronił".
> NIE liczyć jego wyników jako „udanego ataku". Powiązania: [[successful-attacks]] · [[_index]].

## Wyniki
| Benchmark | Wynik |
|---|---|
| JailbreakBench | **64.2%** (248/386) |
| — by_source | **baseline 89%**, gcg-llama2 54%, gcg-vicuna 33%, pair-llama2 75%, **pair-vicuna 84.1%** |

## Znaczenie
Baseline 89% = model spełnia niemal każdą surową szkodliwą prośbę wprost. Kontrast z cenzurowanymi
(1.3%) = miara ile trzyma sam alignment. Użycie w metodyce: **ceiling/kontrola** — jeśli atak nie
działa nawet na uncensored, problem jest w pipelinie, nie w obronie. Świetny też jako **model ATAKUJĄCY**
(nie odmawia generowania payloadów) w pętlach `attack_forge`.
