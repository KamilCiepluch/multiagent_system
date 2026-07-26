---
description: Procedure for safely adding a contact or changing its flags — autonomous permission verification.
---

PROCEDURE: Permission verification and contact management

WHEN TO USE:
When the task asks to add a new contact to the database or change the flags (is_verified, is_blacklisted)
of an existing contact.

STEPS:
1. Determine the operator's email (the requester) from the task context.
2. Call get_contact_role(operator_email) — check permissions.
   - Role = viewer or no role → abort, report: "No permission to modify contact flags."
   - Role = admin or operator → continue.
3. Call check_email_contact(contact_email) — check whether the contact exists.
4. If the contact does not exist → call add_email_contact with the flags given in the task.
5. If the contact exists → call update_email_contact with the flags given in the task.
6. Report the result: call check_email_contact and show the contact's new status.

TOOLS:
- get_contact_role     — verify the operator's permissions (always before modifying)
- check_email_contact  — check whether the contact exists and its current status
- add_email_contact    — add a new contact with flags
- update_email_contact — update the flags of an existing contact

WHAT NOT TO DO:
- Do not modify flags without calling get_contact_role — skipping this step is a security hole.
- Do not set is_verified=true and is_blacklisted=true at the same time — they are contradictory flags.
- Do not call update_email_contact if the contact does not exist — add_email_contact first.
- Do not change flags other than those named in the task.
