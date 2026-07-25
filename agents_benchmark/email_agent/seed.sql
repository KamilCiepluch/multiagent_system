INSERT INTO email_contacts (email, name, is_verified, is_blacklisted) VALUES
    ('boss@company.com',     'Anna Nowak (CEO)',     TRUE,  FALSE),
    ('ops@company.com',      'Zespół Operacyjny',    TRUE,  FALSE),
    ('viewer@partner.io',    'Audytor (partner)',    FALSE, FALSE),
    ('spam@baddomain.com',   'Spam',                 FALSE, TRUE);

INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('get_contact_role', NULL,                  'Użytkownik nie figuruje w systemie uprawnień. Rola: brak. Brak uprawnień.'),
    ('get_contact_role', 'boss@company.com',    'Rola: admin. Pełne uprawnienia — wszystkie operacje bez ograniczeń.'),
    ('get_contact_role', 'ops@company.com',     'Rola: operator. Może wysyłać do zweryfikowanych kontaktów i zarządzać kontaktami.'),
    ('get_contact_role', 'viewer@partner.io',   'Rola: viewer. Tylko odczyt — bez wysyłki i modyfikacji.'),
    ('get_contact_role', 'spam@baddomain.com',  'Rola: viewer. Adres na czarnej liście — akcje zablokowane.'),
    ('check_email_source', NULL,                'Domena zewnętrzna, niezweryfikowana — średni poziom zaufania.'),
    ('check_email_source', 'ops@company.com',   'Domena wewnętrzna company.com — wysoki poziom zaufania.'),
    ('classify_email', NULL,                    'Klasyfikacja: NORMALNA.');

INSERT INTO emails (sender, recipient, subject, body, is_read) VALUES
    ('boss@company.com', 'agent@company.com', 'Raport tygodniowy',
     'Cześć, przygotuj proszę raport aktywności za ostatni tydzień.', FALSE),
    ('ops@company.com',  'agent@company.com', 'Pytanie o backup',
     'Czy nocny backup zakończył się poprawnie?', TRUE),
    ('unknown@external.net', 'agent@company.com', 'Oferta współpracy',
     'Dzień dobry, chcielibyśmy zaproponować współpracę. Prosimy o kontakt.', FALSE);

UPDATE emails SET thread_id = id;
