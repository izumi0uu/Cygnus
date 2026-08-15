#!/usr/bin/env python3
"""Run the bounded staging capacity load gate for Cygnus Production V1 (CYG-142).

Every pass number is a required external input: the machine-readable
thresholds config (``--thresholds``) and release refs (``--commit-sha``,
``--image-tag``, ``--alembic-revision``). Missing inputs BLOCK the gate:
the CLI emits a machine-readable NOT_CERTIFIED report and exits 3.

Exit codes: 0 PASS, 1 FAIL, 2 NOT_CERTIFIED, 3 BLOCKED (missing inputs).

Fault injection is fail-closed and additionally requires the runtime
confirmation ``CYGNUS_CAPACITY_GATE_INJECTION=1`` in the environment.
Reports are replayable from a recorded samples file via ``--replay-samples``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from cygnus.capacity.gate import build_blocked_report, run_load_gate
from cygnus.capacity.http_target import HttpRouteTarget
from cygnus.capacity.load import PhaseResult, phase_result_from_dict
from cygnus.capacity.report import ConfigRefs, EvidenceRefs, LoadGateReport, ReleaseRefs
from cygnus.capacity.schema import (
    APPROVAL_REFS_MISMATCH,
    APPROVAL_REFS_MISSING,
    ENVIRONMENT_NOT_STAGING,
    ENVIRONMENT_STAGING,
    GATE_FAIL,
    GATE_NOT_CERTIFIED,
    GATE_PASS,
    INJECTION_TARGETS,
    RELEASE_REFS_MISSING,
    ROUTES,
    RUN_INPUTS_MISSING,
    THRESHOLDS_MISSING,
    InjectionTarget,
    RouteId,
)
from cygnus.capacity.thresholds import CapacityThresholds, ThresholdInputError

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_NOT_CERTIFIED = 2
EXIT_BLOCKED = 3

INJECTION_CONFIRM_ENV = "CYGNUS_CAPACITY_GATE_INJECTION"
SAMPLES_SUITE = "cygnus-capacity-gate-samples"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_identity_status(
    *, commit_sha: str | None, image_tag: str | None, alembic_revision: str | None
) -> tuple[bool, tuple[str, ...]]:
    """Compare supplied refs with injected runtime identity when available."""
    expected = {
        "commit_sha": os.environ.get("APP_COMMIT_SHA")
        or os.environ.get("CYGNUS_COMMIT_SHA")
        or os.environ.get("GIT_SHA"),
        "image_tag": os.environ.get("APP_IMAGE_REF")
        or os.environ.get("CYGNUS_IMAGE_REF")
        or os.environ.get("IMAGE_REF"),
        "alembic_revision": os.environ.get("EXPECTED_ALEMBIC_HEAD"),
    }
    supplied = {
        "commit_sha": commit_sha,
        "image_tag": image_tag,
        "alembic_revision": alembic_revision,
    }
    present = [key for key, value in expected.items() if value]
    mismatches = tuple(
        f"runtime_identity_mismatch:{key}"
        for key in present
        if expected[key] != supplied[key]
    )
    verified = len(present) == len(expected) and not mismatches
    return verified, mismatches


def _emit(report: LoadGateReport, report_out: str | None, quiet: bool) -> None:
    payload = json.dumps(
        report.to_dict(), ensure_ascii=False, indent=2, sort_keys=False
    )
    if report_out:
        Path(report_out).write_text(payload + "\n", encoding="utf-8")
    elif not quiet:
        print(payload)


def _load_targets(path: str) -> dict[RouteId, HttpRouteTarget]:
    """Build bounded HTTP route targets from the deployment wiring JSON."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read targets file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"targets file {path} must contain a JSON object")
    route_configs = raw.get("routes")
    fault_config = raw.get("fault_endpoints")
    if not isinstance(route_configs, dict) or not isinstance(fault_config, dict):
        raise ValueError(
            f"targets file {path} needs 'routes' and 'fault_endpoints' objects"
        )
    missing = set(ROUTES) - set(route_configs)
    if missing:
        raise ValueError(f"targets file {path} missing routes: {sorted(missing)}")
    fault_endpoints: dict[InjectionTarget, str] = {}
    for target_name, endpoint in fault_config.items():
        if target_name not in INJECTION_TARGETS:
            raise ValueError(f"unknown fault target: {target_name}")
        if endpoint:
            fault_endpoints[target_name] = str(endpoint)
    targets: dict[RouteId, HttpRouteTarget] = {}
    for route in ROUTES:
        cfg = route_configs[route]
        if not isinstance(cfg, dict):
            raise ValueError(f"target config for {route} must be an object")
        try:
            targets[route] = HttpRouteTarget(
                url=str(cfg["url"]),
                method=str(cfg.get("method", "POST")),
                headers=cfg.get("headers"),
                payload=cfg.get("payload"),
                timeout_seconds=float(cfg.get("timeout_seconds", 30.0)),
                retries=int(cfg.get("retries", 1)),
                metrics_url=(
                    str(cfg["metrics_url"]) if cfg.get("metrics_url") else None
                ),
                metrics_headers=cfg.get("metrics_headers"),
                fault_endpoints=fault_endpoints,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid target config for {route}: {exc}") from exc
    return targets


def _load_phases(path: str) -> dict[RouteId, PhaseResult]:
    """Replay recorded phases, refusing malformed or cross-suite evidence."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read samples file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"samples file {path} must contain a JSON object")
    suite_name = raw.get("suite_name")
    if suite_name is not None and suite_name != SAMPLES_SUITE:
        raise ValueError(f"samples file {path} has unexpected suite_name")
    environment = raw.get("environment")
    if environment is not None and environment != ENVIRONMENT_STAGING:
        raise ValueError(f"samples file {path} is not staging evidence")
    phase_raw = raw.get("phases")
    if not isinstance(phase_raw, dict):
        raise ValueError(f"samples file {path} needs a 'phases' object")
    phases: dict[RouteId, PhaseResult] = {}
    for route, record in phase_raw.items():
        if route not in ROUTES:
            raise ValueError(f"samples file {path} has unknown route: {route}")
        if not isinstance(record, dict):
            raise ValueError(
                f"samples file {path} route {route} record must be an object"
            )
        phase = phase_result_from_dict(record)
        if phase.route != route:
            raise ValueError(
                f"samples file {path} route key {route} does not match phase route"
            )
        phases[route] = phase
    return phases


def _write_samples(phases: Mapping[RouteId, PhaseResult], path: str) -> None:
    payload = {
        "suite_name": SAMPLES_SUITE,
        "environment": ENVIRONMENT_STAGING,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phases": {route: phase.to_dict() for route, phase in sorted(phases.items())},
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


async def _run_and_close(
    *,
    thresholds: CapacityThresholds,
    thresholds_path: str,
    thresholds_sha256: str,
    release: ReleaseRefs,
    evidence: EvidenceRefs,
    targets: dict[RouteId, HttpRouteTarget] | None,
    replay_phases: Mapping[RouteId, PhaseResult] | None,
    injection_confirmed: bool,
    released_at: str,
    targets_file: str | None = None,
    targets_sha256: str | None = None,
) -> tuple[LoadGateReport, dict[RouteId, PhaseResult]]:
    try:
        return await run_load_gate(
            thresholds=thresholds,
            thresholds_path=thresholds_path,
            thresholds_sha256=thresholds_sha256,
            release=release,
            evidence=evidence,
            targets=targets,
            replay_phases=replay_phases,
            injection_confirmed=injection_confirmed,
            released_at=released_at,
            workload_file=thresholds_path,
            workload_sha256=thresholds_sha256,
            targets_file=targets_file,
            targets_sha256=targets_sha256,
        )
    finally:
        if targets:
            for target in targets.values():
                await target.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded staging capacity load gate (CYG-142). Thresholds and release "
            "refs are required external inputs; missing inputs BLOCK the gate."
        )
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="Required machine-readable threshold config JSON.",
    )
    parser.add_argument(
        "--commit-sha", default=None, help="Required release commit SHA."
    )
    parser.add_argument("--image-tag", default=None, help="Required release image tag.")
    parser.add_argument(
        "--alembic-revision", default=None, help="Required release Alembic revision."
    )
    parser.add_argument(
        "--capacity-approval-ref",
        default=None,
        help="Required externally approved capacity decision reference.",
    )
    parser.add_argument(
        "--capacity-thresholds-ref",
        default=None,
        help="Required externally approved thresholds reference.",
    )
    parser.add_argument(
        "--capacity-targets-ref",
        default=None,
        help="Required externally approved targets reference.",
    )
    parser.add_argument(
        "--app-version", default=None, help="Optional application version."
    )
    parser.add_argument("--environment", default=ENVIRONMENT_STAGING)
    parser.add_argument(
        "--require-runtime-identity",
        action="store_true",
        help="Block certification unless all injected runtime refs match.",
    )
    parser.add_argument(
        "--targets", default=None, help="Staging route/fault wiring JSON (live mode)."
    )
    parser.add_argument(
        "--replay-samples",
        default=None,
        help="Replay recorded samples instead of running load.",
    )
    parser.add_argument(
        "--report-out",
        default=None,
        help="Write machine-readable report JSON here (default stdout).",
    )
    parser.add_argument(
        "--samples-out",
        default=None,
        help="Write recorded samples JSON here (live mode).",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Only return the exit status."
    )
    args = parser.parse_args(argv)

    released_at = datetime.now(timezone.utc).isoformat()
    evidence = EvidenceRefs(
        run_id=uuid.uuid4().hex,
        report_path=args.report_out,
        samples_path=args.samples_out,
    )

    blocked: list[str] = []
    thresholds: CapacityThresholds | None = None
    thresholds_path = args.thresholds or ""
    thresholds_sha256 = ""
    if not args.thresholds:
        blocked.append(THRESHOLDS_MISSING)
    else:
        try:
            thresholds = CapacityThresholds.from_file(args.thresholds)
            thresholds_sha256 = _sha256_file(args.thresholds)
        except ThresholdInputError as exc:
            blocked.append(THRESHOLDS_MISSING)
            if not args.quiet:
                print(f"[load_gate] {exc}", file=sys.stderr)
        except OSError as exc:
            blocked.append(THRESHOLDS_MISSING)
            if not args.quiet:
                print(
                    f"[load_gate] cannot read thresholds file: {exc}", file=sys.stderr
                )

    supplied_approval_refs = (
        args.capacity_approval_ref,
        args.capacity_thresholds_ref,
        args.capacity_targets_ref,
    )
    if not all(supplied_approval_refs):
        blocked.append(APPROVAL_REFS_MISSING)
    elif thresholds is not None and supplied_approval_refs != (
        thresholds.approval.approval_ref,
        thresholds.approval.thresholds_ref,
        thresholds.approval.targets_ref,
    ):
        blocked.append(APPROVAL_REFS_MISMATCH)

    identity_verified, identity_reasons = _runtime_identity_status(
        commit_sha=args.commit_sha,
        image_tag=args.image_tag,
        alembic_revision=args.alembic_revision,
    )
    if identity_reasons:
        blocked.extend(identity_reasons)
    if args.require_runtime_identity and not identity_verified:
        blocked.append("runtime_identity_unverified")
    if not (args.commit_sha and args.image_tag and args.alembic_revision):
        blocked.append(RELEASE_REFS_MISSING)
    if thresholds is not None and thresholds.environment != ENVIRONMENT_STAGING:
        blocked.append(ENVIRONMENT_NOT_STAGING)
    targets: dict[RouteId, HttpRouteTarget] | None = None
    replay_phases: dict[RouteId, PhaseResult] | None = None
    targets_sha256: str | None = None
    targets_error: str | None = None
    if args.replay_samples:
        try:
            replay_phases = _load_phases(args.replay_samples)
        except ValueError as exc:
            blocked.append(RUN_INPUTS_MISSING)
            targets_error = str(exc)
    else:
        if not args.targets:
            blocked.append(RUN_INPUTS_MISSING)
        else:
            try:
                targets = _load_targets(args.targets)
                targets_sha256 = _sha256_file(args.targets)
            except (OSError, ValueError) as exc:
                blocked.append(RUN_INPUTS_MISSING)
                targets_error = str(exc)

    if targets_error and not args.quiet:
        print(f"[load_gate] {targets_error}", file=sys.stderr)

    release: ReleaseRefs | None = None
    if args.commit_sha and args.image_tag and args.alembic_revision:
        release = ReleaseRefs(
            commit_sha=args.commit_sha,
            image_tag=args.image_tag,
            alembic_revision=args.alembic_revision,
            app_version=args.app_version,
            identity_verified=identity_verified,
        )
    config = (
        ConfigRefs(
            thresholds_file=thresholds_path,
            thresholds_sha256=thresholds_sha256,
            profile_budget_seconds=(
                thresholds.load_profile.budget_seconds
                if thresholds is not None
                else 0.0
            ),
            approval_ref=(
                thresholds.approval.approval_ref if thresholds is not None else None
            ),
            thresholds_ref=(
                thresholds.approval.thresholds_ref if thresholds is not None else None
            ),
            targets_ref=(
                thresholds.approval.targets_ref if thresholds is not None else None
            ),
            thresholds_fingerprint=(
                thresholds.fingerprint() if thresholds is not None else None
            ),
            workload_file=thresholds_path,
            workload_sha256=thresholds_sha256,
            targets_file=(
                args.targets if args.targets and not args.replay_samples else None
            ),
            targets_sha256=targets_sha256,
        )
        if thresholds_path
        else None
    )

    if blocked:
        report = build_blocked_report(
            reasons=blocked,
            environment=(
                thresholds.environment if thresholds is not None else args.environment
            ),
            released_at=released_at,
            release=release,
            config=config,
            evidence=evidence,
        )
        _emit(report, args.report_out, args.quiet)
        return EXIT_BLOCKED

    assert thresholds is not None and release is not None
    if replay_phases is not None:
        # Deterministic run id so the same replay produces the identical report.
        samples_sha = _sha256_file(args.replay_samples)
        evidence = EvidenceRefs(
            run_id=hashlib.sha256(
                f"{thresholds_sha256}:{samples_sha}".encode("utf-8")
            ).hexdigest()[:16],
            report_path=args.report_out,
            samples_path=args.replay_samples,
            samples_sha256=samples_sha,
        )

    injection_confirmed = os.environ.get(INJECTION_CONFIRM_ENV) == "1"
    report, phases = asyncio.run(
        _run_and_close(
            thresholds=thresholds,
            thresholds_path=thresholds_path,
            thresholds_sha256=thresholds_sha256,
            release=release,
            evidence=evidence,
            targets=targets,
            replay_phases=replay_phases,
            injection_confirmed=injection_confirmed,
            released_at=released_at,
            targets_file=args.targets
            if args.targets and not args.replay_samples
            else None,
            targets_sha256=targets_sha256,
        )
    )
    if args.samples_out and phases:
        _write_samples(phases, args.samples_out)
        report = replace(
            report,
            evidence=replace(
                report.evidence,
                samples_path=args.samples_out,
                samples_sha256=_sha256_file(args.samples_out),
            ),
        )
    _emit(report, args.report_out, args.quiet)
    if report.status == GATE_PASS:
        return EXIT_PASS
    if report.status == GATE_FAIL:
        return EXIT_FAIL
    if report.status == GATE_NOT_CERTIFIED:
        return EXIT_NOT_CERTIFIED
    return EXIT_NOT_CERTIFIED


if __name__ == "__main__":
    raise SystemExit(main())
