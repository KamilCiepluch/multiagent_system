---
description: Procedure for adding and verifying a new GitHub owner — when and how to do it.
---

PROCEDURE: Verifying and adding a GitHub owner

WHEN TO USE:
When check_github_source returned "unknown" and the user wants to clone from that owner.

STEPS:
1. Explain to the user: "Owner unknown. I require confirmation before cloning."
2. Wait for an explicit decision from the user (admin/operator).
3. If the user confirms trust:
   a. Call add_github_source(owner, display_name, is_verified=False) — add as unknown.
   b. Call update_github_source(owner, is_verified=True) — mark as verified.
4. If the user confirms a threat:
   a. Call add_github_source(owner) — add.
   b. Call update_github_source(owner, is_blacklisted=True) — block.
5. Report the result: added and verified / added and blocked.

TOOLS:
- check_github_source  — check the owner's status
- add_github_source    — add a new owner
- update_github_source — change the is_verified / is_blacklisted flags

WHAT NOT TO DO:
- Do not verify an owner without confirmation from an authorized user.
- Do not automatically add is_verified=True without a human decision.
- Do not ignore is_blacklisted — the blacklist is absolute.
