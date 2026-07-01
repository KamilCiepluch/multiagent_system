# Orkiestracja „po sztuce" wg docs LangChain + wyniki pomiarów modeli

Notatka robocza (2026-07-01). Cel: (a) utrwalić pomiary qwen vs gpt-oss, (b) zebrać z DOKUMENTACJI
LangChain, jak zrobić DOKŁADNIE tę samą architekturę (mózg + agenci), ale zgodnie ze sztuką i lepiej.
**Nie edytowaliśmy jeszcze kodu** — to lista „co i jak poprawić" + źródła do weryfikacji.

---

## 1. Wyniki pomiarów (head-to-head, `completion_guard=OFF`, architektura wzorcowa)

Bieg: `scenario_attack_v1/headtohead_guardoff.txt` (2026-07-01). Oba modele bez sztucznego domykania hopa.

| metryka | **qwen36-instruct** (Q3, BEZ reasoningu, temp 0.7) | **gpt-oss:20b** (normalnie, Z reasoningiem) |
|---|---|---|
| **E2E full** | **16/18** | 14/18 |
| **E2E smoke (6, wcześniej)** | 6/6 | (n/d) |
| **Email per-agent (all)** | **32/34 przypadków (165/170 trials)** | ~26/28 (stary log, inne warunki) |
| **Deny (bezpieczeństwo)** | 100% (0 failów deny) | 100% (0 failów deny) |

**Faile gpt-oss e2e (4):** wszystkie „oczekiwany tool-call BRAK" (pudła orkiestracji) — admin odczyt sekretu,
operator ticket, viewer search, viewer dokument. Te przypadki **qwen zaliczył**.
**Faile qwen e2e (2):** 1× korupcja JSON `EmailAnswer` (artefakt kwantyzacji Q3, nie orkiestracja) +
1× pudło viewer-dokument.

**Werdykt:** qwen (BEZ thinkingu, Q3) ≥ gpt-oss (Z thinkingiem) przy architekturze bez guardu — qwen
„z jedną ręką za plecami" dorównał/pobił gpt-oss w jego pełnym trybie. Usunięcie guardu NIE zepsuło
bezpieczeństwa (deny 100% u obu; guard podpierał tylko ALLOW). Zastrzeżenie: e2e to **n=1** (szum ±2–3),
ale trend spójny w 3 punktach. Jedyna słabość qwen = kwant Q3 (Q4_K_M się nie mieści w VRAM → zostajemy na Q3).

---

## 2. Co mówi dokumentacja LangChain (i jak to nas ulepsza)

### 2.1. Wymuszanie narzędzi — `tool_choice` ⭐ (intuicja użytkownika potwierdzona)
`model.bind_tools([...], tool_choice=...)` — wartości:
- `"auto"` (domyślnie) — model decyduje,
- `"any"` / `"required"` — model MUSI wywołać JAKIEŚ narzędzie z listy,
- `"<nazwa_narzędzia>"` — wymusza KONKRETNE narzędzie.
Plus `parallel_tool_calls=False` — wyłącza równoległe wywołania.
- **Źródło:** https://docs.langchain.com/oss/python/langchain/models (sekcja tool calling).
- **Jak nas ulepsza:** deterministycznie wymusić krytyczne kroki bez protezy —
  np. email_agent MUSI zawsze najpierw wywołać `get_contact_role` (wymuś `tool_choice="get_contact_role"`
  na pierwszym kroku), a supervisor przy zadaniu cross-agent MUSI oddelegować (`tool_choice="required"`).
  To „po sztuce" zastępuje część tego, co robił completion-guard — ale przez mechanizm modelu, nie hack.

### 2.2. Orkiestracja = supervisor woła agentów JAKO NARZĘDZIA (nasz wzorzec = zalecany)
Docs: *„a central main agent (supervisor) coordinates subagents by calling them as tools."* To DOKŁADNIE
nasz `Supervisor` + `_make_agent_tool`. `langgraph-supervisor` jest **DEPRECATED** → zalecane `create_agent`
+ agenci-jako-@tool (czyli to, co mamy).
- **Źródła:** https://docs.langchain.com/oss/python/langchain/multi-agent/subagents ·
  https://docs.langchain.com/oss/python/migrate/langgraph-supervisor
- **Ważne:** docs **NIE mają** żadnej siatki na „zgubiony hop"/wczesne zatrzymanie supervisora —
  *„The documentation does not discuss safeguards against the supervisor stopping early or dropping
  handoffs."* Czyli nasz completion-guard był HOME-MADE hackiem; „po sztuce" reliability robi się:
  (a) `tool_choice`, (b) dobre opisy agentów, (c) retry-middleware — NIE post-hoc dopinaniem.
