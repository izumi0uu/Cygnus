#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_REF = "origin/main"
UPSTREAM_REMOTE_PATTERNS = (
    re.compile(r"github\.com[:/][^\"'\s]*/arkon(?:\.git)?$"),
    re.compile(r"nduckmink/arkon(?:\.git)?$"),
)


def default_search_roots() -> list[Path]:
    candidates = [
        REPO_ROOT.parent,
        REPO_ROOT.parent / "projects",
        Path.home() / "projects",
    ]
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def iter_git_repos(search_root: Path, *, max_depth: int = 4):
    root_depth = len(search_root.parts)
    for current_root, dirnames, filenames in os.walk(search_root):
        current_path = Path(current_root)
        depth = len(current_path.parts) - root_depth
        if depth > max_depth:
            dirnames[:] = []
            continue

        if ".git" in dirnames:
            yield current_path
            dirnames[:] = []
            continue

        if ".git" in filenames:
            yield current_path
            dirnames[:] = []


def resolve_git_dir(repo_path: Path) -> Path | None:
    marker = repo_path / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if text.startswith(prefix):
            target = text[len(prefix) :].strip()
            return (repo_path / target).resolve()
    return None


def read_origin_url(repo_path: Path) -> str | None:
    git_dir = resolve_git_dir(repo_path)
    if git_dir is None:
        return None

    config_path = git_dir / "config"
    if not config_path.exists():
        return None

    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except configparser.Error:
        return None

    section = 'remote "origin"'
    if not parser.has_section(section):
        return None
    return parser.get(section, "url", fallback=None)


def is_upstream_origin(url: str | None) -> bool:
    if not url:
        return False
    return any(pattern.search(url) for pattern in UPSTREAM_REMOTE_PATTERNS)


def run_git(repo_path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_path), *args], text=True
    ).strip()


def safe_git(repo_path: Path, *args: str) -> tuple[str | None, str | None]:
    try:
        return run_git(repo_path, *args), None
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return None, str(exc)


def collect_ahead_commits(
    repo_path: Path, base_ref: str
) -> tuple[list[dict[str, str]], str | None]:
    raw, error = safe_git(
        repo_path, "log", "--reverse", "--format=%H%x09%s", f"{base_ref}..HEAD"
    )
    if error is not None:
        return [], error
    if not raw:
        return [], None

    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        sha, subject = line.split("\t", 1)
        commits.append({"sha": sha, "subject": subject})
    return commits, None


def collect_status_lines(repo_path: Path) -> tuple[list[str], str | None]:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(repo_path), "status", "--porcelain=v1"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return [], str(exc)
    return [line for line in raw.splitlines() if line], None


class CheckoutRecord(TypedDict):
    path: str
    repo_name: str
    contains_arkon_name: bool
    origin_url: str | None
    is_upstream_origin: bool
    branch: str | None
    head_commit: str | None
    base_ref: str
    ahead_commit_count: int
    ahead_commits: list[dict[str, str]]
    status_lines: list[str]
    untracked_files: list[str]
    has_tracked_dirty: bool
    requires_preservation: bool
    preservation_reasons: list[str]
    physical_delete_blocked: bool
    inspection_errors: list[str]


class CheckoutAudit(TypedDict):
    audit_name: str
    base_ref: str
    search_roots: list[str]
    checkout_count: int
    requires_preservation_count: int
    checkouts: list[CheckoutRecord]


def classify_repo(
    repo_path: Path, *, base_ref: str = DEFAULT_BASE_REF
) -> CheckoutRecord | None:
    origin_url = read_origin_url(repo_path)
    contains_arkon_name = "arkon" in repo_path.name.lower()
    upstream = is_upstream_origin(origin_url)

    if not contains_arkon_name and not upstream:
        return None

    branch, branch_error = safe_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    head_commit, head_error = safe_git(repo_path, "rev-parse", "HEAD")
    status_lines, status_error = collect_status_lines(repo_path)
    ahead_commits, ahead_error = collect_ahead_commits(repo_path, base_ref)

    untracked_files = [line[3:] for line in status_lines if line.startswith("?? ")]
    has_tracked_dirty = any(not line.startswith("?? ") for line in status_lines)
    preservation_reasons: list[str] = []
    if ahead_commits:
        preservation_reasons.append(f"{len(ahead_commits)} ahead commit(s)")
    if has_tracked_dirty:
        preservation_reasons.append("dirty tracked worktree changes")
    if untracked_files:
        preservation_reasons.append(f"{len(untracked_files)} untracked file(s)")

    inspection_errors = [
        error
        for error in (branch_error, head_error, status_error, ahead_error)
        if error is not None
    ]

    return {
        "path": str(repo_path),
        "repo_name": repo_path.name,
        "contains_arkon_name": contains_arkon_name,
        "origin_url": origin_url,
        "is_upstream_origin": upstream,
        "branch": branch,
        "head_commit": head_commit,
        "base_ref": base_ref,
        "ahead_commit_count": len(ahead_commits),
        "ahead_commits": ahead_commits,
        "status_lines": status_lines,
        "untracked_files": untracked_files,
        "has_tracked_dirty": has_tracked_dirty,
        "requires_preservation": bool(preservation_reasons),
        "preservation_reasons": preservation_reasons,
        "physical_delete_blocked": True,
        "inspection_errors": inspection_errors,
    }


def audit_external_checkouts(
    search_roots: list[Path] | None = None,
    *,
    max_depth: int = 4,
    base_ref: str = DEFAULT_BASE_REF,
) -> CheckoutAudit:
    roots = search_roots or default_search_roots()
    seen_paths: set[Path] = set()
    checkouts: list[CheckoutRecord] = []

    for root in roots:
        for repo_path in iter_git_repos(root, max_depth=max_depth):
            resolved = repo_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            classified = classify_repo(resolved, base_ref=base_ref)
            if classified is not None:
                checkouts.append(classified)

    checkouts.sort(key=lambda item: str(item["path"]))
    return {
        "audit_name": "external_checkout_audit",
        "base_ref": base_ref,
        "search_roots": [str(path) for path in roots],
        "checkout_count": len(checkouts),
        "requires_preservation_count": sum(
            1 for item in checkouts if item["requires_preservation"]
        ),
        "checkouts": checkouts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit local filesystem roots for standalone Arkon checkouts outside the current Cygnus repo."
    )
    parser.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Additional root to search. Can be passed multiple times.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="Maximum directory depth to search under each root.",
    )
    parser.add_argument(
        "--base-ref",
        default=DEFAULT_BASE_REF,
        help="Base ref used to detect ahead commits. Default: origin/main",
    )
    parser.add_argument(
        "--fail-if-found",
        action="store_true",
        help="Return exit code 1 when any external checkout is found.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output.",
    )
    args = parser.parse_args()

    explicit_roots = [Path(value).expanduser().resolve() for value in args.search_root]
    search_roots = explicit_roots or default_search_roots()
    payload = audit_external_checkouts(
        search_roots, max_depth=args.max_depth, base_ref=args.base_ref
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("[external-checkout-audit]")
        print(f"- search roots: {', '.join(payload['search_roots'])}")
        print(f"- external checkout count: {payload['checkout_count']}")
        print(f"- requires preservation: {payload['requires_preservation_count']}")
        for item in payload["checkouts"]:
            print(
                f"  - {item['path']} "
                f"(name_match={item['contains_arkon_name']}, upstream_origin={item['is_upstream_origin']}, "
                f"preserve={item['requires_preservation']})"
            )

    if args.fail_if_found and payload["checkout_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
