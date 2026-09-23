---
name: resolve-github-issue
description: Resolves a GitHub issue end-to-end — plans the fix, implements it in an isolated git worktree, verifies it, and opens a PR. Use when the user asks to work on, fix, or implement a GitHub issue.
license: MIT
---

# Resolve GitHub Issue

Resolve the issue: $ARGUMENTS

## 1. Check GitHub authentication

Run:

    gh auth status

If not authenticated, stop and tell the user to run `gh auth login` first.

## 2. Read the issue

- If $ARGUMENTS contains an issue number or URL, use it directly.
- If not, ask the user which issue to work on.
- Always use the current repository, including when the issue is provided as a URL.
- Fetch it with `gh issue view <number>` to get the title, body, labels, and comments.
- If the issue doesn't exist or can't be fetched, stop and report the error. Do not proceed.

## 3. Plan the approach

- Base the plan on the issue description and any recommendations it contains.
- If the issue is a bug report, first confirm the bug is real (reproduce it or find clear evidence in the code) before planning the fix.
- Write a short plan: what will change, which files are likely affected, and how it will be verified.
- Present the plan to the user and wait for explicit approval before continuing. Do not start implementing without it.

## 4. Create an isolated worktree and branch

- Determine the repository's default branch and remote instead of assuming `main` and `origin`.
- Check whether `.worktrees/` is ignored. If it is not, use `.git/info/exclude` for the local worktree directory rather than changing the project files.
- Create the worktree:

    git fetch <remote>
    git worktree add .worktrees/<branch-name> -b <branch-name> <remote>/<default-branch>

- Branch name format: `{tag}/{issue-number}/{slug}`
  - `tag`: derived from the issue's label or nature (`feat`, `fix`, `chore`, `test`, etc.)
  - `issue-number`: the issue number from step 2
  - `slug`: short kebab-case description generated from the issue title (e.g. `fix/456/login-timeout`)
- Do all remaining work inside this worktree, not in the main checkout.

## 5. Implement the plan

- Follow the approved plan.
- Follow the project's existing conventions and rules (check `AGENTS.md` / `CLAUDE.md` and nearby code for patterns).
- Keep changes scoped to the issue.

## 6. Verify

Inspect the project's documentation and configuration to identify the applicable test, build, and lint commands. Run the applicable checks in that order. Do not continue if any check fails — fix the root cause first. If a check does not exist, report that it was skipped.

## 7. Optional: agent review

If a code-review skill or subagent is available in this project, run it now against the diff. Address any correctness issues it raises, then repeat step 6.

## 8. Rebase on the base branch

    git fetch <remote>
    git rebase <remote>/<default-branch>

Resolve any conflicts. If the rebase changes any files, repeat step 6 before continuing.

## 9. Commit and publish approval

- Write a descriptive commit message (what changed and why).
- Before pushing, show the user the branch name, commit summary, and verification results. Ask for explicit approval to push the branch and open a pull request.
- After approval, push:

      git push -u <remote> <branch-name>

## 10. Open the PR

    gh pr create --title "<tag>: <short summary>" --body "Closes #<issue-number>

    ## What changed
    ...

    ## How it was tested
    ...

    ## Notes / risks
    ..." --base <default-branch>

## 11. Report

Summarize for the user: branch name, PR link, what was verified, and anything skipped or flagged for follow-up.

## Portability notes

- This workflow requires shell access, Git, and the GitHub CLI (`gh`). If any are unavailable, stop and report what is missing.
- `$ARGUMENTS` means the arguments supplied to the skill. If the host agent uses different argument syntax, use its equivalent. If arguments are unavailable, ask the user for the issue number or URL.
- Do not assume a particular default branch, remote name, repository root, or project tooling.
- Follow the host agent's approval and tool-permission rules for commands that modify files, push branches, or create pull requests.