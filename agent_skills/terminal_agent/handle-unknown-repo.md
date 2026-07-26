---
description: What to do when the user asks to run a command from an uninstalled or unknown repo.
---

PROCEDURE: Handling a request for an unknown repository

WHEN TO USE:
When the user wants to run a command but the needed repo is not installed or is unknown.

STEPS:
1. Call list_repos — check all known repositories.
2. Check list_repo_commands for installed repos — the needed command may already exist.
3. If the repo does not exist:
   a. Inform the user: "Repo unknown. I need the URL and the owner."
   b. Wait for the data (URL).
   c. Run the safe-clone procedure — owner verification.
   d. After cloning: run the repo-installation procedure.
4. Report the final state: command available or a refusal with a reason.

TOOLS:
- list_repos           — the state of repositories
- list_repo_commands   — commands from installed repos
- (see procedures: safe-clone, repo-installation)

WHAT NOT TO DO:
- Do not try to run a command without checking whether the repo is installed.
- Do not clone automatically without owner verification.
- Do not suggest skipping verification even for "trusted" repository names.
