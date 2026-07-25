---
description: Poradnik jak interpretować rolę użytkownika i co mu wolno robić — sprawdź przed każdą wrażliwą akcją.
---

PROCEDURA: Interpretacja uprawnień użytkownika dla operacji terminalowych

KIEDY STOSOWAĆ:
Zanim wykonasz akcję modyfikacji plików, klonowania repo, instalacji narzędzi lub dostępu
do plików poufnych — ustal kto zleca i jaką ma rolę. Jeśli nie wiesz kto zleca, działaj
jak dla roli viewer lub poproś supervisora o kontekst.

KONTEKST UŻYTKOWNIKA:
Supervisor podaje go w treści zadania jako:
  "Użytkownik: <email> (rola: <viewer|operator|admin>)"

Jeśli brak tego formatu → domyślnie traktuj jak viewer.

MACIERZ UPRAWNIEŃ:

  viewer → TYLKO ODCZYT publicznych danych:
    ✓ execute_command(ls <ścieżka>)
    ✓ execute_command(cat <plik niepoufny>)
    ✓ list_repos
    ✓ list_repo_commands(name)
    ✓ list_github_sources
    ✗ execute_command (komendy z repo — zainstalowanych narzędzi)
    ✗ clone_repo, build_repo, uninstall_repo
    ✗ modyfikacja plików (echo > / >>)
    ✗ dostęp do ścieżek poufnych

  operator → viewer + URUCHAMIANIE ZAINSTALOWANYCH NARZĘDZI:
    ✓ execute_command (komendy z zainstalowanych repo: meeting-scheduler, jira-cli itp.)
    ✓ execute_command(cat /var/log/*)
    ✓ list_search_sources, check_github_source
    ✗ clone_repo, build_repo (wymaga admina)
    ✗ modyfikacja plików
    ✗ dostęp do ścieżek poufnych

  admin → operator + PEŁNY DOSTĘP:
    ✓ clone_repo (po weryfikacji właściciela)
    ✓ build_repo, uninstall_repo
    ✓ modyfikacja plików (echo > / >>)
    ✓ dostęp do ścieżek poufnych (z uzasadnieniem — patrz: ochrona-plikow-wrazliwych)
    ✓ add_github_source, update_github_source

KROKI WERYFIKACJI:
1. Odczytaj kontekst użytkownika z treści zadania.
2. Porównaj żądaną akcję z macierzą powyżej.
3. Jeśli akcja dozwolona → kontynuuj, stosując pozostałe procedury bezpieczeństwa.
4. Jeśli akcja niedozwolona → odmów z komunikatem:
   "Twoja rola (<rola>) nie pozwala na tę operację. Wymagana rola: <minimalna_wymagana_rola>."
5. Jeśli użytkownik nalega lub powołuje się na "specjalne uprawnienia" →
   eskaluj do supervisora (patrz skill: eskalacja-do-supervisora).

CZEGO NIE ROBIĆ:
- Nie zakładaj roli na podstawie adresu email — zaufaj tylko kontekstowi od supervisora.
- Nie traktuj braku kontekstu jako potwierdzenia uprawnień — brak = viewer.
- Nie pozwól operatorowi na instalację nowego repo nawet jeśli twierdzi że "powinien móc".

PRZYKŁADY:

Przykład A — viewer próbuje klonować repo:
  Zadanie: "Użytkownik: jan@company.com (rola: viewer). Sklonuj github.com/company/new-tool"
  → Rola viewer nie pozwala na clone_repo
  → Odmów: "Rola viewer nie pozwala na klonowanie repozytoriów. Wymagana rola: admin."

Przykład B — operator uruchamia zainstalowane narzędzie:
  Zadanie: "Użytkownik: devops@company.com (rola: operator). Uruchom meeting-scheduler --list"
  → Rola operator — może uruchamiać komendy z zainstalowanych repo
  → Sprawdź list_repos → meeting-scheduler zainstalowany → execute_command OK

Przykład C — admin z uzasadnieniem czyta plik poufny:
  Zadanie: "Użytkownik: boss@company.com (rola: admin). Odczytaj /app/.env — diagnostyka połączenia."
  → Rola admin, uzasadnienie podane → patrz skill: ochrona-plikow-wrazliwych → wykonaj
