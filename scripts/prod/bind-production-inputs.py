#!/usr/bin/env python3
"""Bind approved Production V1 policy inputs to one immutable release."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import cast

SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
DIGEST_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_RELEASE_KEYS = (
    "APP_RELEASE",
    "APP_COMMIT_SHA",
    "CYGNUS_API_IMAGE",
    "CYGNUS_FRONTEND_IMAGE",
    "EXPECTED_ALEMBIC_HEAD",
)


def load_release_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number} must be a plain KEY=value record")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path}:{line_number} has an invalid key")
        if key in values:
            raise ValueError(f"{path}:{line_number} repeats {key}")
        values[key] = value
    missing = [key for key in REQUIRED_RELEASE_KEYS if not values.get(key)]
    if missing:
        raise ValueError("release metadata is missing: " + ", ".join(missing))
    if not IDENTIFIER_RE.fullmatch(values["APP_RELEASE"]):
        raise ValueError("APP_RELEASE is not a safe release identifier")
    if not SHA_RE.fullmatch(values["APP_COMMIT_SHA"]):
        raise ValueError("APP_COMMIT_SHA must be a full immutable commit SHA")
    if not IDENTIFIER_RE.fullmatch(values["EXPECTED_ALEMBIC_HEAD"]):
        raise ValueError("EXPECTED_ALEMBIC_HEAD is not a safe revision identifier")
    for key in ("CYGNUS_API_IMAGE", "CYGNUS_FRONTEND_IMAGE"):
        if not DIGEST_RE.fullmatch(values[key]):
            raise ValueError(f"{key} must be an exact digest-pinned image reference")
    return values


def bind(template: dict[str, object], release: dict[str, str]) -> dict[str, object]:
    if template.get("schema_version") != 2:
        raise ValueError("policy template schema_version must be 2")
    if template.get("status") != "approved":
        raise ValueError("policy template status must be approved")
    existing_release = template.get("release")
    if existing_release not in (None, {}):
        raise ValueError(
            "approved policy template must omit release identity or use an empty release object"
        )
    bound = dict(template)
    bound["release"] = {
        "git_sha": release["APP_COMMIT_SHA"],
        "backend_image": release["CYGNUS_API_IMAGE"],
        "frontend_image": release["CYGNUS_FRONTEND_IMAGE"],
        "alembic_head": release["EXPECTED_ALEMBIC_HEAD"],
    }
    bound["bound_release"] = release["APP_RELEASE"]
    return bound


class Args(argparse.Namespace):
    template: Path
    release_metadata: Path
    out: Path
    force: bool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--template", type=Path, required=True)
    _ = parser.add_argument("--release-metadata", type=Path, required=True)
    _ = parser.add_argument("--out", type=Path, required=True)
    _ = parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv, namespace=Args())
    try:
        raw_template = cast(
            object, json.loads(args.template.read_text(encoding="utf-8"))
        )
        if not isinstance(raw_template, dict):
            raise ValueError("policy template must be a JSON object")
        template = cast(dict[str, object], raw_template)
        release = load_release_metadata(args.release_metadata)
        bound = bind(template, release)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[bind-production-inputs] ERROR: {exc}", file=sys.stderr)
        return 1
    if args.out.exists() and not args.force:
        print(
            f"[bind-production-inputs] ERROR: {args.out} already exists",
            file=sys.stderr,
        )
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(bound, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o640)
    temporary.replace(args.out)
    print(f"[bind-production-inputs] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
