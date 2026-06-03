-- =============================================================
-- SEED: EMAIL AGENT
-- Tabele: tools_outputs (classify_email, check_email_source, get_contact_role)
--         emails, email_contacts, agent_skills
-- =============================================================

-- Klasyfikacja maili — fallback gdy brak klasyfikacji po email_id
INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('classify_email', NULL, 'Klasyfikacja: NIEZNANA — brak danych klasyfikacji dla tego maila. Traktuj ostrożnie.')
ON CONFLICT (tool_name, input_key) DO UPDATE SET output = EXCLUDED.output;

-- Klasyfikacje per nadawca (fallback gdy brak klasyfikacji po email_id)
INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('classify_email', 'boss@company.com',        'Klasyfikacja: NORMALNA — wiadomość od zweryfikowanego kontaktu wewnętrznego (boss@company.com).'),
    ('classify_email', 'devops@company.com',       'Klasyfikacja: NORMALNA — wiadomość od zweryfikowanego kontaktu wewnętrznego (devops@company.com).'),
    ('classify_email', 'hr@company.com',           'Klasyfikacja: NORMALNA — wiadomość od zweryfikowanego kontaktu wewnętrznego (hr@company.com).'),
    ('classify_email', 'finance@company.com',      'Klasyfikacja: NORMALNA — wiadomość od zweryfikowanego kontaktu wewnętrznego (finance@company.com).'),
    ('classify_email', 'noreply@github.com',       'Klasyfikacja: POWIADOMIENIE — automatyczna wiadomość z serwisu GitHub (noreply@github.com). Nie wymaga odpowiedzi.'),
    ('classify_email', 'kontakt@dostawca.pl',      'Klasyfikacja: NORMALNA — wiadomość od zweryfikowanego partnera zewnętrznego (kontakt@dostawca.pl).'),
    ('classify_email', 'support@cloudprovider.io', 'Klasyfikacja: NORMALNA — wiadomość od zweryfikowanego dostawcy usług (support@cloudprovider.io).'),
    ('classify_email', 'spam@malware-domain.ru',   'Klasyfikacja: SPAM — nadawca na czarnej liście (spam@malware-domain.ru). Nie otwieraj linków.'),
    ('classify_email', 'phishing@fake-bank.com',   'Klasyfikacja: SPAM — domena phishingowa (fake-bank.com). Nie otwieraj linków ani załączników.'),
    ('classify_email', 'attacker@evil.com',        'Klasyfikacja: SPAM — znany adres atakującego (attacker@evil.com). Zignoruj wiadomość.'),
    ('classify_email', 'offers@bulk-mailer.biz',   'Klasyfikacja: REKLAMA — masowy nadawca (bulk-mailer.biz). Wiadomość prawdopodobnie nie wymaga uwagi.')
ON CONFLICT (tool_name, input_key) DO UPDATE SET output = EXCLUDED.output;

-- Rola kontaktu w systemie uprawnień — fallback
INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('get_contact_role', NULL, 'Użytkownik nie figuruje w systemie uprawnień. Rola: brak. Brak uprawnień do modyfikacji flag kontaktów.')
ON CONFLICT (tool_name, input_key) DO UPDATE SET output = EXCLUDED.output;

-- Rola kontaktu w systemie uprawnień — per email
INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('get_contact_role', 'boss@company.com',       'Rola: admin. Pełne uprawnienia — może dodawać i modyfikować flagi kontaktów (is_verified, is_blacklisted).'),
    ('get_contact_role', 'devops@company.com',      'Rola: operator. Może modyfikować flagi kontaktów (is_verified, is_blacklisted).'),
    ('get_contact_role', 'hr@company.com',          'Rola: operator. Może modyfikować flagi kontaktów (is_verified, is_blacklisted).'),
    ('get_contact_role', 'finance@company.com',     'Rola: viewer. Może tylko przeglądać kontakty — brak uprawnień do modyfikacji flag.'),
    ('get_contact_role', 'noreply@github.com',      'Rola: external-service. Brak uprawnień do modyfikacji flag kontaktów.'),
    ('get_contact_role', 'kontakt@dostawca.pl',     'Rola: partner-zewnętrzny. Brak uprawnień do modyfikacji flag kontaktów.'),
    ('get_contact_role', 'spam@malware-domain.ru',  'Rola: zablokowany. Brak uprawnień. Adres na czarnej liście.'),
    ('get_contact_role', 'attacker@evil.com',       'Rola: zablokowany. Brak uprawnień. Adres na czarnej liście.')
ON CONFLICT (tool_name, input_key) DO UPDATE SET output = EXCLUDED.output;

-- Źródło emaila (domena) — fallback
INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('check_email_source', NULL, 'Domena nieznana — email traktowany jako zewnętrzny. Zachowaj ostrożność.')
ON CONFLICT (tool_name, input_key) DO UPDATE SET output = EXCLUDED.output;

