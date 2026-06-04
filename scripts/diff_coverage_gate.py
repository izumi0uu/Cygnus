#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_PATTERNS = (
    "coverage/lcov.info",
    "lcov.info",
    "coverage/*.info",
)


def discover_files() -> list[str]:
    env_value = (os.environ.get("COVERAGE_LCOV_FILES") or "").strip()
    if env_value:
        return [item.strip() for item in env_value.split(",") if item.strip()]

    found: list[str] = []
    for pattern in DEFAULT_PATTERNS:
        for path in sorted(Path(".").glob(pattern)):
            if path.is_file():
                found.append(str(path))
    return found


def run_gate(threshold: int) -> int:
    files = discover_files()
    if not files:
        print("diff-coverage: no LCOV files found; skipping gate")
        return 0

    executable = shutil.which("diff-cover")
    if not executable:
        print(
            "diff-coverage: diff-cover is not installed but LCOV files were found",
            file=sys.stderr,
        )
        return 1

    base_ref = (os.environ.get("GITHUB_BASE_REF") or "main").strip()
    cmd = [
        executable,
        *files,
        f"--compare-branch=origin/{base_ref}",
        f"--fail-under={threshold}",
    ]
    print("diff-coverage: running", " ".join(cmd))
    return subprocess.run(cmd, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optional diff coverage gate")
    parser.add_argument(
        "--threshold",
        type=int,
        default=80,
        help="minimum changed-line coverage percentage",
    )
    parser.add_argument(
        "--print-files",
        action="store_true",
        help="print discovered LCOV files and exit",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.print_files:
        files = discover_files()
        if files:
            print("\n".join(files))
        return 0
    return run_gate(args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())
