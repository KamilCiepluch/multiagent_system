# llama3.1 (latest, ~8b)

> Twardy w chacie. Powiązania: [[attack-surfaces]] · [[_index]].

## Wyniki
| Benchmark | Wynik |
|---|---|
| JailbreakBench | **1.8%** (7/386) |
| — by_source | baseline 0%, gcg 0%, **pair-vicuna 7.3%**, pair-llama2 25% |

## Co łamie
Tylko PAIR-vicuna (7.3%) — nieco wyżej niż qwen/gpt-oss, ale wciąż nisko. Baseline i GCG = 0%.

## Znaczenie
Punkt odniesienia „mały solidny model". Agentowo tutaj nietestowany. W benchmarku zdolności
agents_blocks wypadał słabo (reasoning), więc mniej groźny jako egzekutor.
