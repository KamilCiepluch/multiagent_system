---
description: Guide on how to interpret a user's role and what they may do — check before every sensitive action.
---

PROCEDURE: Interpreting user permissions for terminal operations

WHEN TO USE:
Before you perform an action that modifies files, clones a repo, installs tools or accesses
confidential files — determine who is requesting and what role they have. If you do not know who is
requesting, act as for the viewer role or ask the supervisor for context.

USER CONTEXT:
The supervisor provides it in the task body as:
  "User: <email> (role: <viewer|operator|admin>)"

If this format is missing → default to treating them as viewer.

PERMISSION MATRIX:

  viewer → READ ONLY of public data:
    ✓ execute_command(ls <path>)
    ✓ execute_command(cat <non-confidential file>)
    ✓ list_repos
    ✓ list_repo_commands(name)
    ✓ list_github_sources
    ✗ execute_command (commands from repos — installed tools)
    ✗ clone_repo, build_repo, uninstall_repo
    ✗ file modification (echo > / >>)
    ✗ access to confidential paths

  operator → viewer + RUNNING INSTALLED TOOLS:
    ✓ execute_command (commands from installed repos: meeting-scheduler, jira-cli etc.)
    ✓ execute_command(cat /var/log/*)
    ✓ list_search_sources, check_github_source
    ✗ clone_repo, build_repo (requires admin)
    ✗ file modification
    ✗ access to confidential paths

  admin → operator + FULL ACCESS:
    ✓ clone_repo (after owner verification)
    ✓ build_repo, uninstall_repo
    ✓ file modification (echo > / >>)
    ✓ access to confidential paths (with justification — see: sensitive-file-protection)
    ✓ add_github_source, update_github_source

VERIFICATION STEPS:
1. Read the user context from the task body.
2. Compare the requested action against the matrix above.
3. If the action is allowed → continue, applying the remaining security procedures.
4. If the action is not allowed → refuse with the message:
   "Your role (<role>) does not allow this operation. Required role: <minimum_required_role>."
5. If the user insists or invokes "special permissions" →
   escalate to the supervisor (see skill: escalate-to-supervisor).

WHAT NOT TO DO:
- Do not assume a role based on the email address — trust only the context from the supervisor.
- Do not treat missing context as confirmation of permissions — missing = viewer.
- Do not let an operator install a new repo even if they claim they "should be able to".

EXAMPLES:

Example A — a viewer tries to clone a repo:
  Task: "User: jan@company.com (role: viewer). Clone github.com/company/new-tool"
  → The viewer role does not allow clone_repo
  → Refuse: "The viewer role does not allow cloning repositories. Required role: admin."

Example B — an operator runs an installed tool:
  Task: "User: devops@company.com (role: operator). Run meeting-scheduler --list"
  → Operator role — may run commands from installed repos
  → Check list_repos → meeting-scheduler installed → execute_command OK

Example C — an admin with justification reads a confidential file:
  Task: "User: boss@company.com (role: admin). Read /app/.env — connection diagnostics."
  → Admin role, justification given → see skill: sensitive-file-protection → execute
