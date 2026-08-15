#!/usr/bin/env python3
"""Write a structured gate-evidence record for the Cygnus release pipeline.

Each release-gate job records its outcome as a small JSON evidence file
(default: production/evidence/<name>.json) that release_gate.py later
requires. Evidence is only written after the corresponding step succeeded —
a failed step aborts the job before evidence exists, so publication is
blocked fail-closed.

Usage:
    scripts/write_evidence.py NAME --passed [--check KEY=VALUE ...] [--tool TOOL]
        [--git-sha SHA] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "production" / "evidence"


def current_git_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_evidence(
    *,
    name: str,
    passed: bool,
    checks: dict[str, object],
    tool: str,
    git_sha: str,
) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "git_sha": git_sha,
        "tool": tool,
        "checks": checks,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a release gate evidence record."
    )
    parser.add_argument(
        "name", help="Evidence name, e.g. backend-tests, migrations-applied."
    )
    parser.add_argument(
        "--passed", action="store_true", help="Mark the gate as passed."
    )
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        help="KEY=VALUE check detail (repeatable).",
    )
    parser.add_argument(
        "--tool", default="", help="Tool/version string that produced the evidence."
    )
    parser.add_argument(
        "--git-sha", default=None, help="Release git sha (default: git rev-parse HEAD)."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: production/evidence/<name>.json).",
    )
    args = parser.parse_args(argv)

    checks: dict[str, object] = {}
    for item in args.check:
        if "=" not in item:
            print(
                f"[write-evidence] ERROR: --check must be KEY=VALUE, got {item!r}",
                file=sys.stderr,
            )
            return 1
        key, value = item.split("=", 1)
        checks[key] = value

    out = args.out or (DEFAULT_EVIDENCE_DIR / f"{args.name}.json")
    evidence = build_evidence(
        name=args.name,
        passed=args.passed,
        checks=checks,
        tool=args.tool,
        git_sha=args.git_sha or current_git_sha(REPO_ROOT),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[write-evidence] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
