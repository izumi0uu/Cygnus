#!/usr/bin/env python3
"""Static fail-closed contract for production delivery artifacts.

This gate deliberately does not claim that a host, registry, DNS name, TLS
certificate, or secret exists. It checks that the repository cannot silently
fall back to an unpinned image, a development compose profile, or a release
workflow that skips a required evidence gate. Live registry verification is
performed separately by ``image_reference_gate.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TypedDict, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGEST_REF_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$"
)
ARG_IMAGE_RE = re.compile(
    r"^ARG\s+[A-Z][A-Z0-9_]*=(\S+@sha256:[0-9a-f]{64})\s*$", re.MULTILINE
)
DIRECT_IMAGE_RE = re.compile(
    r"^\s*image:\s+(\S+@sha256:[0-9a-f]{64})\s*$", re.MULTILINE
)
WORKFLOW_IMAGE_RE = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64})\b"
)
ACTION_SHA_RE = re.compile(
    r"^\s*uses:\s+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}\s*$", re.MULTILINE
)


class GateResult(TypedDict):
    ok: bool
    failures: list[str]
    checks: dict[str, object]


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _image_refs(root: Path) -> set[str]:
    refs: set[str] = set()
    for relative in ("Dockerfile", "frontend/Dockerfile"):
        refs.update(ARG_IMAGE_RE.findall(_read(root, relative)))
    for relative in ("docker-compose.yml", "deploy/docker-compose.prod.yml"):
        refs.update(DIRECT_IMAGE_RE.findall(_read(root, relative)))
    refs.update(WORKFLOW_IMAGE_RE.findall(_read(root, ".github/workflows/release.yml")))
    return refs


def validate_repository(root: Path = REPO_ROOT) -> GateResult:
    failures: list[str] = []
    checks: dict[str, object] = {}
    required_files = (
        "Dockerfile",
        "frontend/Dockerfile",
        "frontend/package-lock.json",
        "docker-compose.yml",
        "deploy/docker-compose.prod.yml",
        "deploy/image-lock.json",
        "config/observability/alert_rules.yml",
        "config/observability/alert_thresholds.schema.json",
        "cygnus/observability/alert_rules.py",
        "deploy/production-inputs.example.json",
        ".github/workflows/release.yml",
        ".github/workflows/backup-restore-drill.yml",
        "scripts/prod/deploy.sh",
        "scripts/prod/rollback.sh",
        "scripts/prod/backup_restore_drill.sh",
        "scripts/run_live_production_certification.sh",
        "scripts/prod/rotate-secrets.sh",
        "scripts/prod/incident.sh",
        "scripts/production_inputs_gate.py",
        "scripts/render_alert_rules.py",
        "scripts/release_gate.py",
    )
    missing = [path for path in required_files if not (root / path).is_file()]
    checks["required_files"] = {"count": len(required_files), "missing": missing}
    failures.extend(f"required file missing: {path}" for path in missing)
    if missing:
        return {"ok": False, "failures": failures, "checks": checks}

    try:
        lock = json.loads(_read(root, "deploy/image-lock.json"))
    except (OSError, json.JSONDecodeError) as exc:
        lock = {}
        failures.append(f"deploy/image-lock.json is invalid JSON: {exc}")
    lock_refs = {
        str(entry.get("reference"))
        for entry in cast(list[object], lock.get("images", []))
        if isinstance(entry, dict) and entry.get("reference")
    }
    refs = _image_refs(root)
    checks["digest_image_references"] = sorted(refs)
    checks["lock_coverage"] = sorted(refs & lock_refs)
    uncovered = sorted(refs - lock_refs)
    if uncovered:
        failures.append(
            "image references missing from deploy/image-lock.json: "
            + ", ".join(uncovered)
        )
    for ref in refs:
        if not DIGEST_REF_RE.fullmatch(ref):
            failures.append(f"image reference is not an exact digest pin: {ref}")

    local_compose = _read(root, "docker-compose.yml")
    production_compose = _read(root, "deploy/docker-compose.prod.yml")
    workflow = _read(root, ".github/workflows/release.yml")
    checks["local_profile_marked_development"] = "DEVELOPMENT ONLY" in local_compose
    if "DEVELOPMENT ONLY" not in local_compose:
        failures.append(
            "local docker-compose.yml is not explicitly marked DEVELOPMENT ONLY"
        )
    if re.search(r"^\s*build:\s*", production_compose, re.MULTILINE):
        failures.append("production compose must not contain build instructions")
    for fragment in (
        "read_only: true",
        "cap_drop:",
        "no-new-privileges:true",
        "tmpfs:",
        "deploy:",
        "resources:",
        "CYGNUS_TLS_CERT_FILE",
        "CYGNUS_TLS_KEY_FILE",
    ):
        if fragment not in production_compose:
            failures.append(
                f"production compose missing required hardening/config fragment: {fragment}"
            )
    checks["production_hardening_fragments"] = True
    if (
        "ports:" not in production_compose
        or '"80:80"' not in production_compose
        or '"443:443"' not in production_compose
    ):
        failures.append("production compose must publish the TLS reverse-proxy ports")
    if any(
        token in production_compose
        for token in ("8077:", "5432:", "6379:", "9000:", "9001:")
    ):
        failures.append("production compose exposes a non-proxy service port")
    if "npm ci --no-audit --no-fund" not in _read(root, "frontend/Dockerfile"):
        failures.append("frontend Dockerfile must install through npm ci")
    if "uv sync --frozen" not in _read(root, "Dockerfile"):
        failures.append("backend Dockerfile must install through uv sync --frozen")

    required_workflow_fragments = (
        "uv sync --frozen",
        "uv run ruff check",
        "uv run mypy",
        "uv run pytest",
        "npm ci --no-audit --no-fund",
        "npm audit --omit=dev --audit-level=high",
        "npm run lint",
        "npm test",
        "npm run build",
        "governance_golden_path_gate.py",
        "domain_eval_gate.py",
        "migration_gate.py",
        "docker_smoke.sh",
        "--platform linux/amd64,linux/arm64",
        "--provenance=true",
        "--sbom=true",
        "cosign sign",
        "cosign verify",
        "cosign download sbom",
        "cosign download attestation",
        "image_reference_gate.py",
        "image_gate.py",
        "release_gate.py",
        "scripts/run_live_production_certification.sh",
        "scripts/prod/backup_restore_drill.sh",
        "--severity HIGH,CRITICAL",
    )
    missing_workflow = [
        fragment for fragment in required_workflow_fragments if fragment not in workflow
    ]
    checks["workflow_required_fragments"] = {"missing": missing_workflow}
    failures.extend(
        f"release workflow missing required step/fragment: {fragment}"
        for fragment in missing_workflow
    )
    live_certification_script = _read(
        root, "scripts/run_live_production_certification.sh"
    )
    requires_runtime_identity = (
        "--require-runtime-identity" in live_certification_script
    )
    checks["live_certification_runtime_identity"] = requires_runtime_identity
    if not requires_runtime_identity:
        failures.append("live certification script must require exact runtime identity")
    workflow_texts = {
        path.name: path.read_text(encoding="utf-8")
        for path in (root / ".github/workflows").glob("*.yml")
    }
    unpinned_actions = [
        f"{filename}: {line.strip()}"
        for filename, text in workflow_texts.items()
        for line in text.splitlines()
        if "uses:" in line and not ACTION_SHA_RE.match(line)
    ]
    checks["unpinned_actions"] = unpinned_actions
    failures.extend(
        f"workflow action is not pinned to a commit SHA: {line}"
        for line in unpinned_actions
    )
    if (root / "frontend/pnpm-lock.yaml").exists():
        failures.append(
            "frontend/pnpm-lock.yaml must stay absent after the npm lockfile cutover"
        )
    return {"ok": not failures, "failures": failures, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_repository(args.repo_root.resolve())
    report = {"gate": "release_contract_gate", **result}
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not result["ok"]:
        if not args.quiet:
            print("[release-contract-gate] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet and not args.json:
        print("[release-contract-gate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
