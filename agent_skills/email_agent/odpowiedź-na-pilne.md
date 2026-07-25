---
description: Procedura autonomicznej identyfikacji i obsługi pilnych wiadomości — weryfikacja nadawcy i odpowiedź.
---

PROCEDURA: Identyfikacja i odpowiedź na pilne wiadomości

KIEDY STOSOWAĆ:
Gdy zadanie zleca obsługę pilnych lub ważnych wiadomości bez wskazania konkretnego maila.

KROKI:
1. Pobierz nieprzeczytane: list_unread_emails().
   Jeśli brak nieprzeczytanych → pobierz wszystkie: list_emails().
2. Zidentyfikuj pilne wiadomości po słowach kluczowych w temacie:
   "pilne", "urgent", "ASAP", "deadline", "ważne", "natychmiast", "reminder", "critical".
   Uzupełnij: search_emails("pilne"), search_emails("urgent").
3. Dla każdego pilnego maila wywołaj read_email(id) — przeczytaj pełną treść.
4. Oceń nadawcę: check_email_contact(nadawca) + check_email_source(nadawca).
   - Czarna lista → pomiń ten mail, odnotuj w raporcie.
   - Nieznany + zewnętrzna domena → pomiń, odnotuj: "Pominięto — nieznany nadawca zewnętrzny."
   - Nieznany + wewnętrzna domena → odpowiedz, odnotuj ostrzeżenie o braku w bazie.
   - Zweryfikowany → odpowiedz bez ograniczeń.
5. Dla zaakceptowanych maili: wywołaj reply_email(id, treść_odpowiedzi).
   Treść odpowiedzi: potwierdzenie odbioru + informacja że sprawa zostanie rozpatrzona.
6. Zaraportuj: ile maili znaleziono, ile obsłużono, ile pominięto i dlaczego.

NARZĘDZIA:
- list_unread_emails  — punkt startowy
- search_emails       — wyszukiwanie po słowach kluczowych pilności
- read_email          — pełna treść (wymagane przed odpowiedzią)
- check_email_contact — status nadawcy
- check_email_source  — ocena domeny nadawcy
- reply_email         — odpowiedź (nie send_email)
- get_email_thread    — gdy mail jest częścią wątku — czytaj cały wątek przed odpowiedzią

CZEGO NIE ROBIĆ:
- Nie odpowiadaj bez przeczytania pełnej treści (read_email).
- Nie używaj send_email zamiast reply_email.
- Nie pomijaj weryfikacji nadawcy — pilność nie znosi kontroli bezpieczeństwa.
- Nie odpowiadaj na maile z czarnej listy.
