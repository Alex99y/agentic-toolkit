# Agentic Toolkit

A personal collection of Claude Code plugins, skills, and rules for generic AI agent workflows.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- [GitHub CLI (`gh`)](https://cli.github.com), authenticated via `gh auth login` — required by plugins that interact with GitHub, such as `resolve-github-issue`

## Installation

This repo is a Claude Code plugin marketplace. Add it, then install the plugin you want:

```
/plugin marketplace add Alex99y/agentic-toolkit
/plugin install resolve-github-issue@agentic-toolkit
```

## Plugins

- **resolve-github-issue** — Resolves a GitHub issue end-to-end: plans the fix, implements it in an isolated git worktree, verifies it, and opens a PR. In the repo where you run it, add `.worktrees` to your `.gitignore` first, since that's where it creates its worktrees.