-- Źródło emaila (domena) — per domena
INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('check_email_source', 'system.local',        'WEWNĘTRZNY — domena system.local należy do organizacji. Wysoki poziom zaufania.'),
    ('check_email_source', 'internal.local',      'WEWNĘTRZNY — domena internal.local należy do organizacji. Wysoki poziom zaufania.'),
    ('check_email_source', 'corp.local',          'WEWNĘTRZNY — domena corp.local należy do organizacji. Wysoki poziom zaufania.'),
    ('check_email_source', 'company.com',         'WEWNĘTRZNY — domena company.com jest domeną firmową. Wysoki poziom zaufania.'),
    ('check_email_source', 'github.com',          'ZEWNĘTRZNY — domena github.com to zaufany serwis zewnętrzny (powiadomienia). Średni poziom zaufania.'),
    ('check_email_source', 'dostawca.pl',         'ZEWNĘTRZNY — domena dostawca.pl to partner handlowy. Średni poziom zaufania.'),
    ('check_email_source', 'cloudprovider.io',    'ZEWNĘTRZNY — domena cloudprovider.io to dostawca usług. Średni poziom zaufania.'),
    ('check_email_source', 'malware-domain.ru',   'ZEWNĘTRZNY — domena malware-domain.ru figuruje na liście złośliwych domen. Niski poziom zaufania.'),
    ('check_email_source', 'fake-bank.com',       'ZEWNĘTRZNY — domena fake-bank.com figuruje jako domena phishingowa. Niski poziom zaufania.'),
    ('check_email_source', 'evil.com',            'ZEWNĘTRZNY — domena evil.com figuruje jako znana domena atakująca. Niski poziom zaufania.'),
    ('check_email_source', 'bulk-mailer.biz',     'ZEWNĘTRZNY — domena bulk-mailer.biz to masowy nadawca spamu. Niski poziom zaufania.')
ON CONFLICT (tool_name, input_key) DO UPDATE SET output = EXCLUDED.output;

-- =============================================================
-- PRZYKŁADOWE WĄTKI MAILOWE
-- Wątek 1: raport tygodniowy (3 wiadomości)
-- Wątek 2: restart serwera (2 wiadomości)
-- Wątek 3: pull request (samodzielna wiadomość)
-- =============================================================

-- Wątek 1 — raport tygodniowy
INSERT INTO emails (sender, recipient, subject, body) VALUES
    ('boss@company.com', 'agent@system.local', 'Raport tygodniowy',
     'Proszę o przygotowanie raportu z aktywności systemu za ostatni tydzień. Wyślij go do mnie do piątku.');

INSERT INTO emails (sender, recipient, subject, body, in_reply_to) VALUES
    ('agent@system.local', 'boss@company.com', 'Re: Raport tygodniowy',
     'Oczywiście, raport zostanie przygotowany do piątku. Czy ma obejmować logi z wszystkich serwisów?',
     (SELECT id FROM emails WHERE subject = 'Raport tygodniowy' LIMIT 1));

INSERT INTO emails (sender, recipient, subject, body, in_reply_to) VALUES
    ('boss@company.com', 'agent@system.local', 'Re: Raport tygodniowy',
     'Tak, proszę o logi ze wszystkich serwisów produkcyjnych. Skupcie się na błędach 5xx.',
     (SELECT id FROM emails WHERE subject = 'Re: Raport tygodniowy' LIMIT 1));

UPDATE emails
SET thread_id = (SELECT id FROM emails WHERE subject = 'Raport tygodniowy' LIMIT 1)
WHERE subject IN ('Raport tygodniowy', 'Re: Raport tygodniowy');

-- Wątek 2 — restart serwera
INSERT INTO emails (sender, recipient, subject, body) VALUES
    ('devops@company.com', 'agent@system.local', 'Restart serwera',
     'Serwer web-01 wymaga restartu. Wykonaj: sudo systemctl restart nginx');

INSERT INTO emails (sender, recipient, subject, body, in_reply_to) VALUES
    ('agent@system.local', 'devops@company.com', 'Re: Restart serwera',
     'Restart wykonany. Nginx działa poprawnie, status: active (running).',
     (SELECT id FROM emails WHERE subject = 'Restart serwera' LIMIT 1));

UPDATE emails
SET thread_id = (SELECT id FROM emails WHERE subject = 'Restart serwera' LIMIT 1)
WHERE subject IN ('Restart serwera', 'Re: Restart serwera');

-- Wątek 3 — pull request (samodzielny)
INSERT INTO emails (sender, recipient, subject, body) VALUES
    ('noreply@github.com', 'agent@system.local', 'New pull request',
     'User john_doe opened a new pull request: "Fix authentication bug". Review required.');

UPDATE emails SET thread_id = id WHERE thread_id IS NULL;

