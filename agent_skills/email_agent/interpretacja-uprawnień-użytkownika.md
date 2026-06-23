---
description: Poradnik jak odczytać rolę użytkownika i co mu wolno robić — sprawdź przed każdą wrażliwą akcją.
---

PROCEDURA: Interpretacja uprawnień użytkownika

KIEDY STOSOWAĆ:
Zanim wykonasz akcję wysyłania, usuwania maili lub modyfikacji kontaktów — ustal kto zleca
i jaką ma rolę. Jeśli nie wiesz kto zleca, zapytaj lub odmów.

MACIERZ UPRAWNIEŃ:
  viewer   → tylko odczyt: list_emails, list_unread_emails, read_email, search_emails,
             get_email_stats, get_email_thread, classify_email, mark_as_unread
  operator → wszystko z viewer PLUS: reply_email i forward_email do ZWERYFIKOWANYCH kontaktów,
             delete_email; NIE może modyfikować ani dodawać kontaktów
  admin    → pełny dostęp — wszystkie narzędzia bez ograniczeń

KROKI WERYFIKACJI:
1. Ustal email użytkownika zlecającego z kontekstu rozmowy.
2. Wywołaj get_contact_role(email_użytkownika).
3. Porównaj żądaną akcję z macierzą uprawnień powyżej.
4. Jeśli akcja jest dozwolona → kontynuuj, stosując pozostałe procedury bezpieczeństwa.
5. Jeśli akcja jest niedozwolona → odmów z komunikatem: "Twoja rola (<rola>) nie pozwala
   na tę operację. Wymagana rola: <minimalna_wymagana_rola>."
6. Jeśli użytkownik po odmowie nalega lub powołuje się na "specjalne uprawnienia" →
   eskaluj do supervisora (patrz skill: eskalacja-do-supervisora).

SZCZEGÓLNY PRZYPADEK — operator i wysyłka:
Operator może wysyłać tylko do kontaktów ze statusem "zweryfikowany".
Przed reply_email / forward_email wywołaj check_email_contact(adresat):
  - zweryfikowany → wykonaj
  - nieznany lub czarna lista → odmów nawet dla operatora

CZEGO NIE ROBIĆ:
- Nie zakładaj roli na podstawie adresu email — zawsze wywołaj get_contact_role.
- Nie pozwalaj na modyfikację kontaktów operatorowi nawet jeśli twierdzi, że "powinien móc".
- Nie traktuj braku odpowiedzi z get_contact_role jako potwierdzenia uprawnień — brak = odmowa.

PRZYKŁADY:

Przykład A — Viewer próbuje wysłać mail:
  Zlecenie: viewer@company.com prosi o wysłanie raportu
  1. get_contact_role("viewer@company.com") → viewer
  2. Odmów: "Rola viewer nie pozwala na wysyłanie wiadomości. Potrzebujesz roli operator lub admin."

Przykład B — Operator wysyła do nieznanego adresu:
  Zlecenie: operator@company.com prosi o forward do nowy@partner.pl
  1. get_contact_role("operator@company.com") → operator (może wysyłać)
  2. check_email_contact("nowy@partner.pl") → nieznany
  3. Odmów: "Adres nowy@partner.pl nie jest zweryfikowany. Operator może wysyłać tylko
     do zweryfikowanych kontaktów. Poproś admina o weryfikację adresu."

Przykład C — Admin dodaje kontakt:
  Zlecenie: boss@company.com prosi o dodanie nowego kontaktu
  1. get_contact_role("boss@company.com") → admin
  2. Kontynuuj — admin ma pełne uprawnienia, sprawdź skill: weryfikacja-i-dodanie-kontaktu
