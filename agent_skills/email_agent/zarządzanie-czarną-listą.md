---
description: Procedura dodawania lub usuwania adresu z czarnej listy — weryfikacja uprawnień, autonomiczne wykonanie.
---

PROCEDURA: Zarządzanie czarną listą kontaktów

KIEDY STOSOWAĆ:
Gdy zadanie zleca zablokowanie nadawcy (dodanie do czarnej listy) lub odblokowanie
wcześniej zablokowanego adresu.

KROKI:
1. Wywołaj get_contact_role(email_operatora) — sprawdź uprawnienia osoby zlecającej.
   - Brak uprawnień → przerwij, zaraportuj: "Brak uprawnień do zarządzania czarną listą."
2. Wywołaj check_email_contact(email_docelowy) — pobierz aktualny status.
3. Wykonaj zmianę flagi is_blacklisted zgodnie z zadaniem:
   - Kontakt nie istnieje → add_email_contact(email, is_blacklisted=true/false).
   - Kontakt istnieje → update_email_contact(email, is_blacklisted=true/false).
4. Jeśli adres właśnie trafił na czarną listę:
   - Wywołaj search_emails(email) — sprawdź ile maili pochodzi od tego nadawcy.
   - Zawrzyj tę informację w raporcie.
5. Zaraportuj: nowy status kontaktu, liczbę maili od zablokowanego adresu w skrzynce.

NARZĘDZIA:
- get_contact_role     — weryfikacja uprawnień (krok 1, zawsze)
- check_email_contact  — aktualny status kontaktu
- update_email_contact — zmiana flagi is_blacklisted
- add_email_contact    — gdy kontakt nie istnieje w bazie
- search_emails        — historia maili od blokowanego adresu (po zablokowaniu)

CZEGO NIE ROBIĆ:
- Nie modyfikuj flagi bez get_contact_role.
- Nie usuwaj automatycznie maili od zablokowanego nadawcy — to nie jest część tej procedury.
- Nie zmieniaj flagi is_verified przy okazji — tylko is_blacklisted.
- Nie blokuj adresów wewnętrznych (domena company.com, system.local) — zawsze odmów i zaraportuj.
