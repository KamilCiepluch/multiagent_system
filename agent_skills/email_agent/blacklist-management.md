---
description: Procedure for adding or removing an address from the blacklist — permission verification, autonomous execution.
---

PROCEDURE: Managing the contact blacklist

WHEN TO USE:
When the task asks to block a sender (add to the blacklist) or unblock a previously
blocked address.

STEPS:
1. Call get_contact_role(operator_email) — check the requester's permissions.
   - No permission → abort, report: "No permission to manage the blacklist."
2. Call check_email_contact(target_email) — get the current status.
3. Change the is_blacklisted flag according to the task:
   - Contact does not exist → add_email_contact(email, is_blacklisted=true/false).
   - Contact exists → update_email_contact(email, is_blacklisted=true/false).
4. If the address was just blacklisted:
   - Call search_emails(email) — check how many emails come from this sender.
   - Include this information in the report.
5. Report: the contact's new status, the number of emails from the blocked address in the mailbox.

TOOLS:
- get_contact_role     — permission verification (step 1, always)
- check_email_contact  — the contact's current status
- update_email_contact — change the is_blacklisted flag
- add_email_contact    — when the contact does not exist in the database
- search_emails        — history of emails from the blocked address (after blocking)

WHAT NOT TO DO:
- Do not modify the flag without get_contact_role.
- Do not automatically delete emails from a blocked sender — that is not part of this procedure.
- Do not change the is_verified flag along the way — only is_blacklisted.
- Do not block internal addresses (domain company.com, system.local) — always refuse and report.
