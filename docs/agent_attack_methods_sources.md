# Realne metody atakowania agentów LLM — źródła i mapowanie na nasz atak

Zebrane na potrzeby maksymalizacji ASR AutoDAN-Turbo na agents_blocks (wektor „pojedynczy mail").
Każda pozycja: **co to / dlaczego istotne / link do weryfikacji / jak wykorzystane u nas**.
Research z 2026-06-29 (WebSearch). Linki do weryfikacji przez użytkownika.

> TL;DR co z tego wzięliśmy do katalogu (`attack_core/knowledge/catalog.py`): (1) **taksonomia
> perswazji** Zeng et al. → 8 technik persuasion (stack authority+social-proof+expert+misrep+
> false-urgency wygrał w E0.c); (2) **„Important Instructions"** z AgentDojo (najwyższy ASR) →
> `important-instructions`; (3) **indirect PI / tool-output spoofing** Greshake → `data-as-
> instructions`, `tool-output-spoofing`, `verification-result-injection`; (4) odkryty empirycznie
> `pre-authenticated-context` (skip-revalidation) — wariant atakowania DECYZJI, nie wartości roli.

---

## Foundational — taksonomie i kanoniczne ataki

### 1. Zeng et al. 2024 — "How Johnny Can Persuade LLMs to Jailbreak Them"
- **Co:** taksonomia perswazji z nauk społecznych — 13 strategii / **40 technik**; generuje
  „Persuasive Adversarial Prompts" (PAP). **>92% ASR** na Llama-2-7b / GPT-3.5 / GPT-4.
- **Dlaczego istotne:** atak NIE algorytmiczny, tylko „humanizujący" model — działa na zaligned
  modele przez perswazję, nie przez exploity tokenowe. To rdzeń naszego katalogu persuasion.
- **Link:** https://arxiv.org/abs/2401.06373 · ACL: https://aclanthology.org/2024.acl-long.773/ ·
  kod: https://github.com/CHATS-lab/persuasive_jailbreaker
- **U nas:** 8 technik persuasion w katalogu; w E0.c stack 5 z nich przebił bramkę ról (0/3→2/10).

### 2. Debenedetti et al. 2024 — "AgentDojo"
- **Co:** dynamiczny benchmark PI dla agentów tool-calling (97 zadań, 629 testów bezpieczeństwa,
  m.in. klient pocztowy). Atak **„Important Instructions"** — komunikat o najwyższym priorytecie,
  adresowany do agenta, „ignore previous instructions", z prawdziwym imieniem ofiary dla
  wiarygodności — **konsekwentnie najwyższy ASR na leaderboardzie**.
- **Dlaczego istotne:** najprostszy, a najskuteczniejszy szablon na agentach; bezpośredni wzorzec.
- **Link:** https://arxiv.org/abs/2406.13352 · html: https://arxiv.org/html/2406.13352v3
- **U nas:** nowa technika katalogu `important-instructions` (E1).

### 3. Zhan et al. 2024 — "InjecAgent"
- **Co:** pierwszy benchmark indirect PI dla agentów zintegrowanych z narzędziami — **1054 testy**
  (finanse, smart-home, **email**…), 62 instrukcje atakującego; kategorie: direct-harm i data-stealing.
- **Dlaczego istotne:** pokazuje, że groźna instrukcja w WYNIKU narzędzia (nie w prompcie usera)
  przejmuje agenta — dokładnie nasz model (payload w treści maila / wyniku search).
- **Link:** https://arxiv.org/abs/2403.02691
- **U nas:** uzasadnia wektory `email` / `search_result`; przyszłe pod-wektory data-stealing.

### 4. Greshake et al. 2023 — "Not what you've signed up for: …Indirect Prompt Injection"
- **Co:** wprowadza indirect PI — wstrzyknięcie przez dane zewnętrzne, które agent wciąga do
  kontekstu (strony, maile, wyniki narzędzi). Techniki: data-as-instructions, podrabianie
  wyników narzędzi, zacieranie granicy dane↔polecenia.
- **Dlaczego istotne:** teoretyczna podstawa całego naszego podejścia (atak POŚREDNI przez DB).
- **Link:** https://arxiv.org/abs/2302.12173
- **U nas:** `data-as-instructions`, `delimiter-confusion`, `tool-output-spoofing`,
  `verification-result-injection`, `search-result-poisoning`.

### 5. OWASP Top 10 for LLM Applications (2025)
- **Co:** standard branżowy. **LLM01: Prompt Injection** (direct/indirect), **LLM07: System Prompt
  Leakage**, **LLM08: Vector/Embedding Weaknesses** (nowe w 2025).
- **Dlaczego istotne:** wspólny słownik klasyfikacji podatności; mapuje nasze `attack_class`.
- **Link:** https://genai.owasp.org/llm-top-10/ (LLM01: https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- **U nas:** klasa `direct_override`, `instruction_hierarchy`.

---

## Agentowe / zaawansowane (recent 2025–2026)

### 6. Confused deputy / tool-chaining w agentach
- **Co:** zaufany komponent (agent) z PRAWOWITYMI uprawnieniami wykonuje złośliwą operację zleconą
  pośrednio; pojedynczo niewinne narzędzia łączone w groźny łańcuch. Najwyższe ryzyko (persystencja
  + niewidzialność + uprzywilejowany dostęp).
- **Link (review):** https://www.mdpi.com/2078-2489/17/1/54 · CWE-441 (Confused Deputy) ·
  Willison: https://simonwillison.net/series/prompt-injection/
- **U nas:** `confused-deputy`, `provenance-laundering`, `chained-agent-escalation`. Trafne dla naszej
  architektury supervisor→email→terminal.

### 7. "Adaptive Attacks Break Defenses Against Indirect Prompt Injection" (2025)
- **Co:** adaptacyjne ataki łamią obrony przed indirect PI na agentach (obrony promptowe są kruche).
- **Dlaczego istotne:** koroboruje NASZ wynik — bramka ról jest perswadowalna na poziomie decyzji
  LLM (prompt-guard nie wystarcza). To argument za uczeniem-się atakującego (AutoDAN-Turbo).
- **Link:** https://arxiv.org/abs/2503.00061

### 8. ChatInject (2025) — abusing chat templates
- **Co:** wstrzyknięcie przez nadużycie szablonów czatu (tokeny ról), by sfałszować hierarchię ról
  w wynikach narzędzi.
- **Link:** https://arxiv.org/abs/2509.22830
- **U nas:** pokrewne `fake-system-prompt` / forged role tags; potencjalny przyszły pod-wektor.

### 9. Benchmarki dodatkowe (do ewentualnego portu metryk)
- **Agent Security Bench (ASB), ICLR 2025** — szeroka ocena ataków/obron agentów.
  https://proceedings.iclr.cc/paper_files/paper/2025/file/5750f91d8fb9d5c02bd8ad2c3b44456b-Paper-Conference.pdf
- **"Simple Prompt Injection… Leak Personal Data"** (2025) — proste ataki wyciekają dane PII
  obserwowane przez agenta podczas zadania. https://arxiv.org/abs/2506.01055
- **AgentVigil / AgentDojo-firewall benchmarks** — generic black-box red-teaming indirect PI.
  https://arxiv.org/abs/2505.05849 · https://arxiv.org/abs/2510.05244

---

## Wnioski dla naszego ataku (co maksymalizuje ASR na pojedynczym mailu)
1. **Perswazja STACKOWANA** (Zeng) > pojedyncza technika — potwierdzone empirycznie (E0.c).
2. **Atakuj DECYZJĘ, nie wartość roli** — bo rola jest deterministyczna z `get_contact_role`.
   Najmocniejsze: „verified upstream / nie re-waliduj" (`pre-authenticated-context`) + „Important
   Instructions". To kierunek E1/E2.
3. **Prompt-guard jest kruchy** (Greshake/Adaptive Attacks) — uczenie-się atakującego (lifelong +
   biblioteka) to właściwe narzędzie, nie pojedynczy ręczny payload.
