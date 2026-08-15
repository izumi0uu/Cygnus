#!/usr/bin/env python3
"""Fail-closed image supply-chain gate for released Cygnus manifests.

A release must contain exact image-index digests, SPDX SBOMs, verified SLSA
provenance bound to those digests, Trivy reports without HIGH/CRITICAL findings,
and a keyless cosign verification record bound to each digest. Empty files or
truthy-looking JSON are not evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any, TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
FAILING_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
REQUIRED_PLATFORMS = ("linux/amd64", "linux/arm64")


class GateResult(TypedDict):
    ok: bool
    failures: list[str]
    checks: dict[str, object]


def load_manifest(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def _json_file(path: Path, label: str, failures: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"{label} is not valid JSON: {exc}")
        return None


def _artifact_path(
    repo_root: Path, value: object, label: str, failures: list[str]
) -> Path | None:
    if not isinstance(value, str) or not value:
        failures.append(f"{label} is missing")
        return None
    path = (repo_root / value).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError:
        failures.append(f"{label} escapes the repository: {value}")
        return None
    if not path.is_file() or path.stat().st_size == 0:
        failures.append(f"{label} file missing or empty: {value}")
        return None
    return path


def _walk_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_walk_values(item))
        payload = value.get("payload")
        if isinstance(payload, str):
            try:
                decoded = base64.b64decode(payload + "===")
                values.extend(_walk_values(json.loads(decoded.decode("utf-8"))))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk_values(item))
    return values


def _has_digest(value: Any, digest: str) -> bool:
    plain = digest.removeprefix("sha256:")
    for item in _walk_values(value):
        if isinstance(item, str) and item in {digest, plain}:
            return True
    return False


def _contains_text(value: object, fragment: str) -> bool:
    return any(
        isinstance(item, str) and fragment in item for item in _walk_values(value)
    )


def _bundle_platform_digests(
    data: object,
    *,
    label: str,
    index_digest: str,
    failures: list[str],
) -> dict[str, str] | None:
    if not isinstance(data, dict):
        failures.append(f"{label} must be a JSON object")
        return None
    if data.get("schema_version") != 1:
        failures.append(f"{label}.schema_version must be 1")
    if data.get("image_index_digest") != index_digest:
        failures.append(f"{label} is not bound to image index {index_digest}")
    raw_platforms = data.get("platforms")
    if not isinstance(raw_platforms, dict):
        failures.append(f"{label}.platforms must be an object")
        return None
    manifests: dict[str, str] = {}
    for platform in REQUIRED_PLATFORMS:
        entry = raw_platforms.get(platform)
        if not isinstance(entry, dict):
            failures.append(f"{label} is missing platform {platform}")
            continue
        manifest_digest = entry.get("manifest_digest")
        if not isinstance(manifest_digest, str) or not DIGEST_PATTERN.fullmatch(
            manifest_digest
        ):
            failures.append(f"{label}.{platform}.manifest_digest is invalid")
            continue
        manifests[platform] = manifest_digest
    return manifests


def _validate_sbom(
    path: Path,
    key: str,
    digest: str,
    failures: list[str],
    checks: dict[str, object],
) -> dict[str, str] | None:
    label = f"images.{key}.sbom"
    data = _json_file(path, label, failures)
    manifests = _bundle_platform_digests(
        data, label=label, index_digest=digest, failures=failures
    )
    if not isinstance(data, dict) or manifests is None:
        return manifests
    raw_platforms = data.get("platforms")
    if not isinstance(raw_platforms, dict):
        return manifests
    for platform in REQUIRED_PLATFORMS:
        entry = raw_platforms.get(platform)
        if not isinstance(entry, dict):
            continue
        document = entry.get("document")
        spdx = document.get("SPDXID") if isinstance(document, dict) else None
        checks[f"{key}_{platform}_sbom_spdx"] = spdx
        if not isinstance(spdx, str) or not spdx:
            failures.append(f"{label}.{platform}.document is not an SPDX document")
    return manifests


def _validate_provenance(
    path: Path,
    key: str,
    digest: str,
    failures: list[str],
    checks: dict[str, object],
) -> dict[str, str] | None:
    label = f"images.{key}.provenance"
    data = _json_file(path, label, failures)
    manifests = _bundle_platform_digests(
        data, label=label, index_digest=digest, failures=failures
    )
    if not isinstance(data, dict) or manifests is None:
        return manifests
    raw_platforms = data.get("platforms")
    if not isinstance(raw_platforms, dict):
        return manifests
    for platform, manifest_digest in manifests.items():
        entry = raw_platforms.get(platform)
        attestations = entry.get("attestations") if isinstance(entry, dict) else None
        has_slsa = _contains_text(attestations, "slsa.dev/provenance")
        digest_bound = _has_digest(attestations, manifest_digest)
        checks[f"{key}_{platform}_provenance_digest_bound"] = digest_bound
        if not isinstance(attestations, list) or not attestations:
            failures.append(f"{label}.{platform}.attestations must be non-empty")
            continue
        if not has_slsa:
            failures.append(f"{label}.{platform} has no SLSA provenance record")
        if not digest_bound:
            failures.append(f"{label}.{platform} is not bound to {manifest_digest}")
    return manifests


def _validate_verification(
    path: Path, key: str, digest: str, failures: list[str], checks: dict[str, object]
) -> None:
    data = _json_file(path, f"images.{key}.verification", failures)
    if data is None:
        return
    checks[f"{key}_signature_digest_bound"] = _has_digest(data, digest)
    if not _has_digest(data, digest):
        failures.append(
            f"images.{key}.verification is not a cosign result bound to {digest}"
        )
    serialized = json.dumps(data, sort_keys=True)
    if "docker-manifest-digest" not in serialized and "critical" not in serialized:
        failures.append(
            f"images.{key}.verification does not have cosign critical image identity"
        )


def _validate_scan(
    path: Path, key: str, failures: list[str], checks: dict[str, object]
) -> None:
    report = _json_file(path, f"images.{key}.scan", failures)
    if not isinstance(report, dict):
        return
    results = report.get("Results")
    if not isinstance(results, list):
        failures.append(f"images.{key}.scan has no Trivy Results list")
        return
    failing: list[dict[str, object]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            continue
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                continue
            severity = str(vulnerability.get("Severity", "")).upper()
            if severity in FAILING_SEVERITIES:
                failing.append(
                    {
                        "id": vulnerability.get("VulnerabilityID"),
                        "severity": severity,
                        "package": vulnerability.get("PkgName"),
                    }
                )
    checks[f"{key}_scan_failing"] = failing
    if failing:
        failures.append(
            f"images.{key}.scan contains {len(failing)} HIGH/CRITICAL vulnerabilities"
        )


def validate_manifest(manifest: dict[str, object], repo_root: Path) -> GateResult:
    failures: list[str] = []
    checks: dict[str, object] = {}
    if manifest.get("schema_version") != SCHEMA_VERSION:
        failures.append(
            f"unsupported manifest schema_version {manifest.get('schema_version')!r}; expected {SCHEMA_VERSION}"
        )
    git = manifest.get("git")
    if not isinstance(git, dict) or not re.fullmatch(
        r"[0-9a-f]{7,64}", str(git.get("sha", ""))
    ):
        failures.append("manifest is missing immutable git.sha")
    head = manifest.get("alembic_head")
    if not isinstance(head, str) or not head:
        failures.append("manifest is missing immutable alembic_head")
    images = manifest.get("images")
    if not isinstance(images, dict):
        return {
            "ok": False,
            "failures": failures + ["manifest has no images section"],
            "checks": checks,
        }
    for key in ("backend", "frontend"):
        entry = images.get(key)
        if not isinstance(entry, dict):
            failures.append(f"manifest is missing images.{key}")
            continue
        if entry.get("status") != "released":
            failures.append(f"images.{key} is not a released image")
            continue
        digest = entry.get("digest")
        if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
            failures.append(f"images.{key}.digest is not an exact sha256 digest")
            continue
        checks[f"{key}_digest"] = digest
        paths: dict[str, Path] = {}
        for artifact in (
            "sbom",
            "signature",
            "certificate",
            "verification",
            "provenance",
            "scan",
        ):
            path = _artifact_path(
                repo_root, entry.get(artifact), f"images.{key}.{artifact}", failures
            )
            if path is not None:
                paths[artifact] = path
        sbom_manifests: dict[str, str] | None = None
        provenance_manifests: dict[str, str] | None = None
        if "sbom" in paths:
            sbom_manifests = _validate_sbom(
                paths["sbom"], key, digest, failures, checks
            )
        if "provenance" in paths:
            provenance_manifests = _validate_provenance(
                paths["provenance"], key, digest, failures, checks
            )
        if (
            sbom_manifests is not None
            and provenance_manifests is not None
            and sbom_manifests != provenance_manifests
        ):
            failures.append(
                f"images.{key} SBOM and provenance platform manifests disagree"
            )
        if "verification" in paths:
            _validate_verification(paths["verification"], key, digest, failures, checks)
        if "scan" in paths:
            _validate_scan(paths["scan"], key, failures, checks)
    return {"ok": not failures, "failures": failures, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "production" / "image-manifest.json",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result: GateResult
    try:
        result = validate_manifest(
            load_manifest(args.manifest), args.repo_root.resolve()
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "ok": False,
            "failures": [f"cannot read image manifest: {exc}"],
            "checks": {},
        }
    report = {"gate": "image_gate", **result}
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not result["ok"]:
        if not args.quiet:
            print("[image-gate] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet and not args.json:
        print(
            "[image-gate] OK (digest-bound SBOM/provenance/cosign/scan evidence verified)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
