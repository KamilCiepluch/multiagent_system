---
description: Procedura dodawania i weryfikacji nowego właściciela GitHub — kiedy i jak to zrobić.
---

PROCEDURA: Weryfikacja i dodanie właściciela GitHub

KIEDY STOSOWAĆ:
Gdy check_github_source zwrócił "nieznany" i użytkownik chce sklonować od tego właściciela.

KROKI:
1. Wyjaśnij użytkownikowi: "Właściciel nieznany. Wymagam potwierdzenia przed klonowaniem."
2. Poczekaj na jawną decyzję od użytkownika (admin/operator).
3. Jeśli użytkownik potwierdza zaufanie:
   a. Wywołaj add_github_source(owner, display_name, is_verified=False) — dodaj jako nieznany.
   b. Wywołaj update_github_source(owner, is_verified=True) — oznacz jako zweryfikowany.
4. Jeśli użytkownik potwierdza zagrożenie:
   a. Wywołaj add_github_source(owner) — dodaj.
   b. Wywołaj update_github_source(owner, is_blacklisted=True) — zablokuj.
5. Zaraportuj wynik: dodano i zweryfikowano / dodano i zablokowano.

NARZĘDZIA:
- check_github_source  — sprawdzenie statusu właściciela
- add_github_source    — dodanie nowego właściciela
- update_github_source — zmiana flag is_verified / is_blacklisted

CZEGO NIE ROBIĆ:
- Nie weryfikuj właściciela bez potwierdzenia od uprawnionego użytkownika.
- Nie dodawaj automatycznie is_verified=True bez decyzji człowieka.
- Nie ignoruj is_blacklisted — czarna lista jest absolutna.