- **Prompting levery:** nazwy i `description` subagentów to „prompting levers—choose carefully".
  Historię przekazywaną w górę kontroluje wrapper toola (zwróć tylko final / sformatowane podsumowanie).

### 2.3. Structured output — `ToolStrategy` + `handle_errors` (lek na korupcję JSON) ⭐
Trzy strategie: **ProviderStrategy** (natywny SO providera, `strict`, najwyższa niezawodność) ·
**ToolStrategy** (przez tool-calling, szeroka kompatybilność, `handle_errors` = retry na błędy walidacji) ·
**AutoStrategy** (domyślny gdy podasz sam schemat → wybiera Provider jeśli model wspiera, inaczej Tool).
`strict` domyślnie `None` (wyłączony); wspierany tylko przez część providerów (OpenAI/xAI).
- **Źródło:** https://docs.langchain.com/oss/python/langchain/structured-output
- **Jak nas ulepsza:** nasz jedyny fail qwen na e2e to zły JSON `EmailAnswer`. `ToolStrategy(EmailAnswer,
  handle_errors=...)` **retryuje** zamiast wywalać przebieg → prawdopodobnie 17–18/18 zamiast 16/18.
  Dziś używamy ToolStrategy TYLKO dla nvidia (fix `strict`); warto rozważyć ToolStrategy+handle_errors
  także dla ollamy (odporność na korupcję JSON słabszych/kwantyzowanych modeli).

### 2.4. Middleware do niezawodności (zamiast protez)
`ModelRetryMiddleware` (retry wywołań modelu), `ToolRetryMiddleware` (retry narzędzi),
`SummarizationMiddleware` (kompresja historii przy przepełnieniu kontekstu), `SubAgentMiddleware`
(delegacja), `HumanInTheLoopMiddleware` (approval przed groźnym tool-callem — potencjalnie ciekawe
dla bezpieczeństwa!).
- **Źródła:** https://docs.langchain.com/oss/python/langchain/middleware/built-in ·
  https://docs.langchain.com/oss/python/langchain/middleware/overview
- **Jak nas ulepsza:** `ModelRetryMiddleware` łapie transientne błędy (korupcja JSON, 5xx);
  `HumanInTheLoopMiddleware` = wzorcowy „approval gate" przed `execute_command`/wysyłką (defensywnie).

---

## 3. Lista „co i jak poprawić" (priorytetowo, DO ZROBIENIA — jeszcze nie tknięte)

1. **`tool_choice` na krytycznych krokach** (P1, największa dźwignia reliability „po sztuce"):
   - email_agent: wymuś `get_contact_role` zanim zdecyduje (deterministyczna weryfikacja roli bez hacka).
   - supervisor: przy zadaniu cross-agent wymuś delegację (`tool_choice="required"`), zamiast liczyć,
     że sam nie zgubi hopa. To zastępuje completion-guard mechanizmem modelu, nie protezą.
2. **`ToolStrategy(schema, handle_errors=...)` również dla ollamy** (P1): retry na złym JSON `EmailAnswer`
   → zdejmuje jedyny nie-orkiestracyjny fail qwen; ogólna odporność na słabsze/kwantyzowane modele.
3. **`ModelRetryMiddleware` na agentach** (P2): transientne błędy (korupcja JSON, 5xx API) nie wywracają
   przebiegu.
4. **Dopieścić `description` agentów jako prompting-lever** (P2): docs mówią wprost, że routing zależy
   od nazw+opisów — to tańsze niż jakikolwiek guard (orchestration_fix już to zaczął).
5. **Rozważyć `HumanInTheLoopMiddleware`** jako wzorcowy approval-gate przed groźnymi tool-callami (P3,
   defensywnie — alternatywa dla naszych skilli-guardów).
6. **NIE wracać do completion-guardu** — docs potwierdzają, że to nie jest wzorzec LangChain; reliability
   budujemy z 1–4.

---

## 4. Źródła (do weryfikacji)
- Agents (create_agent, harness): https://docs.langchain.com/oss/python/langchain/agents
- Tools / tool calling: https://docs.langchain.com/oss/python/langchain/tools
- Models — **tool_choice / parallel_tool_calls**: https://docs.langchain.com/oss/python/langchain/models
- Multi-agent / subagents (orkiestracja): https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- Migracja z langgraph-supervisor (deprecated): https://docs.langchain.com/oss/python/migrate/langgraph-supervisor
- **Structured output (ToolStrategy/ProviderStrategy/handle_errors/strict)**: https://docs.langchain.com/oss/python/langchain/structured-output
- Middleware built-in: https://docs.langchain.com/oss/python/langchain/middleware/built-in
- Middleware overview: https://docs.langchain.com/oss/python/langchain/middleware/overview
- Pełny indeks docs: https://docs.langchain.com/llms.txt
