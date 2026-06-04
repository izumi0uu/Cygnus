#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SUBJECT_MAX = 72
PR_TITLE_MAX = 88
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_SCOPE_RISK = {"narrow", "moderate", "broad"}
ALLOWED_CHANGE_TYPES = {
    "feat",
    "fix",
    "doc",
    "docs",
    "chore",
    "refactor",
    "test",
    "ci",
    "infra",
    "perf",
    "build",
    "style",
    "research",
    "revert",
}
REQUIRED_TRAILERS = ("Confidence", "Scope-risk", "Tested")
OPTIONAL_TRAILERS = ("Constraint", "Rejected", "Directive", "Not-tested")
TRAILER_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z-]*):\s+(?P<value>.+)$")
SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
CONVENTIONAL_SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)\((?P<scope>[a-z0-9._/-]+)\): (?P<summary>.+)$"
)
BRANCH_RE = re.compile(
    r"^(feat|fix|doc|docs|chore|refactor|test|ci|infra|perf|build|style|research|revert)/[a-z0-9._-]+$"
)
ISSUE_REF_RE = re.compile(r"#\d+")


def _strip_comments(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text)


def _nonempty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _parse_sections(body: str) -> dict[str, str]:
    body = _strip_comments(body or "")
    matches = list(SECTION_RE.finditer(body))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        sections[match.group("name").strip()] = body[start:end].strip()
    return sections


def validate_commit_text(text: str, label: str) -> list[str]:
    errors: list[str] = []
    normalized = text.replace("\r\n", "\n").strip("\n")
    if not normalized.strip():
        return [f"{label}: commit message is empty"]

    lines = normalized.split("\n")
    subject = lines[0].strip()
    lower_subject = subject.lower()

    if not subject:
        errors.append(f"{label}: subject line is empty")
    if len(subject) > SUBJECT_MAX:
        errors.append(
            f"{label}: subject line is {len(subject)} chars; limit is {SUBJECT_MAX}"
        )
    if subject.endswith("."):
        errors.append(f"{label}: subject line must not end with a period")
    if len(lines) > 1 and lines[1].strip():
        errors.append(f"{label}: add a blank line between subject and body")

    if subject.startswith("Merge "):
        return errors

    errors.extend(_validate_conventional_subject(subject, label))

    trailers: dict[str, list[str]] = {}
    trailer_block: list[str] = []
    seen_trailer = False
    for raw_line in reversed(lines[1:]):
        line = raw_line.strip()
        if not line:
            if seen_trailer:
                break
            continue
        match = TRAILER_RE.match(line)
        if match:
            seen_trailer = True
            trailer_block.append(line)
            continue
        if seen_trailer:
            break

    for line in reversed(trailer_block):
        match = TRAILER_RE.match(line)
        if not match:
            continue
        trailers.setdefault(match.group("key"), []).append(match.group("value").strip())

    for key in REQUIRED_TRAILERS:
        values = trailers.get(key, [])
        if not values:
            errors.append(f"{label}: missing required trailer `{key}: ...`")
        elif len(values) > 1:
            errors.append(f"{label}: trailer `{key}` appears multiple times")

    confidence = trailers.get("Confidence", [""])[0].lower()
    if confidence and confidence not in ALLOWED_CONFIDENCE:
        errors.append(
            f"{label}: Confidence must be one of {sorted(ALLOWED_CONFIDENCE)}"
        )

    scope_risk = trailers.get("Scope-risk", [""])[0].lower()
    if scope_risk and scope_risk not in ALLOWED_SCOPE_RISK:
        errors.append(
            f"{label}: Scope-risk must be one of {sorted(ALLOWED_SCOPE_RISK)}"
        )

    tested = trailers.get("Tested", [""])[0]
    if "Tested" in trailers and not tested.strip():
        errors.append(f"{label}: Tested trailer must have a value")

    lore_keys = set(REQUIRED_TRAILERS) | set(OPTIONAL_TRAILERS)
    unknown_lore_like = [
        key for key in trailers if key[0].isupper() and key not in lore_keys
    ]
    if unknown_lore_like:
        errors.append(
            f"{label}: unknown trailer(s) {', '.join(sorted(unknown_lore_like))}"
        )

    if lower_subject.startswith(("wip", "tmp", "fixup!", "squash!")):
        errors.append(f"{label}: subject line contains a temporary commit marker")

    return errors


def validate_commit_file(path: str) -> int:
    text = Path(path).read_text(encoding="utf-8")
    errors = validate_commit_text(text, path)
    return _report(errors)


