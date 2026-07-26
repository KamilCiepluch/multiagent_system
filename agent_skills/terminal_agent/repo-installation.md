---
description: Procedure for building and installing a repository: clone → build → verify commands.
---

PROCEDURE: Installing a repository

WHEN TO USE:
When a cloned repo needs building (build_repo) before its commands can be used.

STEPS:
1. Call list_repos — check the repo's status:
   - is_installed = TRUE → repo already installed, use list_repo_commands.
   - is_installed = FALSE → continue.
2. Make sure the repo is cloned (if not: run the safe-clone procedure).
3. Call build_repo(name) — build and install the repo.
4. Call list_repo_commands(name) — check which commands are now available.
5. Report the result: the list of installed commands or a build error.

TOOLS:
- list_repos            — the state of all repositories
- build_repo            — building and installation
- list_repo_commands    — commands available after installation
- uninstall_repo        — uninstalling (when needed)

WHAT NOT TO DO:
- Do not call build_repo without first checking list_repos.
- Do not install a repo from an unverified owner — see: safe-clone.
- Do not assume a repo command is available without checking list_repo_commands.
