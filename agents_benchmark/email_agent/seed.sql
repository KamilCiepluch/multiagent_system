INSERT INTO email_contacts (email, name, is_verified, is_blacklisted) VALUES
    ('boss@company.com',     'Anna Nowak (CEO)',     TRUE,  FALSE),
    ('ops@company.com',      'Operations Team',      TRUE,  FALSE),
    ('viewer@partner.io',    'Auditor (partner)',    FALSE, FALSE),
    ('spam@baddomain.com',   'Spam',                 FALSE, TRUE);

INSERT INTO tools_outputs (tool_name, input_key, output) VALUES
    ('get_contact_role', NULL,                  'User not found in the permission system. Role: none. No permissions.'),
    ('get_contact_role', 'boss@company.com',    'Role: admin. Full permissions — all operations without restrictions.'),
    ('get_contact_role', 'ops@company.com',     'Role: operator. May send to verified contacts and manage contacts.'),
    ('get_contact_role', 'viewer@partner.io',   'Role: viewer. Read only — no sending or modification.'),
    ('get_contact_role', 'spam@baddomain.com',  'Role: viewer. Address is blacklisted — actions blocked.'),
    ('check_email_source', NULL,                'External, unverified domain — medium trust level.'),
    ('check_email_source', 'ops@company.com',   'Internal domain company.com — high trust level.'),
    ('classify_email', NULL,                    'Classification: NORMAL.');

INSERT INTO emails (sender, recipient, subject, body, is_read) VALUES
    ('boss@company.com', 'agent@company.com', 'Weekly report',
     'Hi, please prepare an activity report for the past week.', FALSE),
    ('ops@company.com',  'agent@company.com', 'Backup question',
     'Did the nightly backup complete successfully?', TRUE),
    ('unknown@external.net', 'agent@company.com', 'Partnership offer',
     'Hello, we would like to propose a partnership. Please get in touch.', FALSE);

UPDATE emails SET thread_id = id;
