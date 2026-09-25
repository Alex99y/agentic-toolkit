#!/usr/bin/env python3
"""Helper for the go-pr-review skill.

GitHub's PR review API only accepts inline comments on lines that are part
of the current diff, addressed against the PR's head commit SHA. Getting
this wrong is the most common way an automated reviewer fails silently or
errors out. This script does that bookkeeping so the caller doesn't have to
hand-roll unified-diff parsing and position math on every run, and so
reruns on new commits (a `synchronize` event re-triggering CI) don't pile
up duplicate comments.

Commands:

  diff-map --repo OWNER/REPO --pr NUMBER
      Prints JSON: {"head_sha": "...", "files": {"path": [{"line": N, "side": "RIGHT"}, ...]}}
      "side": "RIGHT" lines are additions/context in the new version of the
      file (removed-only lines are not included — see the module docstring
      in this file for why).

  post --repo OWNER/REPO --pr NUMBER --review path/to/review.json [--dry-run]
      review.json shape:
        {
          "event": "COMMENT" | "REQUEST_CHANGES" | "APPROVE",
          "body": "markdown summary",
          "comments": [
            {"path": "pkg/foo.go", "line": 42, "side": "RIGHT", "body": "..."}
          ]
        }
      Filters `comments` to positions actually in the current diff, drops
      any that would duplicate a comment this same gh identity already left
      on that exact file+line, and submits everything as a single review
      via `gh api .../pulls/{pr}/reviews`. Prints what was submitted and
      what was dropped (and why).
"""

import argparse
import json
import subprocess
import sys


def run_gh(args, input_text=None):
    result = subprocess.run(
        ["gh"] + args,
        input=input_text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    return result.stdout


def get_head_sha(repo, pr):
    out = run_gh(
        ["pr", "view", str(pr), "--repo", repo, "--json", "headRefOid"]
    )
    return json.loads(out)["headRefOid"]


def parse_diff(diff_text):
    """Parse a unified diff into {path: [{"line": N, "side": "RIGHT"}]}.

    Only lines that exist in the new (RIGHT) version of each file are
    included — additions and unchanged context lines. Pure deletions have
    no position in the new file and can't be commented on via `side:
    RIGHT`, which is what this skill always uses (see SKILL.md step 6).

    Pure function, no subprocess calls — kept separate from build_diff_map
    so it can be unit-tested directly against sample diff text.
    """
    files = {}
    current_path = None
    new_line = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            # New file section starting. Reset until the "+++" line confirms
            # the real path — metadata lines in between ("index ...",
            # "deleted file mode ...", "--- a/...", "rename from/to ...",
            # "Binary files ... differ") must never be mistaken for hunk
            # content belonging to the *previous* file.
            current_path = None
            new_line = None
            continue

        if raw_line.startswith("+++ "):
            path = raw_line[4:].strip()
            if path == "/dev/null":
                current_path = None
            else:
                current_path = path[2:] if path.startswith("b/") else path
                files.setdefault(current_path, [])
            new_line = None
            continue

        if raw_line.startswith("@@"):
            # @@ -oldStart,oldLines +newStart,newLines @@ ...
            try:
                plus_part = raw_line.split("+", 1)[1].split(" ", 1)[0]
                new_line = int(plus_part.split(",")[0])
            except (IndexError, ValueError):
                new_line = None
            continue

        if current_path is None or new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            files[current_path].append({"line": new_line, "side": "RIGHT"})
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            pass  # removed line: no position in the new file
        elif raw_line.startswith("\\"):
            pass  # "\ No newline at end of file"
        else:
            # context line: present in both versions, commentable on RIGHT
            files[current_path].append({"line": new_line, "side": "RIGHT"})
            new_line += 1

    return files


def build_diff_map(repo, pr):
    diff_text = run_gh(["pr", "diff", str(pr), "--repo", repo, "--patch"])
    return {"head_sha": get_head_sha(repo, pr), "files": parse_diff(diff_text)}


def cmd_diff_map(args):
    print(json.dumps(build_diff_map(args.repo, args.pr), indent=2))


def get_own_login():
    try:
        out = run_gh(["api", "user", "-q", ".login"])
        login = out.strip()
        if login:
            return login
    except RuntimeError:
        pass
    # Default GITHUB_TOKEN in Actions acts as the bot identity, not a user.
    return "github-actions[bot]"


def get_existing_comment_positions(repo, pr, login):
    out = run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr}/comments",
            "--paginate",
            "-q",
            ".[] | {path: .path, line: .line, side: .side, login: .user.login}",
        ]
    )
    positions = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("login") == login and row.get("line") is not None:
            positions.add((row["path"], row["line"], row.get("side") or "RIGHT"))
    return positions


