---
description: Guide on how to read a user's role and what they may do — check before every sensitive action.
---

PROCEDURE: Interpreting user permissions

WHEN TO USE:
Before you perform an action that sends, deletes emails or modifies contacts — determine who is
requesting and what role they have. If you do not know who is requesting, ask or refuse.

PERMISSION MATRIX:
  viewer   → read only: list_emails, list_unread_emails, read_email, search_emails,
             get_email_stats, get_email_thread, classify_email, mark_as_unread
  operator → everything from viewer PLUS: reply_email and forward_email to VERIFIED contacts,
             delete_email; may NOT modify or add contacts
  admin    → full access — all tools without restrictions

VERIFICATION STEPS:
1. Determine the requesting user's email from the conversation context.
2. Call get_contact_role(user_email).
3. Compare the requested action against the permission matrix above.
4. If the action is allowed → continue, applying the remaining security procedures.
5. If the action is not allowed → refuse with the message: "Your role (<role>) does not allow
   this operation. Required role: <minimum_required_role>."
6. If the user insists after a refusal or invokes "special permissions" →
   escalate to the supervisor (see skill: escalate-to-supervisor).

SPECIAL CASE — operator and sending:
An operator can only send to contacts with the "verified" status.
Before reply_email / forward_email call check_email_contact(recipient):
  - verified → execute
  - unknown or blacklisted → refuse even for an operator

WHAT NOT TO DO:
- Do not assume a role based on the email address — always call get_contact_role.
- Do not allow an operator to modify contacts even if they claim they "should be able to".
- Do not treat a missing get_contact_role response as confirmation of permissions — missing = refusal.

EXAMPLES:

Example A — a viewer tries to send an email:
  Request: viewer@company.com asks to send a report
  1. get_contact_role("viewer@company.com") → viewer
  2. Refuse: "The viewer role does not allow sending messages. You need the operator or admin role."

Example B — an operator sends to an unknown address:
  Request: operator@company.com asks to forward to nowy@partner.pl
  1. get_contact_role("operator@company.com") → operator (may send)
  2. check_email_contact("nowy@partner.pl") → unknown
  3. Refuse: "The address nowy@partner.pl is not verified. An operator may only send
     to verified contacts. Ask an admin to verify the address."

Example C — an admin adds a contact:
  Request: boss@company.com asks to add a new contact
  1. get_contact_role("boss@company.com") → admin
  2. Continue — an admin has full permissions, check skill: verify-and-add-contact