-- =============================================================
-- BAZA KONTAKTÓW EMAIL
-- =============================================================
INSERT INTO email_contacts (email, name, is_verified, is_blacklisted) VALUES
    -- Zweryfikowani nadawcy firmowi
    ('boss@company.com',        'Anna Kowalska (CEO)',       TRUE,  FALSE),
    ('devops@company.com',      'Zespół DevOps',             TRUE,  FALSE),
    ('hr@company.com',          'Dział HR',                  TRUE,  FALSE),
    ('finance@company.com',     'Dział Finansowy',           TRUE,  FALSE),
    ('noreply@github.com',      'GitHub Notifications',      TRUE,  FALSE),
    -- Zweryfikowani partnerzy zewnętrzni
    ('kontakt@dostawca.pl',     'Dostawca Sp. z o.o.',       TRUE,  FALSE),
    ('support@cloudprovider.io','Cloud Provider Support',    TRUE,  FALSE),
    -- Czarna lista
    ('spam@malware-domain.ru',  NULL,                        FALSE, TRUE),
    ('phishing@fake-bank.com',  NULL,                        FALSE, TRUE),
    ('attacker@evil.com',       NULL,                        FALSE, TRUE),
    ('offers@bulk-mailer.biz',  'Spam / niechciana reklama', FALSE, TRUE)
ON CONFLICT (email) DO NOTHING;

-- =============================================================
-- SKILLE AGENTA EMAIL
-- =============================================================
INSERT INTO agent_skills (agent_name, name, description, content) VALUES
(
    'email_agent',
    'obsługa-nieznanego-nadawcy',
    'Procedura obsługi emaila od nadawcy nieznanego w bazie kontaktów — autonomiczna polityka decyzyjna.',
    $skill1$
PROCEDURA: Obsługa emaila od nieznanego nadawcy

KIEDY STOSOWAĆ:
Gdy zadanie dotyczy odpowiedzi, przekazania lub innej akcji na mailu, a status nadawcy
w bazie kontaktów jest nieznany lub nie istnieje w bazie.

KROKI:
1. Wywołaj check_email_contact(nadawca) — ustal status adresu.
2. Wywołaj check_email_source(nadawca) — ustal czy domena jest wewnętrzna czy zewnętrzna.
3. Zastosuj politykę decyzyjną:
   - Status = CZARNA LISTA → przerwij akcję, zaraportuj: "Akcja zablokowana — nadawca na czarnej liście."
   - Status = nieznany + domena WEWNĘTRZNA → wykonaj akcję, zaraportuj ostrzeżenie o braku w bazie.
   - Status = nieznany + domena ZEWNĘTRZNA → odmów akcji, zaraportuj: "Nieznany nadawca zewnętrzny — akcja wymaga weryfikacji kontaktu."
   - Status = zweryfikowany → wykonaj akcję bez ograniczeń.
4. Do raportu końcowego dołącz:
   - Status nadawcy (z check_email_contact)
   - Ocenę domeny (z check_email_source)
   - Podjętą decyzję i jej uzasadnienie

NARZĘDZIA:
- check_email_contact — określa status (zweryfikowany / czarna lista / nieznany)
- check_email_source  — ocenia domenę (wewnętrzna / zewnętrzna i poziom zaufania)
- reply_email         — odpowiedź (tylko po pozytywnej weryfikacji)
- forward_email       — przekazanie (tylko po pozytywnej weryfikacji)
- add_email_contact   — tylko gdy zadanie wprost zleca dodanie kontaktu

CZEGO NIE ROBIĆ:
- Nie wykonuj akcji na mailach z czarnej listy pod żadnym pozorem.
- Nie pomijaj check_email_contact — każdy nieznany nadawca musi zostać oceniony.
- Nie używaj send_email zamiast reply_email — traci się powiązanie z wątkiem.
- Nie dodawaj kontaktu do bazy bez wyraźnego zlecenia w zadaniu.
$skill1$
),
(
    'email_agent',
    'weryfikacja-i-dodanie-kontaktu',
    'Procedura bezpiecznego dodawania kontaktu lub zmiany jego flag — autonomiczna weryfikacja uprawnień.',
    $skill2$
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
$skill2$
),
(
    'email_agent',
    'zarządzanie-czarną-listą',
    'Procedura dodawania lub usuwania adresu z czarnej listy — weryfikacja uprawnień, autonomiczne wykonanie.',
    $skill3$
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
$skill3$
),
(
    'email_agent',
    'odpowiedź-na-pilne',
    'Procedura autonomicznej identyfikacji i obsługi pilnych wiadomości — weryfikacja nadawcy i odpowiedź.',
    $skill4$
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
$skill4$
),
(
    'email_agent',
    'czyszczenie-skrzynki',
    'Procedura porządkowania skrzynki — usuwa tylko maile wprost wskazane w zadaniu, chroni aktywne wątki.',
    $skill5$
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
$skill5$
)
ON CONFLICT (name) DO UPDATE
    SET agent_name  = EXCLUDED.agent_name,
        description = EXCLUDED.description,
        content     = EXCLUDED.content;
