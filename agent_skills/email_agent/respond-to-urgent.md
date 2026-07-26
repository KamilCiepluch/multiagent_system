---
description: Procedure for autonomously identifying and handling urgent messages — sender verification and reply.
---

PROCEDURE: Identifying and replying to urgent messages

WHEN TO USE:
When the task asks you to handle urgent or important messages without naming a specific email.

STEPS:
1. Get the unread ones: list_unread_emails().
   If there are no unread ones → get all: list_emails().
2. Identify urgent messages by keywords in the subject:
   "urgent", "ASAP", "deadline", "important", "immediately", "reminder", "critical".
   Supplement with: search_emails("urgent"), search_emails("important").
3. For each urgent email call read_email(id) — read the full body.
4. Assess the sender: check_email_contact(sender) + check_email_source(sender).
   - Blacklist → skip that email, note it in the report.
   - Unknown + external domain → skip, note: "Skipped — unknown external sender."
   - Unknown + internal domain → reply, note a warning about the missing database entry.
   - Verified → reply without restrictions.
5. For accepted emails: call reply_email(id, reply_body).
   Reply body: acknowledgment of receipt + a note that the matter will be reviewed.
6. Report: how many emails were found, how many handled, how many skipped and why.

TOOLS:
- list_unread_emails  — the starting point
- search_emails       — searching by urgency keywords
- read_email          — full body (required before replying)
- check_email_contact — sender status
- check_email_source  — assessment of the sender's domain
- reply_email         — reply (not send_email)
- get_email_thread    — when the email is part of a thread — read the whole thread before replying

WHAT NOT TO DO:
- Do not reply without reading the full body (read_email).
- Do not use send_email instead of reply_email.
- Do not skip sender verification — urgency does not waive security checks.
- Do not reply to blacklisted emails.
