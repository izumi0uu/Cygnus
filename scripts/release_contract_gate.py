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
import os
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
        "frontend/scripts/run-browser-certification.mjs",
        "docker-compose.yml",
        "deploy/docker-compose.prod.yml",
        "deploy/image-lock.json",
        "config/observability/alert_rules.yml",
        "config/observability/alert_thresholds.schema.json",
        "cygnus/observability/alert_rules.py",
        "deploy/production-inputs.example.json",
        ".github/workflows/release.yml",
        ".github/workflows/repo-guard.yml",
        ".github/workflows/backup-restore-drill.yml",
        "scripts/prod/deploy.sh",
        "scripts/prod/rollback.sh",
        "scripts/prod/backup_restore_drill.sh",
        "scripts/run_live_production_certification.sh",
        "scripts/prod/write-release-env.py",
        "scripts/prod/rotate-secrets.sh",
        "scripts/prod/incident.sh",
        "scripts/production_inputs_gate.py",
        "scripts/collect_image_attestations.py",
        "scripts/render_alert_rules.py",
        "scripts/release_gate.py",
    )
    missing = [path for path in required_files if not (root / path).is_file()]
    checks["required_files"] = {"count": len(required_files), "missing": missing}
    failures.extend(f"required file missing: {path}" for path in missing)
    if missing:
        return {"ok": False, "failures": failures, "checks": checks}
    browser_runner = root / "frontend/scripts/run-browser-certification.mjs"
    browser_runner_executable = os.access(browser_runner, os.X_OK)
    checks["browser_certification_runner_executable"] = browser_runner_executable
    if not browser_runner_executable:
        failures.append("browser certification runner must be executable")

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
    repo_guard_workflow = _read(root, ".github/workflows/repo-guard.yml")
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
    required_proxy_port_mappings = (
        '"${CYGNUS_HTTP_BIND_PORT:-80}:8080"',
        '"${CYGNUS_HTTPS_BIND_PORT:-443}:8443"',
    )
    if "ports:" not in production_compose or any(
        mapping not in production_compose for mapping in required_proxy_port_mappings
    ):
        failures.append(
            "production compose must map public :80/:443 to unprivileged "
            "proxy :8080/:8443"
        )
    if any(mapping in production_compose for mapping in ('"80:80"', '"443:443"')):
        failures.append(
            "production compose must not use privileged proxy container ports"
        )
    if any(
        token in production_compose
        for token in ("8077:", "5432:", "6379:", "9000:", "9001:")
    ):
        failures.append("production compose exposes a non-proxy service port")
    service_sections = {
        "postgres": production_compose.partition("\n  postgres:\n")[2].partition(
            "\n  redis:\n"
        )[0],
        "redis": production_compose.partition("\n  redis:\n")[2].partition(
            "\n  minio:\n"
        )[0],
        "minio": production_compose.partition("\n  minio:\n")[2].partition(
            "\n  migrator:\n"
        )[0],
        "frontend": production_compose.partition("\n  frontend:\n")[2].partition(
            "\nsecrets:\n"
        )[0],
    }
    for service, section in service_sections.items():
        if not section:
            failures.append(f"production compose service section is missing: {service}")
            continue
        if "env_file:" in section:
            failures.append(
                f"production {service} service must not receive the shared app env file"
            )
        for secret_name in ("SECRET_KEY", "DEFAULT_ADMIN_PASSWORD", "MCP_TOKEN_PEPPER"):
            if secret_name in section:
                failures.append(
                    f"production {service} service receives unrelated app secret {secret_name}"
                )
    checks["production_service_secret_scoping"] = not any(
        "env_file:" in section for section in service_sections.values()
    )
    if "npm ci --no-audit --no-fund" not in _read(root, "frontend/Dockerfile"):
        failures.append("frontend Dockerfile must install through npm ci")
    if "uv sync --frozen" not in _read(root, "Dockerfile"):
        failures.append("backend Dockerfile must install through uv sync --frozen")

    required_workflow_fragments = (
        "uv sync --frozen",
        "uv run ruff check",
        "uv run mypy",
        "uv run pytest",
        "CYGNUS_GOVERNANCE_TEST_DATABASE_URL",
        "CYGNUS_MIGRATION_TEST_DATABASE_URL",
        "CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL",
        "Prepare isolated Postgres test databases",
        "createdb -U cygnus cygnus_governance_test",
        "npm ci --no-audit --no-fund",
        "npm --prefix frontend exec -- playwright install chromium",
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
        "--signature-backend production/signatures/backend.sig",
        "--certificate-backend production/signatures/backend.crt",
        "--signature-frontend production/signatures/frontend.sig",
        "--certificate-frontend production/signatures/frontend.crt",
        "collect_image_attestations.py",
        "backend.bundle.json",
        "frontend.bundle.json",
        "image_reference_gate.py",
        "image_gate.py",
        "release_gate.py",
        "scripts/run_live_production_certification.sh",
        "CYGNUS_RELEASE: ${{ inputs.version || github.ref_name }}",
        "Bind approved production policy to candidate release",
        'scripts/prod/write-release-env.py "$CYGNUS_RELEASE"',
        "scripts/prod/bind-production-inputs.py",
        "CYGNUS_PRODUCTION_INPUTS_TEMPLATE_FILE",
        "scripts/prod/backup_restore_drill.sh",
        "--severity HIGH,CRITICAL",
        "deploy-production:",
        "needs: [build-staging-images, live-production-certification, promote-release]",
        "runs-on: [self-hosted, cygnus-production-deploy]",
        "CYGNUS_DEPLOY_IDENTITY",
        "CYGNUS_DEPLOY_HOSTNAME",
        "CYGNUS_DEPLOY_CHECKOUTS_DIR",
        "CYGNUS_OPERATOR_WORK_DIR",
        "name: promoted-release",
        'scripts/prod/deploy.sh --release "$RELEASE_VERSION"',
    )
    missing_workflow = [
        fragment for fragment in required_workflow_fragments if fragment not in workflow
    ]
    checks["workflow_required_fragments"] = {"missing": missing_workflow}
    failures.extend(
        f"release workflow missing required step/fragment: {fragment}"
        for fragment in missing_workflow
    )
    collector = _read(root, "scripts/collect_image_attestations.py")
    required_collector_fragments = (
        '"download",',
        '"sbom",',
        '"attestation",',
        '"--platform",',
        '"linux/amd64"',
        '"linux/arm64"',
        '"image_index_digest"',
        '"manifest_digest"',
    )
    missing_collector = [
        fragment
        for fragment in required_collector_fragments
        if fragment not in collector
    ]
    checks["platform_attestation_collector"] = {"missing": missing_collector}
    failures.extend(
        f"image attestation collector missing required fragment: {fragment}"
        for fragment in missing_collector
    )
    required_repo_guard_fragments = (
        "pgvector/pgvector:0.8.6-pg16-trixie@sha256:",
        "CYGNUS_GOVERNANCE_TEST_DATABASE_URL",
        "CYGNUS_MIGRATION_TEST_DATABASE_URL",
        "CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL",
        "Prepare isolated Postgres test databases",
        "createdb -U cygnus cygnus_governance_test",
        "bash scripts/repo_check.sh",
    )
    missing_repo_guard = [
        fragment
        for fragment in required_repo_guard_fragments
        if fragment not in repo_guard_workflow
    ]
    checks["repo_guard_required_fragments"] = {"missing": missing_repo_guard}
    failures.extend(
        f"repo guard workflow missing required step/fragment: {fragment}"
        for fragment in missing_repo_guard
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
    canonical_browser_runner = (
        "frontend/scripts/run-browser-certification.mjs" in live_certification_script
    )
    checks["canonical_browser_certification_runner"] = canonical_browser_runner
    if not canonical_browser_runner:
        failures.append(
            "live certification must default to the repository-owned browser runner"
        )
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
