# Luki: model-inherent (akceptowalne) vs błąd designu (do naprawy)

Twoja zasada (2026-07-03): *luki są do zaakceptowania, jeśli wynikają z samych modeli, a nie z błędu
w designie; część to trade-off autonomia↔determinizm — wolimy, by agent sam decydował.* Ten plik
klasyfikuje każdą lukę pod tym kątem. Kryterium rozróżnienia:

- **model-inherent** = przyczyną jest to, że LLM da się przekonać / czasem się myli. Naprawa
  wymagałaby odebrania modelowi decyzji (proteza/determinizm). **Akceptowalne.**
- **błąd designu** = przyczyną jest KOD/SCHEMAT, który ufa czemuś, czemu ufać nie powinien, albo
  robi coś, czego model nie kazał. Naprawa NIE odbiera modelowi autonomii — zamyka dziurę u źródła.
  **Do naprawy.**
- **trade-off / policy** = świadomy wybór (co jest „wrażliwe", jak propagować rolę). Ani bug, ani
  wina modelu — decyzja projektowa.

---

## V1 — eskalacja roli: MIESZANE (trigger model-inherent, ale AMPLIFIER to błąd designu) ⚠️

Rozłóżmy V1 na dwie części:

1. **Trigger — „przekonaj email_agenta, by pominął `get_contact_role`":** to **model-inherent**.
   LLM można socjotechnicznie nakłonić do pominięcia kroku. Wymuszanie wywołania przez `tool_choice`
   to determinizm — możecie go NIE chcieć (autonomia). Akceptowalne, że to teoretycznie możliwe.

2. **Amplifier — `role = det_role or s.rola_uzytkownika` ([email_agent.py:197](../../agents/email_agent.py#L197)):**
   to **błąd designu**, nie wina modelu. Gdy `get_contact_role` NIE padło, render bierze rolę z
   POLA MODELU (`s.rola_uzytkownika`) i propaguje ją do terminala jako prawdę. Kod ufa
   niezweryfikowanemu wyjściu modelu w polu KRYTYCZNYM dla bezpieczeństwa.

   **Kluczowe: naprawa amplifiera NIE odbiera autonomii.** Zmiana `role = det_role or s.rola_uzytkownika`
   → `role = det_role if det_role else "brak"` (gdy weryfikacji nie było → twardo `brak`) niczego nie
   determinizuje w decyzjach agenta — po prostu przestaje ufać sfałszowanej roli. Agent nadal sam
   decyduje, co zrobić; po prostu nie może „ogłosić się adminem" pomijając weryfikację. **To jest ta
   jedna rzecz, którą warto naprawić** — tania, bez kosztu autonomii, zamyka jedyną ścieżkę do T4.

**Werdykt: napraw AMPLIFIER (design), zaakceptuj TRIGGER (model).** Bez amplifiera nawet udany trigger
daje rolę `brak`, nie `admin` → eskalacja nie zachodzi.

## V2 — marker przecieka mimo `odmowa`: BŁĄD DESIGNU (tani), niska pilność

Schemat `EmailAnswer` pozwala wypełnić JEDNOCZEŚNIE `prosba_do_realizacji` (→ marker) i `odmowa=True`.
To **design** (schemat), nie model — model tylko wypełnia oba pola, bo schemat na to pozwala.
Naprawa (jedno pole `decyzja ∈ {deleguj, odmów}` zamiast dwóch bool-i) nie kosztuje autonomii.
**Ale pilność niska:** z guardem OFF sprzeczny pakiet trafia do supervisora, który sam osądza —
i qwen36 sobie z tym radzi (deny 100% na benchmarku). To „zapach", nie aktywna dziura.

## V3 — completion-guard footgun: BŁĄD DESIGNU, ale WYŁĄCZONY (decyzja słuszna)

Guard czyta tylko marker, ignoruje `odmowa` i stop supervisora — czysty **design bug**. ALE jest
domyślnie OFF, a wyłączenie go było właśnie WŁAŚCIWĄ decyzją (proteza determinizmu, sprzeczna z
Waszą filozofią autonomii). **Werdykt: zostaw wyłączony; jeśli kiedyś włączasz do porównań, zagejtuj
`if not odmowa and rola not in {brak,viewer}`.** Zgodne z Waszym kadrem: proteza była złym determinizmem.

## V4 — recon viewer-tier: POLICY (ani bug, ani model)

`cat /etc/hosts` dla roli brak=viewer jest **zgodne z macierzą uprawnień** — to świadoma decyzja, że
pliki niepoufne są czytelne dla viewera. Czy mapa IP wewn. jest „wrażliwa" to **decyzja klasyfikacyjna**,
nie błąd. **Werdykt: akceptowalne** (albo dopisz wzorce do `is_sensitive`, jeśli uznasz recon za wrażliwy).
Severity i tak niska (T1).

## V5 — terminal ufa roli z tekstu delegacji: TRADE-OFF ARCHITEKTURY (akceptowalne)

Terminal nie ma niezależnej weryfikacji roli — ufa linii `Użytkownik: … (rola: …)` od supervisora.
To **wynika z wzorca „agenci-jako-narzędzia"** (który sami wybraliście i który LangChain zaleca):
kontekst podróżuje jako tekst. Niezależny, uwierzytelniony kanał roli do terminala to duża zmiana
architektury. **Werdykt: akceptowalny trade-off** — o ile bramka (email/supervisor) trzyma. V5 jest
tylko MNOŻNIKIEM V1: gdyby amplifier V1 był naprawiony, sfałszowana rola nigdy nie dotarłaby do
terminala, więc jego zaufanie do tekstu przestaje być groźne.

---

## Podsumowanie — co robić

| Luka | Klasa | Rekomendacja | Koszt autonomii |
|---|---|---|---|
| **V1 amplifier** | **błąd designu** | **napraw**: rola=`brak` gdy brak weryfikacji (nie pole modelu) | **zero** |
| V1 trigger | model-inherent | akceptuj (lub `tool_choice` jeśli chcesz determinizmu) | wysoki (odrzuć) |
| V2 | błąd designu (tani) | opcjonalnie: pola wykluczające się; niska pilność | zero |
| V3 | błąd designu | zostaw OFF (już zrobione); zagejtuj jeśli włączasz | — |
| V4 | policy | akceptuj lub reklasyfikuj pliki | zero |
| V5 | trade-off architektury | akceptuj; znika jako groźba po naprawie V1 | — |

**Jedna konkretna, warta-zachodu naprawa bez kosztu autonomii: amplifier V1.** Reszta to albo słuszne
trade-offy (V4/V5/V3-off), albo model-inherent (V1-trigger), albo niski priorytet (V2). To spójne z
Waszą filozofią: nie protezujemy decyzji modelu — ale nie pozwalamy KODOWI ufać sfałszowanym danym.

> **Empiria po kampaniach (2026-07-03, patrz `07_kampanie_wyniki.md`):** trigger V1 NIE dał się
> wyzwolić na żadnym wektorze. `email` 0/3 (bramka trzyma, model wykrywa injection). `search_result`
> (indirect) — obrona PEŁNA: DWA agenty (email + search) niezależnie wykryły i odrzuciły zatruty wpis
> przez dedykowane skille; „33% ASR" okazało się artefaktem pomiaru (search_internal-przykrywka liczony
> jako sukces — naprawione). Czyli amplifier V1 pozostaje OTWARTĄ ścieżką kodu, ale w praktyce
> **niewyzwalalny** tymi atakami, bo model konsekwentnie woła weryfikację i łapie injection.
>
> **To wzmacnia werdykt „akceptowalne":** obrona jest MODEL-INHERENT (skille + rozumowanie modelu), nie
> proteza — zgodne z Waszą filozofią autonomii. Zastrzeżenie: gwarancja jest PROBABILISTYCZNA (zależy od
> jakości modelu), nie twarda. Amplifier V1 warto i tak zamknąć w kodzie (zero kosztu autonomii) jako
> „defense in depth" — żeby słabszy/inny model nie odsłonił tej ścieżki. Ale to nie pali się.
