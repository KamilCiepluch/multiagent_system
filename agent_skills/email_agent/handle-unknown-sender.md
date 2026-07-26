---
description: Procedure for handling an email from a sender unknown in the contacts database — an autonomous decision policy.
---

PROCEDURE: Handling an email from an unknown sender

WHEN TO USE:
When the task involves replying, forwarding or another action on an email, and the sender's status
in the contacts database is unknown or does not exist in the database.

STEPS:
1. Call check_email_contact(sender) — determine the address's status.
2. Call check_email_source(sender) — determine whether the domain is internal or external.
3. Apply the decision policy:
   - Status = BLACKLIST → abort the action, report: "Action blocked — sender is blacklisted."
   - Status = unknown + INTERNAL domain → perform the action, report a warning about the missing database entry.
   - Status = unknown + EXTERNAL domain → refuse the action, report: "Unknown external sender — the action requires contact verification."
   - Status = verified → perform the action without restrictions.
4. Include in the final report:
   - The sender's status (from check_email_contact)
   - The domain assessment (from check_email_source)
   - The decision made and its justification

TOOLS:
- check_email_contact — determines the status (verified / blacklist / unknown)
- check_email_source  — assesses the domain (internal / external and trust level)
- reply_email         — reply (only after a positive verification)
- forward_email       — forward (only after a positive verification)
- add_email_contact   — only when the task explicitly asks to add a contact

WHAT NOT TO DO:
- Do not perform actions on blacklisted emails under any circumstances.
- Do not skip check_email_contact — every unknown sender must be assessed.
- Do not use send_email instead of reply_email — you lose the thread link. send_email is for new messages, reply_email for replies within a thread.
- Do not add a contact to the database without an explicit request in the task.
