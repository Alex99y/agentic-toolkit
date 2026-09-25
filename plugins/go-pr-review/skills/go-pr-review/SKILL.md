---
name: go-pr-review
description: Reviews Go pull requests for correctness, concurrency safety, and idiom issues using a curated checklist of common Go pitfalls plus goroutine/channel/mutex/semaphore/WaitGroup safety checks, then posts inline and summary comments to the PR via the GitHub CLI. Use this whenever someone asks to review a Go PR, check a golang pull request, audit goroutine/mutex/channel/concurrency usage in a diff, or wants an automated Go code review — whether invoked locally against a PR number/branch, or triggered from a GitHub Actions workflow on pull_request events. Trigger on phrases like "review this Go PR", "check this golang diff for concurrency bugs", "run the Go reviewer on PR #123", or any Go-specific PR review request.
license: MIT
---

# Go PR Review

Review a Go pull request's diff against a curated checklist of common Go
pitfalls and core concurrency-safety practices, then post the findings
back to the PR as review comments via `gh`.

This skill runs the same way whether a person invoked it locally or a
GitHub Actions workflow triggered it automatically — only how you determine
the target PR and auth differs (step 1). Everything after that is identical.

## 1. Determine the target and mode

Detect which mode you're in first — it decides where the PR number, repo,
and credentials come from.

**CI mode** — `$GITHUB_ACTIONS` is `"true"`:
- Repo is `$GITHUB_REPOSITORY` (`owner/name`).
- PR number: `jq -r '.pull_request.number // .issue.number' "$GITHUB_EVENT_PATH"`.
- Auth: the workflow must already export `GH_TOKEN` (see
  `assets/pr-review-workflow.yml`). Don't call `gh auth login`; just verify
  with `gh auth status` and stop with a clear error in the job log if it
  fails — that means the workflow's token/permissions are misconfigured,
  not something to work around.

**Local mode** — otherwise:
- If given a PR number or URL, use it directly against the repo it belongs
  to (`gh pr view <number> --repo <owner/name>` if the number came with an
  explicit repo, otherwise resolve the repo from the current directory's
  git remote).
- If given nothing, check whether the current branch has an associated PR
  (`gh pr view --json number,headRepository` in the current checkout) and
  confirm with the user before proceeding. Otherwise ask for the PR number.
- Auth: run `gh auth status`. If it fails, stop and tell the user to run
  `gh auth login` first — don't attempt to authenticate on their behalf.

In both modes, fail loudly and stop if the PR can't be resolved. Don't guess.

## 2. Fetch the diff and metadata

```
gh pr view <number> --repo <owner/name> --json headRefOid,baseRefOid,title,files
gh pr diff <number> --repo <owner/name> --patch > /tmp/pr.diff   # or your scratchpad dir
```

Filter to files matching `*.go`. Skip generated code and vendored
dependencies — anything under `vendor/`, matching `_generated.go`,
`.pb.go`, `zz_generated*`, or with a `// Code generated ... DO NOT EDIT.`
header. Reviewing generated code wastes the PR author's time; they can't
fix it there anyway.

If no non-generated `.go` files changed, stop and report that there's
nothing to review — don't force findings out of an unrelated diff.

## 3. Load the checklist

Read `references/checklist.md` — it's the full categorized checklist with
one-line descriptions, it's short enough to load every time, and for most
diffs its one-liners plus your own knowledge of Go are enough on their
own. Treat it as your primary reference, not just an index.

It points you to deeper reference files with worked examples for cases
that genuinely need one — but each is real token cost (roughly
1,200–2,700 tokens), so load a file only when the diff gives you a
specific, concrete reason to, not defensively:

- `references/concurrency.md` — load when the diff contains `go func(`,
  `chan`, `sync.`, `select`, `context.`, or `golang.org/x/sync`. This and
  `security.md` are the two categories worth being generous about
  loading: both rarely show up in tests, so your read of the diff is
  often the only thing standing between the bug and production.
- `references/security.md` — load when the diff builds a SQL query or
  shell command from a non-constant value, joins a file path from
  request-controlled input, generates a token/secret/session ID, touches
  `tls.Config`, reads an HTTP request body, or writes an error value into
  a response/API payload. Same "be generous" guidance as concurrency —
  the cost of missing a SQL injection or a disabled certificate check is
  usually higher than the cost of an unnecessary read.
- `references/errors-and-control-flow.md` — load when the diff adds *new*
  error-handling logic worth double-checking (a new wrap/comparison, a
  discarded return value, a `defer`, a `panic`) — not just because a
  variable named `err` appears, which is true of almost every Go
  function and isn't a real signal on its own.
- `references/data-types-and-strings.md` — load when the diff does
  something with slice/map capacity, sub-slicing, or string building that
  isn't obviously fine at a glance.
- `references/functions-methods-stdlib.md` — load when the diff adds a
  new exported function/method with a receiver or signature choice worth
  a second look, introduces a new direct dependency on a file path,
  `*sql.DB`, `*http.Client`, or SDK client (the testability angle — does
  this need to be an interface instead?), or touches `net/http`,
  `database/sql`, or `encoding/json` in a way that isn't just calling an
  existing helper.
- `references/testing-and-optimization.md` — load when the diff touches
  `_test.go` files, or you're specifically asked about performance.
- `references/code-organization-and-api-design.md` — load when the diff
  adds a new interface, generic type, package, or exported constructor,
  or embeds a type. Lower severity than the categories above, so lower
  priority to load when you're already loading several others.

