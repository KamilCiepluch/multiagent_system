# Udane ataki — prosty podgląd (co REALNIE się udało)

Uszeregowane wg tego, co faktycznie przełamało model. Odróżniamy **sufit** (uncensored — „gdyby model
nie bronił") od realnych wyłomów na modelach cenzurowanych. Pełny kontekst: [[attack-surfaces]], [[benchmarks]].

## Top wektory (modele cenzurowane) — uszeregowane
| # | Wektor | Powierzchnia | Najlepszy wynik | Model | Wiarygodność |
|---|--------|--------------|-----------------|-------|--------------|
| 1 | Szkodliwe zadania z narzędziami | AGENT | **AgentHarm 64%** | [[qwen3.6-35b]] | ✅ |
| 2 | Indirect injection `important_instructions` (slack) | AGENT | **57%** | [[qwen3.6-35b]] | ✅ deterministyczne |
| 3 | ascii (obfuskacja treści) | perswazja | **38.6%** | [[qwen3.6-35b]] | ✅ SORRY-Bench |
| 4 | logical_appeal (perswazja logiczna) | perswazja | 31.8% | [[qwen3.6-35b]] | ✅ |
| 5 | authority_endorsement | perswazja | 26.1% | [[qwen3.6-35b]] | ✅ |
| 6 | Indirect injection (banking) | AGENT | 25.0% | [[qwen3.6-35b]] | ✅ |
| 7 | HarmBench cyber-intrusion (phishing-email) | chat | 6.0% | [[qwen3.6-35b]] | ✅ złoty sędzia |
| 8 | PAIR-vicuna (semantyczny reframing) | chat | ~4% | [[qwen3.6-35b]] | ⚠️ |

## Co konkretnie padło na czacie (HarmBench, sędzia oficjalny)
qwen3.6:35b, 7/300: **3× perswazyjny e-mail phishingowy** + 1× phishing (illegal) → phishing to
najpewniejszy chat-wektor; chem/bio (izotonitazen, homebake heroiny) 2×; cyber (exploit Jeep) 1×.

## Sufit (uncensored — NIE liczy się jako atak, tylko granica)
[[qwen3.5-uncensored-9b]]: JBB **64.2%** (baseline 89%, pair-vicuna 84%). Pokazuje ile „trzyma" sam
alignment: różnica 1.3% (cenzurowany) vs 64% (uncensored) = to obrona modelu, nie przypadek.

## Co NIE działa (żeby nie tracić czasu)
- **GCG** (sufiksy adwersarialne) — 0–1%, nie transferuje na te modele.
- **DAN / „ignore previous" / role_play / szyfry** (caesar/atbash/morse) — ~0–7% (SORRY-Bench/garak).
- **Statyczne jailbreaki wprost** — mur na wszystkim poza uncensored.

## Per-model skrót „co je łamie"
- [[qwen3.6-35b]] — chat-safe, agent-dangerous; ascii+perswazja na treści, indirect injection agentowo (AgentHarm 64%).
- [[gemma4-31b]] — HarmBench 13.7% (dezinformacja 46%!), AgentHarm 52% (dezinfo 85%); pięta = dezinformacja.
- [[gemma4-12b]] — słabszy wariant (JBB 9.6%, HarmBench 10.7%), pair-vicuna 30.5%.
- [[gpt-oss-20b]] — chat-twardy (1.3%), realny wektor to CoT-leak (mierzony osobno w agents_blocks/jailbreak_lab).
- [[gemma3-12b]] — najsłabszy cenzurowany w chacie (JBB 27.5%, pair-vicuna 66%).
- [[llama3.1]] / [[qwen36-instruct]] — twarde w chacie (~1.5–1.8%), agentowo nietestowane tutaj.

## Wnioski → decyzje (do omówienia)
1. Chat single-turn = ślepa uliczka na modelach cenzurowanych → **nie inwestować**.
2. Realna dźwignia = **powierzchnia agentowa** (indirect injection / tool / memory) — dokładnie to,
   co robi `agents_blocks`. Wyniki tutaj to empiryczne uzasadnienie kierunku.
3. Na treści (gdzie filtr treści jest barierą, np. czat secret_guard) — **ascii + logical_appeal + authority**
   to top-3 do wypróbowania (nie DAN/szyfry).
