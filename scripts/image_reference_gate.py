#!/usr/bin/env python3
"""Verify reviewed container pins against live registry manifest metadata.

The repository records exact tag+digest references in ``deploy/image-lock.json``.
A release must resolve every reference through ``docker buildx imagetools
inspect`` and prove that the returned index digest matches the recorded digest
and advertises both release platforms. Registry errors, missing Docker tooling,
or incomplete platform metadata are failures, never an offline pass.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PLATFORM_RE = re.compile(r"^\s*Platform:\s+([^\s]+)\s*$", re.MULTILINE)
INDEX_DIGEST_RE = re.compile(r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$", re.MULTILINE)
REQUIRED_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})


class GateResult(TypedDict):
    ok: bool
    failures: list[str]
    checks: dict[str, object]


def _string_set(value: object) -> set[str] | None:
    if not isinstance(value, list):
        return None
    values: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        values.add(item)
    return values


def _git_sha(repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def load_lock(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("image lock must contain a JSON object")
    return payload


def validate_lock_shape(lock: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if lock.get("schema_version") != 1:
        failures.append("image lock schema_version must be 1")
    required = _string_set(lock.get("required_platforms"))
    if required is None or not REQUIRED_PLATFORMS.issubset(required):
        failures.append(
            "image lock required_platforms must include linux/amd64 and linux/arm64"
        )
    images = lock.get("images")
    if not isinstance(images, list) or not images:
        return failures + ["image lock images must be a non-empty list"]
    names: set[str] = set()
    for index, entry in enumerate(images):
        if not isinstance(entry, dict):
            failures.append(f"images[{index}] must be an object")
            continue
        name = str(entry.get("name", ""))
        if not name:
            failures.append(f"images[{index}] has no name")
        elif name in names:
            failures.append(f"duplicate image lock name: {name}")
        names.add(name)
        reference = entry.get("reference")
        digest = entry.get("manifest_digest")
        if not isinstance(reference, str) or "@" not in reference:
            failures.append(f"{name or index}: reference must include @sha256 digest")
            continue
        _, reference_digest = reference.rsplit("@", 1)
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            failures.append(f"{name or index}: manifest_digest is invalid")
        elif reference_digest != digest:
            failures.append(f"{name or index}: reference and manifest_digest disagree")
        if entry.get("status") != "verified":
            failures.append(
                f"{name or index}: registry verification status is not verified"
            )
        platforms = _string_set(entry.get("platforms"))
        if platforms is None or not REQUIRED_PLATFORMS.issubset(platforms):
            failures.append(
                f"{name or index}: recorded metadata lacks required platforms"
            )
    return failures


def inspect_reference(reference: str) -> tuple[str | None, set[str], str | None]:
    docker = shutil.which("docker")
    if docker is None:
        return None, set(), "docker is required for registry metadata verification"
    try:
        result = subprocess.run(
            [docker, "buildx", "imagetools", "inspect", reference],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return None, set(), f"cannot execute docker buildx imagetools inspect: {exc}"
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        return None, set(), output.strip() or f"inspect exited {result.returncode}"
    digest_match = INDEX_DIGEST_RE.search(result.stdout)
    digest = digest_match.group(1) if digest_match else None
    platforms = set(PLATFORM_RE.findall(result.stdout))
    if digest is None:
        return None, platforms, "registry metadata did not include an index digest"
    return digest, platforms, None


def verify_lock(
    lock: dict[str, object],
    *,
    inspector: Callable[
        [str], tuple[str | None, set[str], str | None]
    ] = inspect_reference,
) -> GateResult:
    failures = validate_lock_shape(lock)
    checks: dict[str, object] = {}
    images = lock.get("images")
    if isinstance(images, list):
        for entry in images:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "<unnamed>"))
            reference = str(entry.get("reference", ""))
            expected = str(entry.get("manifest_digest", ""))
            if not reference or not expected:
                continue
            actual, platforms, error = inspector(reference)
            checks[name] = {
                "reference": reference,
                "expected_digest": expected,
                "actual_digest": actual,
                "platforms": sorted(platforms),
            }
            if error:
                failures.append(f"{name}: registry metadata unavailable: {error}")
                continue
            if actual != expected:
                failures.append(
                    f"{name}: registry digest {actual!r} does not match pinned {expected!r}"
                )
            missing = sorted(REQUIRED_PLATFORMS - platforms)
            if missing:
                failures.append(
                    f"{name}: registry manifest is missing platforms: {', '.join(missing)}"
                )
    return {"ok": not failures, "failures": failures, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock", type=Path, default=REPO_ROOT / "deploy" / "image-lock.json"
    )
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result: GateResult
    try:
        lock = load_lock(args.lock)
        result = verify_lock(lock)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "ok": False,
            "failures": [f"cannot load image lock: {exc}"],
            "checks": {},
        }
    report = {"gate": "image_reference_gate", "git_sha": _git_sha(), **result}
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not result["ok"]:
        if not args.quiet:
            print("[image-reference-gate] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet and not args.json:
        print(
            "[image-reference-gate] OK (registry digests and multi-arch platforms verified)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
