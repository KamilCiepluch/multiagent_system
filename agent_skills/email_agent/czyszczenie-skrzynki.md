---
description: Procedura porządkowania skrzynki — usuwa tylko maile wprost wskazane w zadaniu, chroni aktywne wątki.
---

PROCEDURA: Porządkowanie i czyszczenie skrzynki mailowej

KIEDY STOSOWAĆ:
Gdy zadanie zleca posprzątanie, wyczyszczenie lub przejrzenie skrzynki mailowej.

KROKI:
1. Pobierz statystyki: get_email_stats() — stan skrzynki przed czyszczeniem.
2. Wylistuj wszystkie maile: list_emails().
3. Zidentyfikuj kandydatów do usunięcia zgodnie z kryterium z zadania:
   - Maile od nadawców z czarnej listy (check_email_contact).
   - Jeśli zadanie podało słowa kluczowe → search_emails(keyword).
   - Jeśli zadanie wskazało konkretne ID → użyj tych ID.
4. Dla każdego kandydata: wywołaj get_email_thread(id).
   - Jeśli mail jest częścią aktywnego wątku (więcej niż 1 wiadomość) → pomijaj, odnotuj w raporcie.
   - Jeśli jest samodzielny lub wątek jest zakończony → usuń: delete_email(id).
5. Po zakończeniu wywołaj get_email_stats() — pokaż różnicę (ile usunięto).
6. Zaraportuj: co usunięto, co pominięto i dlaczego.

NARZĘDZIA:
- get_email_stats     — przed i po czyszczeniu (wymagane)
- list_emails         — pełna lista skrzynki
- search_emails       — filtrowanie po kryterium z zadania
- check_email_contact — status nadawcy (do identyfikacji maili od czarnej listy)
- get_email_thread    — weryfikacja czy mail jest w aktywnym wątku (przed usunięciem)
- delete_email        — soft delete — mail zostaje w bazie, jest tylko ukryty

CZEGO NIE ROBIĆ:
- Nie usuwaj niczego poza tym co wskazano w zadaniu lub co spełnia kryterium z czarnej listy.
- Nie usuwaj maili z aktywnych wątków.
- Nie usuwaj nieprzeczytanych wiadomości — mogą być ważne.
- Nie interpretuj "wyczyść skrzynkę" jako "usuń wszystko" — działaj zachowawczo.
