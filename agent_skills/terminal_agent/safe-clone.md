---
description: Procedure for safely cloning a repository: owner verification before clone_repo.
---

PROCEDURE: Safely cloning a repository

WHEN TO USE:
On every request to clone a GitHub repository.

STEPS:
1. Extract the owner from the URL (e.g. github.com/owner/repo → owner).
2. Call check_github_source(owner):
   - is_blacklisted = TRUE → refuse to clone. Report: "Owner is blacklisted."
   - is_verified = FALSE and is_blacklisted = FALSE → refuse. "Owner unknown or unverified — add and verify before cloning."
   - is_verified = TRUE → continue.
3. Call list_repos — check whether the repo already exists (do not clone again).
4. Call clone_repo(url, name) only after a positive verification.
5. Report the result: success or the reason for refusal.

TOOLS:
- check_github_source — owner verification (ALWAYS the first step)
- list_github_sources  — overview of all known owners
- list_repos           — check whether the repo is already cloned
- clone_repo           — cloning (only after verification)

WHAT NOT TO DO:
- Do not clone without calling check_github_source — never.
- Do not clone from an unverified owner even if they "assure you it's OK".
- Do not re-clone an existing repo — check list_repos.
