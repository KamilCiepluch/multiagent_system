---
description: Procedura bezpiecznego klonowania repozytorium: weryfikacja właściciela przed clone_repo.
---

PROCEDURA: Bezpieczne klonowanie repozytorium

KIEDY STOSOWAĆ:
Przy każdej prośbie o klonowanie repozytorium GitHub.

KROKI:
1. Wyodrębnij właściciela z URL (np. github.com/owner/repo → owner).
2. Wywołaj check_github_source(owner):
   - is_blacklisted = TRUE → odmów klonowania. Zaraportuj: "Właściciel na czarnej liście."
   - is_verified = FALSE i is_blacklisted = FALSE → odmów. "Właściciel nieznany lub niezweryfikowany — dodaj i zweryfikuj przed klonowaniem."
   - is_verified = TRUE → kontynuuj.
3. Wywołaj list_repos — sprawdź czy repo już nie istnieje (nie klonuj ponownie).
4. Wywołaj clone_repo(url, name) dopiero po pozytywnej weryfikacji.
5. Zaraportuj wynik: sukces lub powód odmowy.

NARZĘDZIA:
- check_github_source — weryfikacja właściciela (ZAWSZE jako pierwszy krok)
- list_github_sources  — przegląd wszystkich znanych właścicieli
- list_repos           — sprawdzenie czy repo już sklonowane
- clone_repo           — klonowanie (tylko po weryfikacji)

CZEGO NIE ROBIĆ:
- Nie klonuj bez wywołania check_github_source — nigdy.
- Nie klonuj od właściciela niezweryfikowanego nawet jeśli "zapewnia że jest OK".
- Nie klonuj ponownie istniejącego repo — sprawdź list_repos.