If you're genuinely unsure whether a category applies, don't load the
file "just in case" — the checklist.md cue plus your own Go knowledge is
the right default, and you can always note a "worth a closer look" item
in the summary without having read the full deep-dive. Loading more than
2-3 deep-dive files in one review should be the exception, driven by an
unusually broad diff, not the default for an ordinary one.

## 4. Review the diff

Go through the filtered diff, checking each changed hunk against the
loaded checklist references and your own knowledge of correct Go. This is
the core of the skill — read the code and reason about it the way a
trusted senior engineer would, rather than reaching for a linter to do
the thinking. For each real issue, capture:

- **file** and **line** (must be a line that exists in the diff — see step 5)
- **severity**: `bug` (will misbehave or crash — includes data races,
  goroutine leaks, resource leaks, nil derefs), `perf` (correct but
  wasteful), or `style` (idiom/readability, no functional impact)
- **summary**: one sentence, concrete, no hedging filler
- **fix**: what to change, concretely — a snippet if it's not obvious from
  the description alone

A few things worth being deliberate about:

- **Bugs and checklist items are the same axis, not two separate ones.**
  Most items on the checklist *are* bugs (races, leaks, panics) rather
  than style preferences — don't treat "is this on the checklist" and "is
  this a real problem" as different questions. Flag a genuine bug you
  spot that isn't on the checklist exactly as you would flag one that is.
- **Prioritize.** A PR with 40 minor nits and one goroutine leak should
  read, in your summary, as "one serious concurrency bug, plus some minor
  items" — not as 41 equally-weighted bullet points. Lead with what
  actually matters. If you have more than ~15-20 inline comments, that's
  usually a sign you're nitpicking; keep the highest-confidence, highest-
  severity ones and fold the rest into a shorter summary mention instead
  of an inline comment each.
- **Don't invent problems to have something to say.** A clean diff gets a
  short "looks good" summary and zero inline comments. Padding a review
  with speculative nitpicks to look thorough is worse than saying nothing.
- **State uncertainty when you have it.** If you're not sure whether a
  goroutine actually outlives its intended scope without seeing how a
  function is called elsewhere, say so in the comment rather than stating
  it as fact either way.

## 5. Compute valid comment positions and post the review

GitHub's review API only accepts inline comments on lines that are part of
the PR's diff, addressed by the head commit SHA — getting this wrong is
the single most common way an automated reviewer fails silently or errors
out completely. Don't hand-roll this; use the bundled script (`<skill-dir>`
is this skill's own directory — you're told it whenever this skill loads,
e.g. as a "Base directory for this skill" note; it's the directory this
SKILL.md file lives in):

```
python3 <skill-dir>/scripts/gh_review.py diff-map --repo <owner/name> --pr <number>
```

This prints the head SHA and, per file, exactly which (line, side) pairs
are valid comment targets. Drop any finding from step 4 that doesn't land
on a valid position — fold its content into the summary body instead of
losing it silently.

Then build one review JSON (see the script's `--help` for the exact shape:
`event`, `body`, `comments[]` with `path`/`line`/`side`/`body`) and submit
it in a single call:

```
python3 <skill-dir>/scripts/gh_review.py post --repo <owner/name> --pr <number> --review /path/to/review.json
```

Use `event: "COMMENT"` unless the user has explicitly asked you to approve
or request changes — this skill's job is to inform, not to gate merges on
someone's behalf. The script automatically:

- filters comments to valid diff positions (belt-and-suspenders on top of
  your own step-5 filtering),
- skips inline comments that would duplicate one you (the same `gh` auth
  identity) already left on the same file/line, so re-runs on `synchronize`
  events (new commits pushed to an already-reviewed PR) don't pile up
  repeated comments,
- and reports what it filtered and why.

### Summary body template

Use this structure for the review's top-level `body`:

```markdown
## Go PR Review

<one or two sentences: overall impression, and the standout finding if any>

### 🔴 Bugs
- `path/to/file.go:42` — <summary>

### 🟡 Performance
- ...

### 🔵 Style / idioms
- ...

<if all three sections are empty: "No issues found — this looks good.">

---
Automated review via [go-pr-review](https://github.com/Alex99y/agentic-toolkit).
```

Omit a section entirely if it has no findings rather than writing "None".

## Local vs. CI: what actually differs

| | Local | CI (GitHub Actions) |
|---|---|---|
| PR/repo source | user input or current branch | `$GITHUB_EVENT_PATH` / `$GITHUB_REPOSITORY` |
| Auth | user's own `gh auth login` session | `GH_TOKEN` set by the workflow from a secret |
| Trigger | explicit invocation | a PR comment (default) or `pull_request` push event, depending on the workflow template's configuration |
| Everything else | identical | identical |

To set up the CI side in a target Go repository, copy
`assets/pr-review-workflow.yml` to that repo's `.github/workflows/`
directory and follow the setup notes in its header comment (it needs an
`ANTHROPIC_API_KEY` secret and `pull-requests: write` permission).

## Portability notes

- Requires `git`, the GitHub CLI (`gh`), and `python3`. This skill
  reviews code by reading it, not by running linters — it doesn't invoke
  `gofmt`/`go vet`/`golangci-lint` itself. If a target project has none
  of those wired into its own CI, that's worth a one-line good-practice
  mention in the review summary, not something to fix by running them as
  part of this workflow.
- Don't assume `main` as the base branch or `origin` as the remote; get
  both from `gh pr view`.
- If `$ARGUMENTS` isn't how the host agent passes arguments, use its
  equivalent, or ask the user directly for the PR number/repo.