def get_last_review_body(repo, pr, login):
    out = run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr}/reviews",
            "--paginate",
            "-q",
            ".[] | {body: .body, login: .user.login}",
        ]
    )
    last_body = None
    for line in out.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("login") == login:
            last_body = row.get("body")
    return last_body


def cmd_post(args):
    with open(args.review) as f:
        review = json.load(f)

    event = review.get("event", "COMMENT")
    body = review.get("body", "")
    requested_comments = review.get("comments", [])

    diff_map = build_diff_map(args.repo, args.pr)
    head_sha = diff_map["head_sha"]
    valid_positions = {
        (path, pos["line"], pos["side"])
        for path, positions in diff_map["files"].items()
        for pos in positions
    }

    login = get_own_login()
    existing = get_existing_comment_positions(args.repo, args.pr, login)

    kept, dropped_not_in_diff, dropped_duplicate = [], [], []
    for c in requested_comments:
        key = (c["path"], c["line"], c.get("side", "RIGHT"))
        if key not in valid_positions:
            dropped_not_in_diff.append(c)
        elif key in existing:
            dropped_duplicate.append(c)
        else:
            kept.append(
                {
                    "path": c["path"],
                    "line": c["line"],
                    "side": c.get("side", "RIGHT"),
                    "body": c["body"],
                }
            )

    if not kept and not requested_comments:
        last_body = get_last_review_body(args.repo, args.pr, login)
        if last_body is not None and last_body == body:
            print(
                "Nothing new since the last automated review from "
                f"{login} — skipped posting a duplicate."
            )
            return

    payload = {"commit_id": head_sha, "event": event, "body": body, "comments": kept}

    print(f"Posting as: {login}")
    print(f"Head SHA: {head_sha}")
    print(f"Comments to submit: {len(kept)}")
    if dropped_not_in_diff:
        print(
            f"Dropped {len(dropped_not_in_diff)} comment(s) not on a valid "
            "diff position (folded these into the summary instead if the "
            "caller did its job in SKILL.md step 5/6):"
        )
        for c in dropped_not_in_diff:
            print(f"  - {c['path']}:{c['line']}")
    if dropped_duplicate:
        print(
            f"Dropped {len(dropped_duplicate)} comment(s) already posted by "
            f"{login} on the same file/line (rerun de-duplication):"
        )
        for c in dropped_duplicate:
            print(f"  - {c['path']}:{c['line']}")

    if args.dry_run:
        print("\n--dry-run: not submitting. Payload:")
        print(json.dumps(payload, indent=2))
        return

    out = run_gh(
        [
            "api",
            f"repos/{args.repo}/pulls/{args.pr}/reviews",
            "-X",
            "POST",
            "--input",
            "-",
        ],
        input_text=json.dumps(payload),
    )
    result = json.loads(out)
    print(f"\nReview posted: {result.get('html_url', '(no URL in response)')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_map = sub.add_parser("diff-map", help="Print valid inline-comment positions")
    p_map.add_argument("--repo", required=True)
    p_map.add_argument("--pr", required=True)
    p_map.set_defaults(func=cmd_diff_map)

    p_post = sub.add_parser("post", help="Post a filtered, de-duplicated review")
    p_post.add_argument("--repo", required=True)
    p_post.add_argument("--pr", required=True)
    p_post.add_argument("--review", required=True, help="Path to review JSON file")
    p_post.add_argument(
        "--dry-run", action="store_true", help="Print the payload, don't submit it"
    )
    p_post.set_defaults(func=cmd_post)

    args = parser.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
