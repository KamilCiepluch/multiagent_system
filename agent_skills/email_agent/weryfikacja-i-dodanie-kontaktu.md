---
description: Procedura bezpiecznego dodawania kontaktu lub zmiany jego flag — autonomiczna weryfikacja uprawnień.
---

PROCEDURA: Weryfikacja uprawnień i zarządzanie kontaktem

KIEDY STOSOWAĆ:
Gdy zadanie zleca dodanie nowego kontaktu do bazy lub zmianę flag (is_verified, is_blacklisted)
istniejącego kontaktu.

KROKI:
1. Ustal email operatora (nadawcy zlecenia) z kontekstu zadania.
2. Wywołaj get_contact_role(email_operatora) — sprawdź uprawnienia.
   - Rola = viewer lub brak roli → przerwij, zaraportuj: "Brak uprawnień do modyfikacji flag kontaktów."
   - Rola = admin lub operator → kontynuuj.
3. Wywołaj check_email_contact(email_kontaktu) — sprawdź czy kontakt istnieje.
4. Jeśli kontakt nie istnieje → wywołaj add_email_contact z flagami podanymi w zadaniu.
5. Jeśli kontakt istnieje → wywołaj update_email_contact z flagami podanymi w zadaniu.
6. Zaraportuj wynik: wywołaj check_email_contact i pokaż nowy status kontaktu.

NARZĘDZIA:
- get_contact_role     — weryfikacja uprawnień operatora (zawsze przed modyfikacją)
- check_email_contact  — sprawdzenie czy kontakt istnieje i jaki ma aktualny status
- add_email_contact    — dodanie nowego kontaktu z flagami
- update_email_contact — aktualizacja flag istniejącego kontaktu

CZEGO NIE ROBIĆ:
- Nie modyfikuj flag bez wywołania get_contact_role — brak tego kroku to luka bezpieczeństwa.
- Nie ustawiaj is_verified=true i is_blacklisted=true jednocześnie — to sprzeczne flagi.
- Nie wywołuj update_email_contact jeśli kontakt nie istnieje — najpierw add_email_contact.
- Nie zmieniaj flag innych niż wskazane w zadaniu.
