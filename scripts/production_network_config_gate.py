#!/usr/bin/env python3
"""Validate nginx-substituted Production V1 network inputs before Compose starts."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit


FQDN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
PLACEHOLDER_RE = re.compile(
    r"(?:change|replace|example|placeholder|todo)", re.IGNORECASE
)
RESERVED_TLDS = frozenset({"example", "invalid", "local", "localhost", "test"})


class NetworkGateResult(TypedDict):
    ok: bool
    failures: list[str]
    domain: str
    public_origin: str
    metrics_cidr: str
    proxy_cidr: str


def _public_origin_failure(*, domain: str, public_origin: str) -> str | None:
    try:
        parsed = urlsplit(public_origin)
        port = parsed.port
    except ValueError:
        return "CYGNUS_PUBLIC_ORIGIN must be a canonical HTTPS origin"
    if (
        parsed.scheme != "https"
        or parsed.hostname != domain
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        return "CYGNUS_PUBLIC_ORIGIN must be a canonical HTTPS origin for CYGNUS_DOMAIN"
    authority = domain if port is None else f"{domain}:{port}"
    if public_origin != f"https://{authority}":
        return "CYGNUS_PUBLIC_ORIGIN must not contain credentials, a path, or non-canonical host syntax"
    return None


def validate(
    *,
    domain: str,
    public_origin: str,
    metrics_cidr: str,
    expected_proxy_cidr: str,
) -> NetworkGateResult:
    failures: list[str] = []
    if (
        domain != domain.lower()
        or not FQDN_RE.fullmatch(domain)
        or PLACEHOLDER_RE.search(domain)
        or domain.rsplit(".", 1)[-1] in RESERVED_TLDS
    ):
        failures.append(
            "CYGNUS_DOMAIN must be a lowercase, non-placeholder public FQDN"
        )
    origin_failure = _public_origin_failure(domain=domain, public_origin=public_origin)
    if origin_failure:
        failures.append(origin_failure)
    if (
        any(character.isspace() for character in metrics_cidr)
        or ";" in metrics_cidr
        or "$" in metrics_cidr
    ):
        failures.append(
            "CYGNUS_METRICS_ALLOWED_CIDR must be one plain CIDR with no nginx syntax"
        )
    else:
        try:
            network = ipaddress.ip_network(metrics_cidr, strict=True)
        except ValueError:
            failures.append("CYGNUS_METRICS_ALLOWED_CIDR must be one strict CIDR")
        else:
            if network.prefixlen == 0 or str(network) != metrics_cidr:
                failures.append(
                    "CYGNUS_METRICS_ALLOWED_CIDR must be a normalized non-global CIDR"
                )
    if (
        any(character.isspace() for character in expected_proxy_cidr)
        or ";" in expected_proxy_cidr
    ):
        failures.append("expected proxy CIDR is unsafe")
    else:
        try:
            proxy = ipaddress.ip_network(expected_proxy_cidr, strict=True)
        except ValueError:
            failures.append("expected proxy CIDR is invalid")
        else:
            if proxy.prefixlen == 0 or str(proxy) != expected_proxy_cidr:
                failures.append("expected proxy CIDR must be normalized and narrow")
    return {
        "ok": not failures,
        "failures": failures,
        "domain": domain,
        "public_origin": public_origin,
        "metrics_cidr": metrics_cidr,
        "proxy_cidr": expected_proxy_cidr,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--metrics-cidr", required=True)
    parser.add_argument("--expected-proxy-cidr", required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    result = validate(
        domain=args.domain,
        public_origin=args.public_origin,
        metrics_cidr=args.metrics_cidr,
        expected_proxy_cidr=args.expected_proxy_cidr,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {"gate": "production_network_config", **result},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if not result["ok"]:
        if not args.quiet:
            print("[production-network-config] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("[production-network-config] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
