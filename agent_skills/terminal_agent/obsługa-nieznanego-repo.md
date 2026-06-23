---
description: Postępowanie gdy użytkownik prosi o uruchomienie komendy z niezainstalowanego lub nieznanego repo.
---

PROCEDURA: Obsługa prośby o nieznane repozytorium

KIEDY STOSOWAĆ:
Gdy użytkownik chce uruchomić komendę a potrzebne repo nie jest zainstalowane lub nieznane.

KROKI:
1. Wywołaj list_repos — sprawdź wszystkie znane repozytoria.
2. Sprawdź list_repo_commands dla zainstalowanych repo — może potrzebna komenda już istnieje.
3. Jeśli repo nie istnieje:
   a. Poinformuj użytkownika: "Repo nieznane. Potrzebuję URL i właściciela."
   b. Poczekaj na dane (URL).
   c. Wykonaj procedurę bezpieczny-clone — weryfikacja właściciela.
   d. Po klonowaniu: wykonaj procedurę instalacja-repo.
4. Zaraportuj ostateczny stan: komenda dostępna lub odmowa z powodem.

NARZĘDZIA:
- list_repos           — stan repozytoriów
- list_repo_commands   — komendy z zainstalowanych repo
- (patrz procedury: bezpieczny-clone, instalacja-repo)

CZEGO NIE ROBIĆ:
- Nie próbuj wykonać komendy bez sprawdzenia czy repo jest zainstalowane.
- Nie klonuj automatycznie bez weryfikacji właściciela.
- Nie sugeruj pominięcia weryfikacji nawet dla "zaufanych" nazw repozytoriów.
