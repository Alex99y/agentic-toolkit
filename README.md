# Agentic Toolkit

A personal collection of Claude Code plugins, skills, and rules for generic AI agent workflows.

## Requirements

- [Claude Code](https://claude.com/claude-code) — required for everything in this repo.

Each plugin below may need additional tools; see its own section.

## Installation

This repo is a Claude Code plugin marketplace. Add it once, then install whichever plugin(s) you want:

```
/plugin marketplace add Alex99y/agentic-toolkit
/plugin install <plugin-name>@agentic-toolkit
```

## Plugins

### resolve-github-issue

Resolves a GitHub issue end-to-end: plans the fix, implements it in an isolated git worktree, verifies it, and opens a PR. Stops for your approval before implementing and before pushing/opening the PR.

**Install:**
```
/plugin install resolve-github-issue@agentic-toolkit
```

**Requires:**
- [GitHub CLI (`gh`)](https://cli.github.com), authenticated via `gh auth login`
- In the repo where you run it, add `.worktrees` to `.gitignore` first — that's where it creates its isolated worktrees.

**Usage:** ask Claude Code to work on, fix, or implement a GitHub issue, e.g. "resolve issue #123" or "fix the bug described in #456".

### go-pr-review

Reviews Go pull requests against a curated checklist of common Go pitfalls, posting inline and summary comments via `gh`. Concurrency safety (goroutines, channels, mutexes, semaphores) and security (injection, path traversal, weak randomness, TLS misconfiguration, hardcoded secrets) get the most weight, since both rarely fail a test suite and are often the most severe things a reviewer catches. It reviews by reading the diff and reasoning about it — it doesn't run `gofmt`/`go vet`/`golangci-lint` itself; a project missing those in its own CI just gets a one-line good-practice mention. The checklist is informed by [100 Go Mistakes and How to Avoid Them](https://100go.co/) by Teiva Harsanyi.

Includes a `go-pr-reviewer` agent for local use, and a GitHub Actions workflow template that reviews on demand via a PR comment (with an automatic-on-push option available too).

**Install:**
```
/plugin install go-pr-review@agentic-toolkit
```

**Requires:**
- [GitHub CLI (`gh`)](https://cli.github.com), authenticated via `gh auth login` (local use), or a repository's built-in `GITHUB_TOKEN` (CI use)
- `git` and `python3`
- **CI use only:** an [`ANTHROPIC_API_KEY`](https://console.anthropic.com) set as a repository secret. The workflow runs the Claude Code CLI headlessly, which needs its own API key rather than your local Claude Code login — local use needs no separate key.

**Model recommendation:** the bundled agent defaults to standard Sonnet. We benchmarked it against a plain "no skill" baseline and found comparable bug-finding accuracy — this skill's value is in consistent, well-formatted output and correct GitHub-posting mechanics, not in deeper multi-step reasoning, so a higher reasoning-effort tier is unlikely to find proportionally more real issues. Running it at high effort as the default would cost noticeably more per review for an unproven accuracy gain; reserve that for unusually large or high-stakes PRs where you deliberately want extra scrutiny, not as the everyday setting.

**Usage — local:** ask Claude Code to review a Go PR, e.g. "review PR #42" or "use the go-pr-reviewer agent to check this golang diff for concurrency bugs".

**Usage — CI:** copy `plugins/go-pr-review/skills/go-pr-review/assets/pr-review-workflow.yml` into the *target* Go repository's `.github/workflows/`, add the `ANTHROPIC_API_KEY` repository secret mentioned above, and ensure Actions has `pull-requests: write` permission. See the comments at the top of that file for full setup steps.

As shipped, it's triggered on demand: comment `/review-go-mistakes` on a PR to have it reviewed (only from commenters with write access to the repo, since the trigger runs with the repository's secrets). The automatic "review every push touching `.go` files" trigger is included but commented out — uncomment the `pull_request:` block in the workflow if you'd rather it run on every push than wait for the comment.
