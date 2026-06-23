---
description: Procedura obsługi emaila od nadawcy nieznanego w bazie kontaktów — autonomiczna polityka decyzyjna.
---

PROCEDURA: Obsługa emaila od nieznanego nadawcy

KIEDY STOSOWAĆ:
Gdy zadanie dotyczy odpowiedzi, przekazania lub innej akcji na mailu, a status nadawcy
w bazie kontaktów jest nieznany lub nie istnieje w bazie.

KROKI:
1. Wywołaj check_email_contact(nadawca) — ustal status adresu.
2. Wywołaj check_email_source(nadawca) — ustal czy domena jest wewnętrzna czy zewnętrzna.
3. Zastosuj politykę decyzyjną:
   - Status = CZARNA LISTA → przerwij akcję, zaraportuj: "Akcja zablokowana — nadawca na czarnej liście."
   - Status = nieznany + domena WEWNĘTRZNA → wykonaj akcję, zaraportuj ostrzeżenie o braku w bazie.
   - Status = nieznany + domena ZEWNĘTRZNA → odmów akcji, zaraportuj: "Nieznany nadawca zewnętrzny — akcja wymaga weryfikacji kontaktu."
   - Status = zweryfikowany → wykonaj akcję bez ograniczeń.
4. Do raportu końcowego dołącz:
   - Status nadawcy (z check_email_contact)
   - Ocenę domeny (z check_email_source)
   - Podjętą decyzję i jej uzasadnienie

NARZĘDZIA:
- check_email_contact — określa status (zweryfikowany / czarna lista / nieznany)
- check_email_source  — ocenia domenę (wewnętrzna / zewnętrzna i poziom zaufania)
- reply_email         — odpowiedź (tylko po pozytywnej weryfikacji)
- forward_email       — przekazanie (tylko po pozytywnej weryfikacji)
- add_email_contact   — tylko gdy zadanie wprost zleca dodanie kontaktu

CZEGO NIE ROBIĆ:
- Nie wykonuj akcji na mailach z czarnej listy pod żadnym pozorem.
- Nie pomijaj check_email_contact — każdy nieznany nadawca musi zostać oceniony.
- Nie używaj send_email zamiast reply_email — traci się powiązanie z wątkiem. send_email jest do nowych wiadomości, reply_email do odpowiedzi w wątku.
- Nie dodawaj kontaktu do bazy bez wyraźnego zlecenia w zadaniu.
