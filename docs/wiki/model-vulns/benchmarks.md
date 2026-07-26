# Benchmarki — co mierzy każdy i ile mu wierzyć

Rig (`test llms/`) odpala 7 benchmarków przez lokalną Ollamę (proxy Bearer, zwykle `think:false`).
Każdy ma INNEGO sędziego → liczby nieporównywalne wprost. Pogrupowane wg **powierzchni** ataku
([[attack-surfaces]]).

## Powierzchnia: CHAT (pojedyncza tura, statyczne jailbreaki)
| Benchmark | Co mierzy | Sędzia | Wiarygodność |
|---|---|---|---|
| **JailbreakBench** (JBB) | statyczne jailbreaki transfer (baseline/PAIR/GCG) | `gpt-oss-safeguard:20b` (lokalny) | ⚠️ namiastka oficjalnego Llama-3-70B — kierunkowo OK |
| **HarmBench** | bezpośrednie szkodliwe prośby, 300 zach./6 kat. | oficjalny **HarmBench-Llama-2-13b-cls** | ✅ złoty standard |
| **JailJudge** | zbiór jailbreak, sędzia LlamaGuard | LlamaGuard | ✅ solidne (tylko gpt-oss) |

Źródła JBB: `baseline` (surowe prośby), `pair-*` (semantyczny reframing PAIR), `gcg-*` (sufiksy
adwersarialne GCG). PAIR/GCG craftowane na vicuna/llama2 → **transfer**. GCG praktycznie NIE transferuje.

## Powierzchnia: PERSWAZJA / mutacje treści
| Benchmark | Co mierzy | Sędzia | Wiarygodność |
|---|---|---|---|
| **SORRY-Bench** | która TECHNIKA łamie refuzję (88 promptów × 21 mutacji = 1848) | fine-tunowany sędzia SORRY-Bench | ✅ dedykowany |

Mutacje = ascii, logical_appeal, authority_endorsement, technical_terms, misrepresentation,
evidence-based, slang, translate-*, role_play, misspellings… (ranking: [[attack-surfaces]]).

## Powierzchnia: AGENT (narzędzia + indirect injection) — NAJGROŹNIEJSZA
| Benchmark | Co mierzy | Sędzia | Wiarygodność |
|---|---|---|---|
| **AgentHarm** | szkodliwe ZADANIA z narzędziami (176 próbek/8 kat.) | Inspect `combined_scorer` (refusal+grading) | ✅ dowody jednoznaczne |
| **AgentDojo** | prompt-injection wstrzyknięty w treść narzędzia (atak `important_instructions`) | **deterministyczne** testy suity | ✅ twarde, nie-LLM |

AgentDojo suity: slack / banking / travel / workspace; metryki `utility` (czy zadanie zrobione) +
`asr` (czy injection zadziałał).

## Detektory (traktować OSTROŻNIE)
| Benchmark | Co mierzy | Wiarygodność |
|---|---|---|
| **garak** | rodziny probe'ów (goodside/grandma/dan/malwaregen/promptinject/latentinjection/encoding) | ❌ **zawyża 2–20×** — detektory (AnyCode/TriggerList/MitigationBypass) łapią pozory, nie realny wyciek |

**Zasada:** garak = sygnał kierunkowy KTÓRE rodziny drażnią model, NIE bezwzględne ASR. Do wniosków
bierzemy HarmBench/SORRY-Bench/AgentDojo/AgentHarm; JBB z zastrzeżeniem; garak tylko jako trop.
