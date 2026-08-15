#!/usr/bin/env python3
"""Validate Production V1's explicitly allowlisted internal delivery targets.

The runtime intentionally has no delivery target by default. Production must
supply a non-empty JSON mapping plus a separate exact hostname allowlist; this
prevents a typo or compromised non-secret environment file from redirecting
signed internal delivery requests to an arbitrary host.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit

CHANNEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
PLACEHOLDER_PATTERN = re.compile(
    r"(?:change|replace|example|placeholder|todo)", re.IGNORECASE
)


class DeliveryGateResult(TypedDict):
    ok: bool
    failures: list[str]
    targets: list[dict[str, str]]
    allowed_hosts: list[str]


def validate(targets_json: str, allowed_hosts_raw: str) -> DeliveryGateResult:
    failures: list[str] = []
    try:
        targets = json.loads(targets_json)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "failures": [f"DELIVERY_TARGETS_JSON is not valid JSON: {exc}"],
            "targets": [],
            "allowed_hosts": [],
        }
    if not isinstance(targets, dict) or not targets:
        return {
            "ok": False,
            "failures": ["DELIVERY_TARGETS_JSON must be a non-empty object"],
            "targets": [],
            "allowed_hosts": [],
        }
    allowed_hosts = {
        host.strip().lower().rstrip(".")
        for host in allowed_hosts_raw.split(",")
        if host.strip()
    }
    if not allowed_hosts:
        failures.append(
            "CYGNUS_DELIVERY_ALLOWED_HOSTS must name at least one exact internal hostname"
        )
    for host in sorted(allowed_hosts):
        if (
            not HOST_PATTERN.fullmatch(host)
            or host in {"localhost", "*"}
            or "*" in host
            or PLACEHOLDER_PATTERN.search(host)
        ):
            failures.append(f"invalid delivery allowlist host {host!r}")
    normalized: list[dict[str, str]] = []
    for channel, raw_url in sorted(targets.items()):
        if not isinstance(channel, str) or not CHANNEL_PATTERN.fullmatch(channel):
            failures.append(f"invalid delivery channel id {channel!r}")
            continue
        if (
            not isinstance(raw_url, str)
            or not raw_url.strip()
            or PLACEHOLDER_PATTERN.search(raw_url)
        ):
            failures.append(f"delivery target {channel!r} is blank or a placeholder")
            continue
        parsed = urlsplit(raw_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            failures.append(
                f"delivery target {channel!r} must be a credential-free HTTPS "
                "base origin without a non-root path, query, or fragment"
            )
            continue
        if host not in allowed_hosts:
            failures.append(
                f"delivery target {channel!r} host {host!r} is not in CYGNUS_DELIVERY_ALLOWED_HOSTS"
            )
            continue
        normalized.append({"channel": channel, "host": host, "url": raw_url})
    return {
        "ok": not failures,
        "failures": failures,
        "targets": normalized,
        "allowed_hosts": sorted(allowed_hosts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets-json", required=True)
    parser.add_argument("--allowed-hosts", required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    result = validate(args.targets_json, args.allowed_hosts)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {"gate": "production_delivery_config", **result},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if not result["ok"]:
        if not args.quiet:
            print("[production-delivery-config] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("[production-delivery-config] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
