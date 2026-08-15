#!/usr/bin/env python3
"""Validate and bind an externally executed Production V1 certification report.

This is deliberately a validator, not a report generator. A trusted
self-hosted runner must execute the named real certification command first.
Only a matching native report with exact release identity and all checks passed
can produce the small evidence wrapper consumed by ``release_gate.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from release_gate import REQUIRED_LIVE_REPORT_CHECKS, validate_live_report_checks

VALID_NAMES = frozenset(REQUIRED_LIVE_REPORT_CHECKS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(
    *,
    name: str,
    report_path: Path,
    git_sha: str,
    backend_image: str,
    frontend_image: str,
    alembic_head: str,
) -> tuple[dict[str, object] | None, list[str]]:
    failures: list[str] = []
    if name not in VALID_NAMES:
        return None, [f"unsupported certification name {name!r}"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"cannot read native report: {exc}"]
    if not isinstance(report, dict):
        return None, ["native report must be a JSON object"]
    if report.get("report_format") != f"cygnus-{name}-report/v1":
        failures.append(f"report_format must be cygnus-{name}-report/v1")
    if report.get("status") != "passed":
        failures.append("status must be exactly 'passed'")
    if report.get("git_sha") != git_sha:
        failures.append("git_sha must exactly match the candidate release")
    expected_identity = {
        "git_commit": git_sha,
        "backend_image_ref": backend_image,
        "frontend_image_ref": frontend_image,
        "alembic_head": alembic_head,
    }
    release_identity = report.get("release_identity")
    if not isinstance(release_identity, dict) or any(
        release_identity.get(key) != value for key, value in expected_identity.items()
    ):
        failures.append("release_identity must exactly match the candidate release")
    if (
        not isinstance(report.get("generated_at"), str)
        or not report["generated_at"].strip()
    ):
        failures.append("generated_at is required")
    failures.extend(validate_live_report_checks(name, report))
    return report, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, choices=sorted(VALID_NAMES))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--alembic-head", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report, failures = validate(
        name=args.name,
        report_path=args.report,
        git_sha=args.git_sha,
        backend_image=args.backend_image,
        frontend_image=args.frontend_image,
        alembic_head=args.alembic_head,
    )
    if failures:
        print("[live-certification-report] FAILED", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    assert report is not None
    wrapper = {
        "schema_version": 1,
        "name": args.name,
        "passed": True,
        "git_sha": args.git_sha,
        "tool": "external-production-certification",
        "checks": {"report_sha256": sha256(args.report), "native_status": "passed"},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(wrapper, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[live-certification-report] OK: {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
