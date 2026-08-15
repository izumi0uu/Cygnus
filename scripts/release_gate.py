#!/usr/bin/env python3
"""Fail-closed publication precondition for the Cygnus release pipeline.

Release promotion is allowed only after immutable-image verification and every
required, release-bound evidence record has passed. Structured live evidence is
validated instead of trusting a truthy wrapper: capacity must include five
measured routes and fault recovery; the backup drill must meet declared RPO/RTO
on an isolated target. Missing, skipped, malformed, stale, or merely truthy
("false") evidence blocks publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIRED_EVIDENCE = (
    "backend-tests",
    "frontend-tests",
    "docker-smoke",
    "migrations-applied",
    "dependency-audit",
    "secrets-scan",
    "golden-path",
    "domain-eval",
    "repo-check",
    "production-inputs",
    "capacity-gate",
    "backup-restore-drill",
    "production-e2e",
    "browser-e2e",
    "security-failure-injection",
    "persisted-domain-eval",
    "image-supply-chain",
)
STRUCTURED_REPORTS = {
    "production-inputs": "cygnus.production-inputs.json",
    "capacity-gate": "cygnus.capacity.report.json",
    "backup-restore-drill": "cygnus.drill.report.json",
    "production-e2e": "cygnus.production-e2e.json",
    "browser-e2e": "cygnus.browser-e2e.json",
    "security-failure-injection": "cygnus.security-failure-injection.json",
    "persisted-domain-eval": "cygnus.persisted-domain-eval.json",
}
REQUIRED_LIVE_REPORT_CHECKS: dict[str, frozenset[str]] = {
    "production-e2e": frozenset(
        {
            "fresh-deploy",
            "upgrade",
            "health",
            "login",
            "ingestion",
            "governance",
            "review",
            "publish",
            "retrieval",
            "restart-durability",
            "rollback",
            "teardown-diagnostics",
        }
    ),
    "browser-e2e": frozenset(
        {
            "unauthenticated-deep-link-redirect",
            "admin-login-deep-link-resume",
            "admin-static-route-smoke",
            "command-palette-keyboard",
            "mobile-navigation-and-overflow",
            "browser-runtime-health",
            "screenshot-evidence",
        }
    ),
    "security-failure-injection": frozenset(
        {
            "production-config-rejection",
            "authentication-boundary",
            "authorization-boundary",
            "oauth-output-safety",
            "oauth-state-validation",
            "oauth-pkce-validation",
            "login-abuse-protection",
            "forwarded-header-trust",
            "browser-security-headers",
            "dependency-security-gate",
            "static-security-gate",
            "actionable-failure-recovery",
        }
    ),
    "persisted-domain-eval": frozenset(
        {
            "persisted-approval-lineage",
            "persisted-publication-lineage",
            "allowed-audience-no-leakage",
            "denied-audience-no-leakage",
            "freshness-invalidation",
            "propagation-acknowledgement",
            "two-turn-truth-re-query",
            "restart-persistence",
        }
    ),
}


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_passed(evidence: dict[str, object]) -> bool:
    """Accept only JSON boolean ``true``; strings and numeric truthiness fail."""
    return evidence.get("passed") is True


def _raw_report(
    evidence: dict[str, object], name: str, evidence_dir: Path, failures: list[str]
) -> dict[str, object] | None:
    filename = STRUCTURED_REPORTS[name]
    path = evidence_dir / filename
    if not path.is_file():
        failures.append(
            f"evidence {name!r} is missing required structured report {filename}"
        )
        return None
    report = _load_json(path)
    if report is None:
        failures.append(
            f"evidence {name!r} structured report is not valid JSON: {filename}"
        )
        return None
    checks = evidence.get("checks")
    declared_hash = checks.get("report_sha256") if isinstance(checks, dict) else None
    actual_hash = _sha256(path)
    if not isinstance(declared_hash, str) or declared_hash != actual_hash:
        failures.append(
            f"evidence {name!r} structured report hash is absent or mismatched"
        )
    return report


def _all_checks_pass(report: dict[str, object]) -> bool:
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        return False
    return all(
        isinstance(check, dict) and check.get("passed") is True for check in checks
    )


def _has_evidence_content(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value) and any(
            _has_evidence_content(item) for item in value.values()
        )
    if isinstance(value, list):
        return bool(value) and any(_has_evidence_content(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def validate_live_report_checks(name: str, report: dict[str, object]) -> list[str]:
    """Validate the named, semantic checks in a native live report."""
    required = REQUIRED_LIVE_REPORT_CHECKS.get(name)
    if required is None:
        return [f"unsupported live report name {name!r}"]

    raw_checks = report.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        return [f"{name} report checks must be a non-empty list"]

    failures: list[str] = []
    checks_by_name: dict[str, dict[str, object]] = {}
    for index, raw_check in enumerate(raw_checks):
        if not isinstance(raw_check, dict):
            failures.append(f"{name} report check at index {index} must be an object")
            continue
        check_name = raw_check.get("name")
        if (
            not isinstance(check_name, str)
            or not check_name.strip()
            or check_name != check_name.strip()
        ):
            failures.append(
                f"{name} report check at index {index} must have a non-empty, "
                "trimmed string name"
            )
            continue
        if check_name in checks_by_name:
            failures.append(f"{name} report has duplicate check name: {check_name}")
        else:
            checks_by_name[check_name] = raw_check
        if raw_check.get("passed") is not True:
            failures.append(
                f"{name} report check {check_name!r} must contain JSON boolean "
                "passed: true"
            )

    missing = sorted(required - checks_by_name.keys())
    if missing:
        failures.append(
            f"{name} report is missing required checks: " + ", ".join(missing)
        )

    for check_name in sorted(required & checks_by_name.keys()):
        check = checks_by_name[check_name]
        if not any(
            isinstance(value, (dict, list)) and _has_evidence_content(value)
            for value in (check.get("evidence"), check.get("details"))
        ):
            failures.append(
                f"{name} report required check {check_name!r} must contain "
                "non-empty structured evidence or details"
            )
    return failures


def _validate_capacity(
    report: dict[str, object], manifest: dict[str, object], failures: list[str]
) -> None:
    if report.get("suite_name") != "cygnus-production-capacity-gate":
        failures.append("capacity report has an unexpected suite_name")
    if report.get("status") != "PASS" or report.get("environment") != "staging":
        failures.append("capacity report must be a PASS from staging")
    release = report.get("release")
    if not isinstance(release, dict):
        failures.append("capacity report is missing release identity")
        return
    git = cast(dict[str, object], manifest.get("git") or {})
    images = cast(dict[str, object], manifest.get("images") or {})
    backend = cast(dict[str, object], images.get("backend") or {})
    expected_image = f"{backend.get('image')}@{backend.get('digest')}"
    if release.get("commit_sha") != git.get("sha"):
        failures.append("capacity report commit_sha does not match release manifest")
    if release.get("identity_verified") is not True:
        failures.append("capacity report does not prove runtime identity verification")
    if release.get("image_tag") != expected_image:
        failures.append(
            "capacity report image_tag does not bind the backend image digest"
        )
    if release.get("alembic_revision") != manifest.get("alembic_head"):
        failures.append(
            "capacity report Alembic revision does not match release manifest"
        )
    routes = report.get("routes")
    expected_routes = {"publish", "ticket_import", "ingestion", "worker", "query"}
    if (
        not isinstance(routes, list)
        or {route.get("route") for route in routes if isinstance(route, dict)}
        != expected_routes
    ):
        failures.append("capacity report must contain all five required routes")
    elif any(
        not isinstance(route, dict)
        or route.get("measured") is not True
        or route.get("status") != "PASS"
        or not isinstance(route.get("checks"), list)
        or not route["checks"]
        or any(
            not isinstance(check, dict) or check.get("passed") is not True
            for check in route["checks"]
        )
        for route in routes
    ):
        failures.append("capacity report has an unmeasured or failed route/check")
    injection = report.get("failure_injection")
    expected_targets = {"db", "queue", "tool", "provider"}
    if (
        not isinstance(injection, dict)
        or injection.get("enabled") is not True
        or injection.get("guard_allowed") is not True
        or injection.get("recovered_all") is not True
        or set(injection.get("expected_targets", [])) != expected_targets
        or set(injection.get("exercised_targets", [])) != expected_targets
    ):
        failures.append(
            "capacity report lacks complete, guarded fault-injection recovery evidence"
        )


def _validate_drill(
    report: dict[str, object],
    evidence: dict[str, object],
    manifest: dict[str, object],
    failures: list[str],
) -> None:
    if (
        report.get("report_format") != "cygnus-drill-report/v1"
        or report.get("operation") != "drill"
        or report.get("status") != "passed"
    ):
        failures.append("backup evidence is not a passed cygnus drill report")
    wrapper_checks = evidence.get("checks")
    if not isinstance(wrapper_checks, dict):
        wrapper_checks = {}
    source = report.get("source")
    target = report.get("target")
    expected_source = wrapper_checks.get("source_identity")
    if (
        not isinstance(source, dict)
        or source.get("environment") != "production"
        or not isinstance(source.get("identity"), str)
        or source.get("identity") != expected_source
    ):
        failures.append(
            "backup drill source must be production and match the certified source identity"
        )
    if (
        not isinstance(target, dict)
        or target.get("environment") != "isolated"
        or not isinstance(target.get("identity"), str)
        or not target.get("identity")
    ):
        failures.append("backup drill target must be a named isolated target")
    git = cast(dict[str, object], manifest.get("git") or {})
    images = cast(dict[str, object], manifest.get("images") or {})
    backend = cast(dict[str, object], images.get("backend") or {})
    frontend = cast(dict[str, object], images.get("frontend") or {})
    expected_identity = {
        "git_commit": git.get("sha"),
        "backend_image_ref": f"{backend.get('image')}@{backend.get('digest')}",
        "frontend_image_ref": f"{frontend.get('image')}@{frontend.get('digest')}",
        "alembic_head": manifest.get("alembic_head"),
    }
    release_identity = report.get("release_identity")
    if not isinstance(release_identity, dict) or any(
        release_identity.get(key) != value for key, value in expected_identity.items()
    ):
        failures.append(
            "backup drill release_identity does not exactly match the candidate manifest"
        )
    identity_requirement = report.get("release_identity_requirement")
    if not isinstance(identity_requirement, dict) or any(
        identity_requirement.get(key) is not True
        for key in (
            "manifest_required",
            "expected_match_required",
            "expected_match_verified",
        )
    ):
        failures.append(
            "backup drill does not prove required release identity was verified"
        )
    rpo = report.get("rpo")
    rto = report.get("rto")
    objectives = report.get("objectives")
    for label, value, objective_key in (
        ("rpo", rpo, "rpo_max_seconds"),
        ("rto", rto, "rto_max_seconds"),
    ):
        if (
            not isinstance(value, dict)
            or value.get("measured") is not True
            or isinstance(value.get("seconds"), bool)
            or not isinstance(value.get("seconds"), (int, float))
            or value["seconds"] < 0
        ):
            failures.append(
                f"backup drill {label} must be measured with numeric seconds"
            )
        elif (
            not isinstance(objectives, dict)
            or isinstance(objectives.get(objective_key), bool)
            or not isinstance(objectives.get(objective_key), (int, float))
            or objectives[objective_key] <= 0
            or value["seconds"] > objectives[objective_key]
        ):
            failures.append(
                f"backup drill {label} does not satisfy a positive declared objective"
            )
    objective_refs = report.get("objective_refs")
    if (
        not isinstance(objective_refs, dict)
        or objective_refs.get("rpo_objective_ref")
        != wrapper_checks.get("rpo_objective_ref")
        or objective_refs.get("rto_objective_ref")
        != wrapper_checks.get("rto_objective_ref")
    ):
        failures.append(
            "backup drill objective references do not match the certified approvals"
        )
    requirement = report.get("objective_requirement")
    if (
        not isinstance(requirement, dict)
        or requirement.get("required") is not True
        or requirement.get("both_declared") is not True
    ):
        failures.append(
            "backup drill does not prove both declared recovery objectives were required"
        )
    verification = report.get("verification")
    if not isinstance(verification, dict):
        failures.append("backup drill is missing verification details")
    else:
        expected_empty = (
            ("table_row_counts", "mismatches"),
            ("object_hashes", "mismatches"),
            ("foreign_keys", "orphans"),
            ("idempotency_receipts", "ledger_event_duplicate_idempotency_keys"),
            ("idempotency_receipts", "outbox_job_id_duplicates"),
            ("pending_jobs", "nonterminal_outbox_rows_after_replay"),
            ("redis", "enqueued_outbox_without_arq_job"),
            ("encrypted_config", "decrypt_failures"),
        )
        for section, key in expected_empty:
            nested = verification.get(section)
            if not isinstance(nested, dict) or nested.get(key) not in (0, [], {}):
                failures.append(
                    f"backup drill verification {section}.{key} is non-zero/non-empty"
                )
    if not _all_checks_pass(report):
        failures.append("backup drill has missing or failed checks")


def _validate_generic_live_report(
    name: str,
    report: dict[str, object],
    manifest: dict[str, object],
    failures: list[str],
) -> None:
    expected_format = f"cygnus-{name}-report/v1"
    if report.get("report_format") != expected_format:
        failures.append(f"{name} report_format must be {expected_format!r}")
    if report.get("status") != "passed":
        failures.append(f"{name} report status must be exactly 'passed'")
    git = cast(dict[str, object], manifest.get("git") or {})
    if report.get("git_sha") != git.get("sha"):
        failures.append(f"{name} report git_sha does not match release manifest")
    images = cast(dict[str, object], manifest.get("images") or {})
    backend = cast(dict[str, object], images.get("backend") or {})
    frontend = cast(dict[str, object], images.get("frontend") or {})
    expected_identity = {
        "git_commit": git.get("sha"),
        "backend_image_ref": f"{backend.get('image')}@{backend.get('digest')}",
        "frontend_image_ref": f"{frontend.get('image')}@{frontend.get('digest')}",
        "alembic_head": manifest.get("alembic_head"),
    }
    release_identity = report.get("release_identity")
    if not isinstance(release_identity, dict) or any(
        release_identity.get(key) != value for key, value in expected_identity.items()
    ):
        failures.append(
            f"{name} release_identity does not exactly match the candidate manifest"
        )
    failures.extend(validate_live_report_checks(name, report))


def _validate_production_inputs(
    report: dict[str, object],
    manifest: dict[str, object],
    failures: list[str],
) -> None:
    if report.get("gate") != "production_inputs_gate":
        failures.append("production inputs report has an unexpected gate name")
    if report.get("ok") is not True or report.get("failures") != []:
        failures.append("production inputs report is not an explicit clean pass")
    git = cast(dict[str, object], manifest.get("git") or {})
    if report.get("git_sha") != git.get("sha"):
        failures.append(
            "production inputs report git_sha does not match release manifest"
        )
    checks = report.get("checks")
    if not isinstance(checks, dict):
        failures.append("production inputs report is missing checks")
        return
    for field in (
        "git_sha",
        "backend_image",
        "frontend_image",
        "alembic_head",
    ):
        binding = checks.get(f"release_{field}")
        if not isinstance(binding, dict) or binding.get("matches") is not True:
            failures.append(
                f"production inputs report release_{field} binding did not pass"
            )
    for key in (
        "metrics_allowlist_binding",
        "public_domain_binding",
        "public_origin_binding",
        "capacity_threshold_binding",
        "alert_threshold_binding",
        "backup_objective_binding",
        "delivery_target_binding",
        "delivery_hmac_ref_binding",
    ):
        if checks.get(key) is not True:
            failures.append(f"production inputs report {key} did not pass")
    fingerprint = checks.get("input_fingerprint_sha256")
    if not isinstance(fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", fingerprint
    ):
        failures.append("production inputs report has no valid decision fingerprint")


def _validate_structured(
    name: str,
    evidence: dict[str, object],
    manifest: dict[str, object],
    evidence_dir: Path,
    failures: list[str],
) -> None:
    report = _raw_report(evidence, name, evidence_dir, failures)
    if report is None:
        return
    if name == "production-inputs":
        _validate_production_inputs(report, manifest, failures)
    elif name == "capacity-gate":
        _validate_capacity(report, manifest, failures)
    elif name == "backup-restore-drill":
        _validate_drill(report, evidence, manifest, failures)
    else:
        _validate_generic_live_report(name, report, manifest, failures)


def validate_release(
    *,
    manifest_path: Path,
    evidence_dir: Path,
    required_evidence: tuple[str, ...],
    repo_root: Path,
) -> dict[str, object]:
    failures: list[str] = []
    checks: dict[str, object] = {}
    from image_gate import load_manifest, validate_manifest

    try:
        manifest = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"cannot read image manifest {manifest_path}: {exc}")
        manifest = {}
    else:
        image_result = validate_manifest(manifest, repo_root=repo_root)
        if not image_result["ok"]:
            failures.append("image manifest failed image_gate validation")
        checks["image_gate"] = image_result["ok"]
    release_sha = str(
        cast(dict[str, object], manifest.get("git") or {}).get("sha") or "unknown"
    )
    checks["release_git_sha"] = release_sha

    for name in required_evidence:
        path = evidence_dir / f"{name}.json"
        if not path.is_file():
            failures.append(f"evidence {name!r} missing (expected {path})")
            continue
        evidence = _load_json(path)
        if evidence is None:
            failures.append(f"evidence {name!r} is not valid JSON: {path.name}")
            continue
        passed = _evidence_passed(evidence)
        checks[f"evidence_{name}"] = passed
        if not passed:
            failures.append(f"evidence {name!r} must contain JSON boolean passed: true")
            continue
        if evidence.get("git_sha") != release_sha:
            failures.append(
                f"evidence {name!r} git sha {evidence.get('git_sha')!r} does not match release sha {release_sha!r}"
            )
        if name in STRUCTURED_REPORTS:
            _validate_structured(name, evidence, manifest, evidence_dir, failures)
    return {"ok": not failures, "failures": failures, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed release gate: exact images plus complete release-bound evidence."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "production" / "image-manifest.json",
    )
    parser.add_argument(
        "--evidence-dir", type=Path, default=REPO_ROOT / "production" / "evidence"
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        help="Additional evidence name to require (repeatable).",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--quiet", action="store_true", help="Only print failures.")
    parser.add_argument(
        "--json", action="store_true", help="Emit the structured report as JSON."
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="Write the structured report to PATH."
    )
    args = parser.parse_args(argv)
    required = DEFAULT_REQUIRED_EVIDENCE + tuple(args.require)
    result = validate_release(
        manifest_path=args.manifest,
        evidence_dir=args.evidence_dir,
        required_evidence=required,
        repo_root=args.repo_root.resolve(),
    )
    report = {
        "gate": "release_gate",
        "ok": result["ok"],
        "git_sha": str(
            cast(dict[str, object], result["checks"]).get("release_git_sha", "unknown")
        ),
        **result,
    }
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if result["failures"]:
        if not args.quiet:
            print("[release-gate] FAILED — publication blocked")
        for failure in cast(list[str], result["failures"]):
            print(f"- {failure}")
        return 1
    if not args.quiet and not args.json:
        print("[release-gate] OK — publication precondition satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
