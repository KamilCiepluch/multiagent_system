# gemma3:12b

> **Najsłabszy cenzurowany w chacie** z całego zestawu. Powiązania: [[attack-surfaces]] · [[_index]].

## Wyniki
| Benchmark | Wynik |
|---|---|
| JailbreakBench | **27.5%** (106/386) |
| — by_source | baseline 12%, gcg-llama2 18%, gcg-vicuna 20%, **pair-vicuna 65.9%**, pair-llama2 50% |
| — by_category | Expert advice 55.3%, Fraud 39.5%, Disinformation 37.8%, Privacy 34.2% |

## Co łamie
Prawie wszystko względem cenzurowanych: **pair-vicuna 65.9%**, a nawet GCG częściowo transferuje
(18–20%) — rzadkość. Baseline 12% = przepuszcza wprost co ósmą prośbę.

## Znaczenie
Poprzednia generacja — pokazuje POSTĘP alignmentu: gemma3:12b 27.5% → [[gemma4-12b]] 9.6% na tym samym
teście. Dobry „słaby cel" do kalibracji pipeline'u (łatwo dostać pozytywy).
