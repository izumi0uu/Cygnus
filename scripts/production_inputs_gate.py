#!/usr/bin/env python3
"""Fail-closed non-secret Production V1 decision/input gate.

The actual production-inputs JSON is intentionally gitignored. It records
identifiers and approvals rather than secret values, binds those decisions to
one release candidate, and rejects templates, unallowlisted delivery targets,
broad proxy trust, unmeasured capacity objectives, or mismatched public inputs
before deploy/promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGEST_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FQDN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PLACEHOLDERS = ("change_me", "replace", "example", "todo", "pending", "unknown", "<")
REQUIRED_APPROVALS = ("security", "operations", "release")
REQUIRED_SECRET_REFS = (
    "store_ref",
    "runtime_secret_ref",
    "mcp_token_pepper_ref",
    "delivery_hmac_secret_ref",
    "oauth_credentials_ref",
    "provider_credentials_ref",
    "database_password_ref",
    "redis_password_ref",
    "minio_credentials_ref",
    "tls_certificate_ref",
)


class GateResult(TypedDict):
    ok: bool
    failures: list[str]
    checks: dict[str, object]


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


def _object(value: object, path: str, failures: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    failures.append(f"{path} must be an object")
    return {}


def _list(value: object, path: str, failures: list[str]) -> list[Any]:
    if isinstance(value, list):
        return value
    failures.append(f"{path} must be a list")
    return []


def _ref(data: dict[str, Any], key: str, path: str, failures: list[str]) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        failures.append(f"{path}.{key} is required")
        return ""
    value = value.strip()
    if any(marker in value.lower() for marker in PLACEHOLDERS):
        failures.append(
            f"{path}.{key} is a placeholder, not an approved external reference"
        )
    if "\n" in value or "\r" in value or "=" in value:
        failures.append(
            f"{path}.{key} must be a reference/identifier, not a secret value"
        )
    return value


def _positive(
    data: dict[str, Any], key: str, path: str, failures: list[str]
) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        failures.append(f"{path}.{key} must be a positive measured numeric value")
        return None
    return float(value)


def _domain(value: str, path: str, failures: list[str]) -> str:
    normalized = value.lower()
    if value != normalized or not FQDN_RE.fullmatch(value):
        failures.append(f"{path} must be a lowercase bare public FQDN")
    return normalized


def _parse_delivery_env(
    raw: str, allowed_hosts_raw: str, failures: list[str]
) -> tuple[dict[str, str], set[str]]:
    try:
        targets = json.loads(raw)
    except json.JSONDecodeError as exc:
        failures.append(f"DELIVERY_TARGETS_JSON is not valid JSON: {exc}")
        return {}, set()
    if not isinstance(targets, dict) or not targets:
        failures.append("DELIVERY_TARGETS_JSON must be a non-empty JSON object")
        return {}, set()
    allowed_hosts = {
        host.strip().lower().rstrip(".")
        for host in allowed_hosts_raw.split(",")
        if host.strip()
    }
    if not allowed_hosts:
        failures.append("CYGNUS_DELIVERY_ALLOWED_HOSTS must be non-empty")
    normalized: dict[str, str] = {}
    for channel, endpoint in targets.items():
        if not isinstance(channel, str) or not CHANNEL_RE.fullmatch(channel):
            failures.append(f"DELIVERY_TARGETS_JSON has invalid channel id {channel!r}")
            continue
        if not isinstance(endpoint, str):
            failures.append(
                f"DELIVERY_TARGETS_JSON.{channel} must be an HTTPS endpoint string"
            )
            continue
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            failures.append(
                f"DELIVERY_TARGETS_JSON.{channel} must be a credential-free HTTPS URL without query/fragment"
            )
            continue
        if host not in allowed_hosts:
            failures.append(
                f"DELIVERY_TARGETS_JSON.{channel} host {host!r} is not allowlisted"
            )
            continue
        normalized[channel] = endpoint
    return normalized, allowed_hosts


def _validate_delivery(
    delivery: dict[str, Any],
    *,
    targets_json: str,
    allowed_hosts_raw: str,
    hmac_secret_ref: str,
    failures: list[str],
    checks: dict[str, object],
) -> None:
    manifest_secret_ref = _ref(delivery, "hmac_secret_ref", "delivery", failures)
    _ref(delivery, "approval_ref", "delivery", failures)
    expected_targets, env_hosts = _parse_delivery_env(
        targets_json, allowed_hosts_raw, failures
    )
    targets = _list(delivery.get("targets"), "delivery.targets", failures)
    manifest_targets: dict[str, str] = {}
    for index, target in enumerate(targets):
        item = _object(target, f"delivery.targets[{index}]", failures)
        channel = _ref(item, "channel_id", f"delivery.targets[{index}]", failures)
        endpoint = _ref(item, "endpoint", f"delivery.targets[{index}]", failures)
        if channel and not CHANNEL_RE.fullmatch(channel):
            failures.append(f"delivery.targets[{index}].channel_id is invalid")
        parsed = urlsplit(endpoint)
        if endpoint:
            hostname = parsed.hostname
            if (
                not hostname
                or parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                failures.append(
                    f"delivery.targets[{index}].endpoint must be a credential-free HTTPS URL without query/fragment"
                )
            elif hostname.lower().rstrip(".") not in env_hosts:
                failures.append(
                    f"delivery.targets[{index}].endpoint host is not in CYGNUS_DELIVERY_ALLOWED_HOSTS"
                )
        if channel:
            if channel in manifest_targets:
                failures.append(f"delivery.targets repeats channel_id {channel!r}")
            manifest_targets[channel] = endpoint
    if not manifest_targets:
        failures.append("delivery.targets must contain at least one approved channel")
    if manifest_targets != expected_targets:
        failures.append("delivery.targets must exactly match DELIVERY_TARGETS_JSON")
    if not hmac_secret_ref:
        failures.append("CYGNUS_DELIVERY_HMAC_SECRET_REF was not supplied")
    elif manifest_secret_ref != hmac_secret_ref:
        failures.append(
            "delivery.hmac_secret_ref does not match CYGNUS_DELIVERY_HMAC_SECRET_REF"
        )
    checks["delivery_channels"] = sorted(manifest_targets)
    checks["delivery_target_binding"] = manifest_targets == expected_targets
    checks["delivery_hmac_ref_binding"] = (
        bool(hmac_secret_ref) and manifest_secret_ref == hmac_secret_ref
    )


def _validate_alert_inputs(
    observability: dict[str, Any],
    *,
    alert_approval_ref: str,
    alert_thresholds_ref: str,
    alert_thresholds_sha256: str,
    failures: list[str],
    checks: dict[str, object],
) -> None:
    approved_approval_ref = _ref(
        observability, "approval_ref", "observability", failures
    )
    approved_thresholds_ref = _ref(
        observability, "alert_thresholds_ref", "observability", failures
    )
    threshold_hash = _ref(
        observability, "alert_thresholds_sha256", "observability", failures
    )
    if threshold_hash and not SHA256_RE.fullmatch(threshold_hash):
        failures.append("observability.alert_thresholds_sha256 must be sha256:<64 hex>")
    if approved_approval_ref != alert_approval_ref:
        failures.append(
            "observability.approval_ref must exactly match CYGNUS_ALERT_APPROVAL_REF"
        )
    if approved_thresholds_ref != alert_thresholds_ref:
        failures.append(
            "observability.alert_thresholds_ref must exactly match CYGNUS_ALERT_THRESHOLDS_REF"
        )
    if threshold_hash != alert_thresholds_sha256:
        failures.append(
            "observability.alert_thresholds_sha256 must exactly match CYGNUS_ALERT_THRESHOLDS_SHA256"
        )
    checks["alert_threshold_binding"] = (
        approved_approval_ref == alert_approval_ref
        and approved_thresholds_ref == alert_thresholds_ref
        and threshold_hash == alert_thresholds_sha256
    )


def load_inputs(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("production input manifest must be a JSON object")
    return raw


def validate_inputs(
    inputs: dict[str, Any],
    *,
    git_sha: str,
    backend_image: str,
    frontend_image: str,
    alembic_head: str,
    expected_proxy_cidr: str,
    domain: str,
    delivery_targets_json: str,
    delivery_allowed_hosts: str,
    delivery_hmac_secret_ref: str,
    metrics_allowlist_ref: str,
    metrics_allowed_cidr: str,
    alert_approval_ref: str,
    alert_thresholds_ref: str,
    alert_thresholds_sha256: str,
    capacity_approval_ref: str,
    capacity_thresholds_ref: str,
    capacity_targets_ref: str,
    capacity_thresholds_sha256: str,
    backup_source_identity: str,
    rpo_objective_ref: str,
    rto_objective_ref: str,
) -> GateResult:
    failures: list[str] = []
    checks: dict[str, object] = {}
    if inputs.get("schema_version") != 2:
        failures.append("schema_version must be 2")
    if inputs.get("status") != "approved":
        failures.append(
            "status must be 'approved'; templates and unapproved decisions cannot promote"
        )

    release = _object(inputs.get("release"), "release", failures)
    actual_release = {
        key: _ref(release, key, "release", failures)
        for key in ("git_sha", "backend_image", "frontend_image", "alembic_head")
    }
    if not SHA_RE.fullmatch(actual_release["git_sha"]):
        failures.append("release.git_sha must be a commit SHA")
    for field in ("backend_image", "frontend_image"):
        if not DIGEST_RE.fullmatch(actual_release[field]):
            failures.append(
                f"release.{field} must be an exact name@sha256 image reference"
            )
    for field, expected in (
        ("git_sha", git_sha),
        ("backend_image", backend_image),
        ("frontend_image", frontend_image),
        ("alembic_head", alembic_head),
    ):
        matches = bool(expected) and actual_release[field] == expected
        checks[f"release_{field}"] = {"matches": matches}
        if not expected:
            failures.append(f"expected release {field} was not supplied to the gate")
        elif not matches:
            failures.append(
                f"release.{field} does not match the candidate being promoted"
            )

    hosting = _object(inputs.get("hosting"), "hosting", failures)
    _ref(hosting, "host_ref", "hosting", failures)
    _ref(hosting, "region", "hosting", failures)
    network = _object(hosting.get("network"), "hosting.network", failures)
    proxy_cidr = _ref(network, "proxy_cidr", "hosting.network", failures)
    _ref(network, "ingress_policy_ref", "hosting.network", failures)
    approved_metrics_ref = _ref(
        network, "metrics_allowlist_ref", "hosting.network", failures
    )
    approved_metrics_cidr = _ref(
        network, "metrics_allowed_cidr", "hosting.network", failures
    )
    try:
        parsed_metrics = ipaddress.ip_network(approved_metrics_cidr, strict=True)
    except ValueError:
        failures.append("hosting.network.metrics_allowed_cidr must be a valid CIDR")
    else:
        if (
            parsed_metrics.prefixlen == 0
            or str(parsed_metrics) != approved_metrics_cidr
        ):
            failures.append(
                "hosting.network.metrics_allowed_cidr must be a normalized non-global CIDR"
            )
    if approved_metrics_ref != metrics_allowlist_ref:
        failures.append(
            "hosting.network.metrics_allowlist_ref must exactly match CYGNUS_METRICS_ALLOWLIST_REF"
        )
    if approved_metrics_cidr != metrics_allowed_cidr:
        failures.append(
            "hosting.network.metrics_allowed_cidr must exactly match CYGNUS_METRICS_ALLOWED_CIDR"
        )
    checks["metrics_allowlist_binding"] = (
        approved_metrics_ref == metrics_allowlist_ref
        and approved_metrics_cidr == metrics_allowed_cidr
    )
    try:
        parsed_proxy = ipaddress.ip_network(proxy_cidr, strict=True)
    except ValueError:
        failures.append("hosting.network.proxy_cidr must be a valid CIDR")
    else:
        if parsed_proxy.prefixlen == 0:
            failures.append(
                "hosting.network.proxy_cidr must not trust the entire address space"
            )
        if proxy_cidr != expected_proxy_cidr:
            failures.append(
                "hosting.network.proxy_cidr must match the deterministic Compose proxy network"
            )

    registry = _object(inputs.get("registry"), "registry", failures)
    _ref(registry, "repository_ref", "registry", failures)
    _ref(registry, "credential_ref", "registry", failures)
    secrets = _object(inputs.get("secrets"), "secrets", failures)
    for key in REQUIRED_SECRET_REFS:
        _ref(secrets, key, "secrets", failures)

    endpoint = _object(inputs.get("public_endpoint"), "public_endpoint", failures)
    approved_domain = _domain(
        _ref(endpoint, "domain", "public_endpoint", failures),
        "public_endpoint.domain",
        failures,
    )
    env_domain = _domain(domain, "CYGNUS_DOMAIN", failures)
    if approved_domain != env_domain:
        failures.append("public_endpoint.domain must exactly match CYGNUS_DOMAIN")
    checks["public_domain_binding"] = approved_domain == env_domain
    _ref(endpoint, "dns_change_ref", "public_endpoint", failures)
    _ref(endpoint, "tls_validation_ref", "public_endpoint", failures)

    capacity = _object(inputs.get("capacity"), "capacity", failures)
    approved_approval_ref = _ref(capacity, "approval_ref", "capacity", failures)
    approved_thresholds_ref = _ref(capacity, "thresholds_ref", "capacity", failures)
    approved_targets_ref = _ref(capacity, "targets_ref", "capacity", failures)
    threshold_hash = _ref(capacity, "thresholds_sha256", "capacity", failures)
    if threshold_hash and not SHA256_RE.fullmatch(threshold_hash):
        failures.append("capacity.thresholds_sha256 must be sha256:<64 hex>")
    if approved_approval_ref != capacity_approval_ref:
        failures.append(
            "capacity.approval_ref must exactly match CYGNUS_CAPACITY_APPROVAL_REF"
        )
    if approved_thresholds_ref != capacity_thresholds_ref:
        failures.append(
            "capacity.thresholds_ref must exactly match CYGNUS_CAPACITY_THRESHOLDS_REF"
        )
    if approved_targets_ref != capacity_targets_ref:
        failures.append(
            "capacity.targets_ref must exactly match CYGNUS_CAPACITY_TARGETS_REF"
        )
    if threshold_hash != capacity_thresholds_sha256:
        failures.append(
            "capacity.thresholds_sha256 must exactly match CYGNUS_CAPACITY_THRESHOLDS_SHA256"
        )
    checks["capacity_threshold_binding"] = (
        threshold_hash == capacity_thresholds_sha256
        and approved_approval_ref == capacity_approval_ref
        and approved_thresholds_ref == capacity_thresholds_ref
        and approved_targets_ref == capacity_targets_ref
    )
    observability = _object(inputs.get("observability"), "observability", failures)
    _validate_alert_inputs(
        observability,
        alert_approval_ref=alert_approval_ref,
        alert_thresholds_ref=alert_thresholds_ref,
        alert_thresholds_sha256=alert_thresholds_sha256,
        failures=failures,
        checks=checks,
    )
    capacity_values = {
        key: _positive(capacity, key, "capacity", failures)
        for key in (
            "max_p95_latency_ms",
            "max_error_rate_percent",
            "max_queue_age_seconds",
            "max_worker_utilization_percent",
        )
    }
    for key in ("max_error_rate_percent", "max_worker_utilization_percent"):
        capacity_value = capacity_values[key]
        if capacity_value is not None and capacity_value > 100:
            failures.append(f"capacity.{key} must be <= 100")

    objectives = _object(inputs.get("objectives"), "objectives", failures)
    slo = _positive(objectives, "availability_slo_percent", "objectives", failures)
    if slo is not None and slo > 100:
        failures.append("objectives.availability_slo_percent must be <= 100")
    for key in ("rpo_seconds", "rto_seconds", "retention_days", "drill_cadence_days"):
        _positive(objectives, key, "objectives", failures)
    approved_rpo_ref = _ref(objectives, "rpo_objective_ref", "objectives", failures)
    approved_rto_ref = _ref(objectives, "rto_objective_ref", "objectives", failures)
    if approved_rpo_ref != rpo_objective_ref:
        failures.append(
            "objectives.rpo_objective_ref must exactly match CYGNUS_RPO_OBJECTIVE_REF"
        )
    if approved_rto_ref != rto_objective_ref:
        failures.append(
            "objectives.rto_objective_ref must exactly match CYGNUS_RTO_OBJECTIVE_REF"
        )
    backup = _object(inputs.get("backup"), "backup", failures)
    approved_backup_identity = _ref(backup, "source_identity", "backup", failures)
    _ref(backup, "approval_ref", "backup", failures)
    if approved_backup_identity != backup_source_identity:
        failures.append(
            "backup.source_identity must exactly match CYGNUS_BACKUP_SOURCE_ID"
        )
    checks["backup_objective_binding"] = (
        approved_backup_identity == backup_source_identity
        and approved_rpo_ref == rpo_objective_ref
        and approved_rto_ref == rto_objective_ref
    )

    delivery = _object(inputs.get("delivery"), "delivery", failures)
    _validate_delivery(
        delivery,
        targets_json=delivery_targets_json,
        allowed_hosts_raw=delivery_allowed_hosts,
        hmac_secret_ref=delivery_hmac_secret_ref,
        failures=failures,
        checks=checks,
    )

    canary = _object(inputs.get("canary"), "canary", failures)
    _ref(canary, "cohort_ref", "canary", failures)
    audience_dimension = _ref(canary, "audience_dimension", "canary", failures)
    if audience_dimension not in {"plan", "region"}:
        failures.append("canary.audience_dimension must be exactly 'plan' or 'region'")
    operations = _object(inputs.get("operations"), "operations", failures)
    _ref(operations, "on_call_ref", "operations", failures)
    _ref(operations, "rollback_authority_ref", "operations", failures)
    approvals = _object(
        operations.get("approval_refs"), "operations.approval_refs", failures
    )
    for key in REQUIRED_APPROVALS:
        _ref(approvals, key, "operations.approval_refs", failures)

    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    checks["input_fingerprint_sha256"] = hashlib.sha256(canonical).hexdigest()
    return {"ok": not failures, "failures": failures, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--alembic-head", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--delivery-targets-json", required=True)
    parser.add_argument("--alert-approval-ref", required=True)
    parser.add_argument("--alert-thresholds-ref", required=True)
    parser.add_argument("--alert-thresholds-sha256", required=True)
    parser.add_argument("--delivery-allowed-hosts", required=True)
    parser.add_argument("--delivery-hmac-secret-ref", required=True)
    parser.add_argument("--metrics-allowlist-ref", required=True)
    parser.add_argument("--metrics-allowed-cidr", required=True)
    parser.add_argument("--capacity-approval-ref", required=True)
    parser.add_argument("--capacity-thresholds-ref", required=True)
    parser.add_argument("--capacity-targets-ref", required=True)
    parser.add_argument("--backup-source-identity", required=True)
    parser.add_argument("--rpo-objective-ref", required=True)
    parser.add_argument("--rto-objective-ref", required=True)
    parser.add_argument("--capacity-thresholds-sha256", required=True)
    parser.add_argument("--expected-proxy-cidr", default="172.30.0.0/24")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result: GateResult
    try:
        result = validate_inputs(
            load_inputs(args.inputs),
            git_sha=args.git_sha,
            backend_image=args.backend_image,
            frontend_image=args.frontend_image,
            alembic_head=args.alembic_head,
            expected_proxy_cidr=args.expected_proxy_cidr,
            domain=args.domain,
            delivery_targets_json=args.delivery_targets_json,
            delivery_allowed_hosts=args.delivery_allowed_hosts,
            delivery_hmac_secret_ref=args.delivery_hmac_secret_ref,
            alert_approval_ref=args.alert_approval_ref,
            alert_thresholds_ref=args.alert_thresholds_ref,
            alert_thresholds_sha256=args.alert_thresholds_sha256,
            metrics_allowlist_ref=args.metrics_allowlist_ref,
            metrics_allowed_cidr=args.metrics_allowed_cidr,
            capacity_approval_ref=args.capacity_approval_ref,
            capacity_thresholds_ref=args.capacity_thresholds_ref,
            capacity_targets_ref=args.capacity_targets_ref,
            capacity_thresholds_sha256=args.capacity_thresholds_sha256,
            backup_source_identity=args.backup_source_identity,
            rpo_objective_ref=args.rpo_objective_ref,
            rto_objective_ref=args.rto_objective_ref,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "ok": False,
            "failures": [f"cannot load production inputs: {exc}"],
            "checks": {},
        }
    report = {"gate": "production_inputs_gate", "git_sha": _git_sha(), **result}
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not result["ok"]:
        if not args.quiet:
            print("[production-inputs-gate] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet and not args.json:
        print("[production-inputs-gate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
