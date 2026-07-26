# gpt-oss:20b

> Chat-twardy; realny wektor to CoT-leak (poza tym rigiem). Powiązania: [[attack-surfaces]] · [[_index]].

## Wyniki
| Benchmark | Wynik |
|---|---|
| JailbreakBench | **1.3%** (5/386) |
| — by_source | baseline 0%, gcg 0%, **pair-vicuna 4.9%**, pair-llama2 25% |
| HarmBench | **3.3%** |
| JailJudge | ds 4.8%, id 2.8% (sędzia LlamaGuard) |

## Co łamie
Bardzo mało w chacie — jedynie PAIR-vicuna (~5%). Model rozumujący: prawdziwa słabość to **wyciek
reasoningu (CoT-leak)** — mierzony osobno w `agents_blocks/jailbreak_lab`, nie w tym rigu.

## Co NIE łamie
GCG (0%), baseline (0%), DAN (garak zawyża — realnie ~2–3%).

## Znaczenie
Domyślny model systemu agents_blocks (starsze biegi). Twardy na treści → atakować przez architekturę
(dekompozycja/hijack) i CoT-leak, nie prompt.