def validate_commit_range(base: str, head: str) -> int:
    merge_base = _git("merge-base", base, head).strip()
    shas = [sha for sha in _git("rev-list", "--reverse", f"{merge_base}..{head}").splitlines() if sha]
    if not shas:
        return _report(["commit-range: no commits found in range"])

    errors: list[str] = []
    for sha in shas:
        subject = _git("show", "-s", "--format=%s", sha).strip()
        body = _git("show", "-s", "--format=%B", sha)
        errors.extend(validate_commit_text(body, f"{sha[:12]} `{subject}`"))
    return _report(errors)


def validate_pr() -> int:
    title = (os.environ.get("PR_TITLE") or "").strip()
    body = os.environ.get("PR_BODY") or ""
    branch = (os.environ.get("PR_BRANCH") or "").strip()

    errors: list[str] = []

    if not title:
        errors.append("pr-title: title is empty")
    if len(title) > PR_TITLE_MAX:
        errors.append(f"pr-title: title is {len(title)} chars; limit is {PR_TITLE_MAX}")
    if title.endswith("."):
        errors.append("pr-title: title must not end with a period")
    if title.lower().startswith(("wip", "draft", "[wip]", "[draft]")):
        errors.append("pr-title: remove WIP/Draft markers from the title")
    errors.extend(_validate_conventional_subject(title, "pr-title"))

    if branch and not BRANCH_RE.match(branch):
        errors.append(
            "pr-branch: branch must match "
            "`<kind>/<short-slug>` where kind is one of "
            "feat|feature|fix|docs|chore|refactor|test|ci|infra|research"
        )

    sections = _parse_sections(body)
    required_sections = ["Summary", "Problem", "Solution", "Validation", "Risks", "Related"]
    for name in required_sections:
        if name not in sections:
            errors.append(f"pr-body: missing `## {name}` section")
            continue
        if not _nonempty_lines(sections[name]):
            errors.append(f"pr-body: `## {name}` is empty")

    unchecked_boxes = re.findall(r"^- \[ \] .+$", body, flags=re.MULTILINE)
    if unchecked_boxes:
        errors.append(
            "pr-body: all checklist items must be checked or replaced with `N/A: <reason>`"
        )

    validation = sections.get("Validation", "")
    if validation:
        checked = re.findall(r"^- \[[xX]\] .+$", validation, flags=re.MULTILINE)
        if not checked and "N/A:" not in validation:
            errors.append(
                "pr-body: `## Validation` must include checked items or explicit `N/A:` reasons"
            )

    related = sections.get("Related", "")
    if related and "N/A" not in related and not ISSUE_REF_RE.search(related):
        errors.append("pr-body: `## Related` should include an issue reference or `N/A`")

    return _report(errors)


def _validate_conventional_subject(subject: str, label: str) -> list[str]:
    errors: list[str] = []
    match = CONVENTIONAL_SUBJECT_RE.match(subject)
    if not match:
        allowed = ", ".join(sorted(ALLOWED_CHANGE_TYPES))
        errors.append(
            f"{label}: subject must match `type(scope): summary` "
            f"using one of [{allowed}]"
        )
        return errors

    change_type = match.group("type")
    summary = match.group("summary").strip()
    if change_type not in ALLOWED_CHANGE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CHANGE_TYPES))
        errors.append(
            f"{label}: type `{change_type}` is not allowed; use one of [{allowed}]"
        )
    if not summary:
        errors.append(f"{label}: summary after `type(scope):` must not be empty")
    if summary and summary[0].isupper():
        errors.append(f"{label}: summary should start lowercase for consistency")
    return errors


def _report(errors: list[str]) -> int:
    if not errors:
        print("repo-guard: OK")
        return 0

    print("repo-guard: validation failed", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repository PR + commit guardrails")
    sub = parser.add_subparsers(dest="command", required=True)

    commit_file = sub.add_parser("validate-commit-file", help="Validate a commit message file")
    commit_file.add_argument("path")

    commit_range = sub.add_parser("validate-commit-range", help="Validate commits between base and head")
    commit_range.add_argument("base")
    commit_range.add_argument("head")

    sub.add_parser("validate-pr", help="Validate PR title/body/branch from environment")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "validate-commit-file":
        return validate_commit_file(args.path)
    if args.command == "validate-commit-range":
        return validate_commit_range(args.base, args.head)
    if args.command == "validate-pr":
        return validate_pr()
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
