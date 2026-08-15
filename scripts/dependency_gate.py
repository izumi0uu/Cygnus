#!/usr/bin/env python3
"""Dependency supply-chain gate for the Cygnus release pipeline.

Offline mode (default, no network, no external tools):
  - uv.lock exists, parses as TOML, and is a uv v1 lockfile;
  - every locked package pins at least one sha256 hash (sdist or wheel);
  - every direct dependency declared in pyproject.toml (runtime + dev extra)
    resolves to a package present in the lockfile.

Audit mode (--audit, used by the release workflow, requires `uv` and the
`pip-audit` dev dependency):
  - `uv lock --check` proves pyproject.toml and uv.lock are in sync;
  - the locked graph is exported and scanned by pip-audit;
  - any advisory not explicitly accepted in production/risk-acceptances.json
    fails the gate (fail-closed).

Exit status: 0 = clean, 1 = any lock/vulnerability problem.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
RISK_ACCEPTANCES = REPO_ROOT / "production" / "risk-acceptances.json"

_DIRECT_SPEC_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")


def _git_sha(repo_root: Path = REPO_ROOT) -> str:
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


def _package_name(spec: str) -> str:
    """Normalize a PEP 508 dependency string to its distribution name."""
    match = _DIRECT_SPEC_PATTERN.match(spec.strip())
    if not match:
        return spec.strip().lower()
    return match.group(0).lower()


def _load_lock(lock_path: Path) -> dict[str, object]:
    return tomllib.loads(lock_path.read_text(encoding="utf-8"))


def _locked_package_names(lock: dict[str, object]) -> set[str]:
    names: set[str] = set()
    for entry in cast(list[dict[str, object]], lock.get("package", [])):
        name = entry.get("name")
        if isinstance(name, str):
            names.add(name.lower())
    return names


def _unhashed_packages(
    lock: dict[str, object], local_project: str | None = None
) -> list[str]:
    """Return package names whose lock entries carry no sha256 hash at all.

    The local project itself (never fetched from an index) is excluded.
    """
    unhashed: list[str] = []
    for entry in cast(list[dict[str, object]], lock.get("package", [])):
        name = entry.get("name")
        if isinstance(name, str) and name.lower() == (local_project or "").lower():
            continue
        has_sha256 = False
        for key in ("sdist", "wheels"):
            value = entry.get(key)
            if key == "sdist" and isinstance(value, dict):
                if str(value.get("hash", "")).startswith("sha256:"):
                    has_sha256 = True
            elif key == "wheels" and isinstance(value, list):
                if any(
                    str(w.get("hash", "")).startswith("sha256:")
                    for w in value
                    if isinstance(w, dict)
                ):
                    has_sha256 = True
        if isinstance(name, str) and not has_sha256:
            unhashed.append(name)
    return unhashed


def _direct_dependency_names(pyproject: dict[str, object]) -> set[str]:
    project = cast(dict[str, object], pyproject.get("project", {}))
    names = {
        _package_name(spec) for spec in cast(list[str], project.get("dependencies", []))
    }
    for extra in cast(
        dict[str, list[str]], project.get("optional-dependencies", {})
    ).values():
        for spec in extra:
            names.add(_package_name(spec))
    return names


def offline_checks(repo_root: Path) -> dict[str, object]:
    """Static lockfile-integrity checks that need no network or tools."""
    failures: list[str] = []
    checks: dict[str, object] = {}

    pyproject_path = repo_root / "pyproject.toml"
    lock_path = repo_root / "uv.lock"

    checks["pyproject_present"] = pyproject_path.is_file()
    if not pyproject_path.is_file():
        failures.append("pyproject.toml is missing")
    checks["lock_present"] = lock_path.is_file()
    if not lock_path.is_file():
        failures.append("uv.lock is missing")

    lock: dict[str, object] = {}
    if lock_path.is_file():
        try:
            lock = _load_lock(lock_path)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            failures.append(f"uv.lock is not valid TOML: {exc}")
        else:
            version = lock.get("version")
            checks["lock_version"] = version
            if version != 1:
                failures.append(f"uv.lock version is {version!r}, expected 1")
            local_project: str | None = None
            if pyproject_path.is_file():
                try:
                    pyproject_probe = tomllib.loads(
                        pyproject_path.read_text(encoding="utf-8")
                    )
                except (OSError, tomllib.TOMLDecodeError):
                    pyproject_probe = {}
                else:
                    local_project = str(
                        (pyproject_probe.get("project") or {}).get("name") or ""
                    )
            unhashed = _unhashed_packages(lock, local_project=local_project)
            checks["unhashed_packages"] = unhashed
            if unhashed:
                failures.append(
                    f"{len(unhashed)} locked package(s) have no sha256 hash: {', '.join(sorted(unhashed))}"
                )

    if pyproject_path.is_file():
        try:
            pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            failures.append(f"pyproject.toml is not valid TOML: {exc}")
        else:
            required = _direct_dependency_names(pyproject)
            checks["direct_dependencies"] = sorted(required)
            if lock:
                locked = _locked_package_names(lock)
                missing = sorted(name for name in required if name not in locked)
                checks["unlocked_direct_dependencies"] = missing
                if missing:
                    failures.append(
                        "direct dependencies missing from uv.lock: "
                        + ", ".join(missing)
                    )

    return {"ok": not failures, "checks": checks, "failures": failures}


def _load_risk_acceptances(path: Path) -> set[str]:
    """Return accepted advisories as `{package}@{version}:{advisory}` keys."""
    accepted: set[str] = set()
    if not path.is_file():
        return accepted
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return accepted
    for item in data.get("acceptances", []):
        package = str(item.get("package", "")).lower()
        version = str(item.get("version", ""))
        advisory = str(item.get("advisory", ""))
        if package and version and advisory:
            accepted.add(f"{package}@{version}:{advisory}")
    return accepted


def filter_unaccepted(
    dependencies: list[dict[str, object]], accepted: set[str]
) -> list[dict[str, object]]:
    """Return pip-audit findings whose package/version/advisory is not accepted."""
    unaccepted: list[dict[str, object]] = []
    for dependency in dependencies:
        pkg = str(dependency.get("name", "")).lower()
        version = str(dependency.get("version", ""))
        findings = dependency.get("vulns", dependency.get("advisories", []))
        for advisory in cast(list[dict[str, object]], findings):
            advisory_id = str(advisory.get("id", ""))
            key = f"{pkg}@{version}:{advisory_id}"
            if key not in accepted:
                unaccepted.append(
                    {
                        "package": pkg,
                        "version": version,
                        "advisory": advisory_id,
                        "description": str(advisory.get("description", ""))[:200],
                    }
                )
    return unaccepted


def audit_checks(repo_root: Path) -> dict[str, object]:
    """Network-backed audit: uv lock sync check + pip-audit scan."""
    failures: list[str] = []
    checks: dict[str, object] = {}

    uv = shutil.which("uv")
    checks["uv_available"] = uv is not None
    if uv is None:
        failures.append("uv binary not found; locked dependency audit requires uv")
        return {"ok": False, "checks": checks, "failures": failures}

    lock_check = subprocess.run(
        [uv, "lock", "--check"], cwd=str(repo_root), capture_output=True, text=True
    )
    checks["uv_lock_check"] = lock_check.returncode == 0
    if lock_check.returncode != 0:
        failures.append(
            "uv lock --check failed: pyproject.toml and uv.lock are out of sync"
        )

    pip_audit = shutil.which("pip-audit")
    checks["pip_audit_available"] = pip_audit is not None
    if pip_audit is None:
        failures.append(
            "pip-audit binary not found; install the dev extra (uv sync --all-extras)"
        )
        return {"ok": False, "checks": checks, "failures": failures}

    accepted = _load_risk_acceptances(
        repo_root / "production" / "risk-acceptances.json"
    )
    checks["risk_acceptances"] = sorted(accepted)

    with tempfile.TemporaryDirectory(prefix="cygnus-depgate-") as tmp:
        requirements = Path(tmp) / "requirements.txt"
        exported = subprocess.run(
            [
                uv,
                "export",
                "--frozen",
                "--all-extras",
                "--no-emit-project",
                "--format",
                "requirements.txt",
            ],
            capture_output=True,
            text=True,
        )
        if exported.returncode != 0:
            failures.append(f"uv export failed: {exported.stderr.strip()}")
            return {"ok": False, "checks": checks, "failures": failures}
        requirements.write_text(exported.stdout, encoding="utf-8")

        scan = subprocess.run(
            [pip_audit, "--requirement", str(requirements), "--format", "json"],
            capture_output=True,
            text=True,
        )
        if scan.returncode not in (0, 1):
            failures.append(
                f"pip-audit failed to run: {scan.stderr.strip() or scan.stdout.strip()}"
            )
            return {"ok": False, "checks": checks, "failures": failures}

        try:
            report = json.loads(scan.stdout)
        except json.JSONDecodeError:
            failures.append("pip-audit did not return a JSON report")
            return {"ok": False, "checks": checks, "failures": failures}

        dependencies = report.get("dependencies", [])
        unaccepted = filter_unaccepted(dependencies, accepted)
        checks["dependencies"] = dependencies
        checks["unaccepted_vulnerabilities"] = unaccepted
        if unaccepted:
            failures.append(
                f"{len(unaccepted)} unaccepted vulnerable dependency/advisory pair(s)"
            )

    return {"ok": not failures, "checks": checks, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dependency supply-chain gate: lockfile integrity + optional pip-audit scan."
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Run the network-backed pip-audit scan (release workflow; requires uv + pip-audit).",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print failures.")
    parser.add_argument(
        "--json", action="store_true", help="Emit the structured report as JSON."
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="Write the structured report to PATH."
    )
    args = parser.parse_args(argv)

    offline = offline_checks(REPO_ROOT)
    if args.audit:
        audit = audit_checks(REPO_ROOT)
        failures = cast(list[str], offline["failures"]) + cast(
            list[str], audit["failures"]
        )
        ok = offline["ok"] and audit["ok"]
        report: dict[str, object] = {
            "gate": "dependency_gate",
            "mode": "audit" if args.audit else "offline",
            "ok": ok,
            "git_sha": _git_sha(),
            "offline": offline,
            "audit": audit,
        }
    else:
        failures = cast(list[str], offline["failures"])
        ok = offline["ok"]
        report = {
            "gate": "dependency_gate",
            "mode": "offline",
            "ok": ok,
            "git_sha": _git_sha(),
            "offline": offline,
        }

    if args.report is not None:
        report_path = args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if failures:
        if not args.quiet:
            print("[dependency-gate] FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if not args.quiet and not args.json:
        mode = "audit" if args.audit else "offline"
        print(f"[dependency-gate] OK ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
