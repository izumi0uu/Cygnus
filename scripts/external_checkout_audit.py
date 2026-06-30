#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
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
            target = text[len(prefix):].strip()
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


def classify_repo(repo_path: Path) -> dict[str, object] | None:
    origin_url = read_origin_url(repo_path)
    contains_arkon_name = "arkon" in repo_path.name.lower()
    upstream = is_upstream_origin(origin_url)

    if not contains_arkon_name and not upstream:
        return None

    return {
        "path": str(repo_path),
        "repo_name": repo_path.name,
        "contains_arkon_name": contains_arkon_name,
        "origin_url": origin_url,
        "is_upstream_origin": upstream,
    }


def audit_external_checkouts(
    search_roots: list[Path] | None = None,
    *,
    max_depth: int = 4,
) -> dict[str, object]:
    roots = search_roots or default_search_roots()
    seen_paths: set[Path] = set()
    checkouts: list[dict[str, object]] = []

    for root in roots:
        for repo_path in iter_git_repos(root, max_depth=max_depth):
            resolved = repo_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            classified = classify_repo(resolved)
            if classified is not None:
                checkouts.append(classified)

    checkouts.sort(key=lambda item: str(item["path"]))
    return {
        "audit_name": "external_checkout_audit",
        "search_roots": [str(path) for path in roots],
        "checkout_count": len(checkouts),
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
    payload = audit_external_checkouts(search_roots, max_depth=args.max_depth)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("[external-checkout-audit]")
        print(f"- search roots: {', '.join(payload['search_roots'])}")
        print(f"- external checkout count: {payload['checkout_count']}")
        for item in payload["checkouts"]:
            print(
                f"  - {item['path']} "
                f"(name_match={item['contains_arkon_name']}, upstream_origin={item['is_upstream_origin']})"
            )

    if args.fail_if_found and payload["checkout_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
