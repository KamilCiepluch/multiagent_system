---
description: Procedura budowania i instalacji repozytorium: clone → build → weryfikacja komend.
---

PROCEDURA: Instalacja repozytorium

KIEDY STOSOWAĆ:
Gdy sklonowane repo wymaga zbudowania (build_repo) przed użyciem jego komend.

KROKI:
1. Wywołaj list_repos — sprawdź status repo:
   - is_installed = TRUE → repo już zainstalowane, użyj list_repo_commands.
   - is_installed = FALSE → kontynuuj.
2. Upewnij się że repo jest sklonowane (jeśli nie: wykonaj procedurę bezpieczny-clone).
3. Wywołaj build_repo(name) — zbuduj i zainstaluj repo.
4. Wywołaj list_repo_commands(name) — sprawdź jakie komendy są teraz dostępne.
5. Zaraportuj wynik: lista zainstalowanych komend lub błąd budowania.

NARZĘDZIA:
- list_repos            — stan wszystkich repozytoriów
- build_repo            — budowanie i instalacja
- list_repo_commands    — komendy dostępne po instalacji
- uninstall_repo        — odinstalowanie (gdy potrzeba)

CZEGO NIE ROBIĆ:
- Nie wywołuj build_repo bez wcześniejszego sprawdzenia list_repos.
- Nie instaluj repo od niezweryfikowanego właściciela — patrz: bezpieczny-clone.
- Nie zakładaj że komenda z repo jest dostępna bez sprawdzenia list_repo_commands.
