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

