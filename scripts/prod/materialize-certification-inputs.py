#!/usr/bin/env python3
"""Materialize protected release-certification inputs from bounded base64 values."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from typing import cast
from pathlib import Path

_INPUTS: tuple[tuple[str, str, str, bool], ...] = (
    (
        "CYGNUS_PRODUCTION_ENV_B64",
        "CYGNUS_PRODUCTION_ENV_FILE",
        "production.env",
        False,
    ),
    (
        "CYGNUS_PRODUCTION_INPUTS_TEMPLATE_B64",
        "CYGNUS_PRODUCTION_INPUTS_TEMPLATE_FILE",
        "production-inputs.json",
        True,
    ),
    (
        "CYGNUS_ALERT_THRESHOLDS_B64",
        "CYGNUS_ALERT_THRESHOLDS_FILE",
        "alert-thresholds.json",
        True,
    ),
    (
        "CYGNUS_CAPACITY_THRESHOLDS_B64",
        "CYGNUS_CAPACITY_THRESHOLDS_FILE",
        "capacity-thresholds.json",
        True,
    ),
    (
        "CYGNUS_CAPACITY_TARGETS_B64",
        "CYGNUS_CAPACITY_TARGETS_FILE",
        "capacity-targets.json",
        True,
    ),
)
_MAX_INPUT_BYTES = 256 * 1024


def _decode(name: str) -> bytes:
    encoded = os.environ.get(name, "")
    if not encoded:
        raise ValueError(f"{name} is required")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{name} is not valid base64") from exc
    if not data or len(data) > _MAX_INPUT_BYTES or b"\0" in data:
        raise ValueError(f"{name} decoded content is empty, oversized, or contains NUL")
    return data


class Args(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.output_dir: Path = Path()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(namespace=Args())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    for source_name, output_name, filename, require_json in _INPUTS:
        data = _decode(source_name)
        if require_json:
            try:
                payload = cast(object, json.loads(data))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{source_name} is not valid UTF-8 JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{source_name} must decode to a JSON object")
        path = output_dir / filename
        _ = path.write_bytes(data)
        path.chmod(0o600)
        print(f"{output_name}={path}")


if __name__ == "__main__":
    main()
