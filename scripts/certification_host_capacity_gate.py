#!/usr/bin/env python3
"""Fail closed when an isolated certification stack cannot fit on its host."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import TypedDict, cast

ONE_SHOT_SERVICES = frozenset(
    {"migrator"}
)  # Runs before the long-lived services and is not part of their peak.


class HostCapacityResult(TypedDict):
    ok: bool
    failures: list[str]
    total_bytes: int
    available_bytes: int
    available_cpus: int
    required_cpus: float
    required_bytes: int
    concurrent_services: list[str]
    service_limits_bytes: dict[str, int]
    service_limits_cpus: dict[str, float]


class Args(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.compose_config: Path | None = None
        self.meminfo: Path = Path("/proc/meminfo")
        self.report: Path | None = None
        self.quiet: bool = False


def _object_map(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        return None
    return cast(dict[str, object], raw)


def _physical_memory_bytes(meminfo: str) -> tuple[int, int]:
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        fields = remainder.split()
        if len(fields) != 2 or fields[1] != "kB":
            continue
        try:
            values[key] = int(fields[0]) * 1024
        except ValueError:
            continue
    missing = [key for key in ("MemTotal", "MemAvailable") if key not in values]
    if missing:
        raise ValueError(f"meminfo is missing: {', '.join(missing)}")
    return values["MemTotal"], values["MemAvailable"]


def validate(
    *, compose_config: object, meminfo: str, available_cpus: int
) -> HostCapacityResult:
    failures: list[str] = []
    service_limits: dict[str, int] = {}
    service_cpu_limits: dict[str, float] = {}
    config = _object_map(compose_config)
    services = _object_map(config.get("services")) if config is not None else None
    if services is None:
        failures.append("Compose config must contain a services object")
        services = {}

    for name, service_value in sorted(services.items()):
        service = _object_map(service_value)
        deploy = _object_map(service.get("deploy")) if service is not None else None
        resources = _object_map(deploy.get("resources")) if deploy is not None else None
        limits = _object_map(resources.get("limits")) if resources is not None else None
        raw_cpu_limit = limits.get("cpus") if limits is not None else None
        raw_limit = limits.get("memory") if limits is not None else None
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, (int, str)):
            failures.append(f"service {name!r} has no rendered numeric memory limit")
            continue
        try:
            limit = int(raw_limit)
        except ValueError:
            failures.append(f"service {name!r} has no rendered numeric memory limit")
            continue
        if limit <= 0:
            failures.append(f"service {name!r} has a non-positive memory limit")
            continue
        if isinstance(raw_cpu_limit, bool) or not isinstance(
            raw_cpu_limit, (float, int, str)
        ):
            failures.append(f"service {name!r} has no rendered numeric CPU limit")
            continue
        try:
            cpu_limit = float(raw_cpu_limit)
        except ValueError:
            failures.append(f"service {name!r} has no rendered numeric CPU limit")
            continue
        if not math.isfinite(cpu_limit) or cpu_limit <= 0:
            failures.append(f"service {name!r} has a non-positive CPU limit")
            continue
        service_cpu_limits[name] = cpu_limit
        service_limits[name] = limit

    try:
        total, available = _physical_memory_bytes(meminfo)
    except ValueError as exc:
        failures.append(str(exc))
        total = 0
        available = 0
    concurrent_services = sorted(
        name for name in services if name not in ONE_SHOT_SERVICES
    )
    required = sum(service_limits.get(name, 0) for name in concurrent_services)
    required_cpus = sum(
        service_cpu_limits.get(name, 0.0) for name in concurrent_services
    )
    if available_cpus <= 0:
        failures.append("host logical CPU count is unavailable")
    elif services and required_cpus > available_cpus:
        failures.append(
            f"certification host has {available_cpus} logical CPUs but rendered "
            + f"service limits require {required_cpus} CPUs"
        )
    if services and required:
        if total < required:
            failures.append(
                f"certification host has {total} physical memory bytes but "
                + f"rendered service limits require {required} bytes"
            )
        if available < required:
            failures.append(
                f"certification host currently has {available} available physical "
                + f"memory bytes but rendered service limits require {required} bytes"
            )
    return {
        "ok": not failures,
        "failures": failures,
        "total_bytes": total,
        "available_cpus": available_cpus,
        "required_cpus": required_cpus,
        "available_bytes": available,
        "required_bytes": required,
        "service_limits_bytes": service_limits,
        "concurrent_services": concurrent_services,
        "service_limits_cpus": service_cpu_limits,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--compose-config",
        type=Path,
        help="docker compose config --format json output; defaults to stdin",
    )
    _ = parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    _ = parser.add_argument("--report", type=Path)
    _ = parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv, namespace=Args())

    try:
        compose_text = (
            args.compose_config.read_text(encoding="utf-8")
            if args.compose_config
            else sys.stdin.read()
        )
        compose_config = cast(object, json.loads(compose_text))
        meminfo = args.meminfo.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[certification-host-capacity] FAILED: {exc}", file=sys.stderr)
        return 1

    result = validate(
        compose_config=compose_config,
        meminfo=meminfo,
        available_cpus=os.cpu_count() or 0,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        _ = args.report.write_text(
            json.dumps(
                {"gate": "certification_host_capacity", **result},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if not result["ok"]:
        if not args.quiet:
            print("[certification-host-capacity] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            f"[certification-host-capacity] OK: cpus={result['available_cpus']} "
            + f"required_cpus={result['required_cpus']} total={result['total_bytes']} "
            + f"available={result['available_bytes']} required={result['required_bytes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
