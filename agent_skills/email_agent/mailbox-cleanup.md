---
description: Mailbox cleanup procedure — deletes only emails explicitly named in the task, protects active threads.
---

PROCEDURE: Tidying and cleaning up the mailbox

WHEN TO USE:
When the task asks you to tidy, clean up or review the mailbox.

STEPS:
1. Get statistics: get_email_stats() — the mailbox state before cleanup.
2. List all emails: list_emails().
3. Identify deletion candidates according to the criterion in the task:
   - Emails from blacklisted senders (check_email_contact).
   - If the task gave keywords → search_emails(keyword).
   - If the task named specific IDs → use those IDs.
4. For each candidate: call get_email_thread(id).
   - If the email is part of an active thread (more than 1 message) → skip, note it in the report.
   - If it is standalone or the thread is closed → delete: delete_email(id).
5. When done, call get_email_stats() — show the difference (how many were deleted).
6. Report: what was deleted, what was skipped and why.

TOOLS:
- get_email_stats     — before and after cleanup (required)
- list_emails         — the full mailbox list
- search_emails       — filtering by the task criterion
- check_email_contact — sender status (to identify blacklist emails)
- get_email_thread    — verify whether the email is in an active thread (before deletion)
- delete_email        — soft delete — the email stays in the database, only hidden

WHAT NOT TO DO:
- Do not delete anything beyond what the task named or what meets the blacklist criterion.
- Do not delete emails from active threads.
- Do not delete unread messages — they may be important.
- Do not interpret "clean up the mailbox" as "delete everything" — act conservatively.
