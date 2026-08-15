"""Orchestration for the bounded staging capacity gate (CYG-142).

Verdict semantics:

* ``NOT_CERTIFIED`` -- required external inputs are missing (thresholds,
  release refs, run inputs, non-staging environment), a route was not
  measured, or fault injection was not exercised. Production cannot be
  certified from an incomplete run.
* ``FAIL`` -- every required input was present, but a measured metric
  violated its explicit threshold or an injected dependency did not
  recover within its explicit SLO.
* ``PASS`` -- every route measured, every threshold met, every configured
  fault target exercised with observed recovery.

Replay mode re-derives the identical report from a recorded samples file
(``replay_phases``), which is how CI retains and audits reports per
release.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Sequence

from cygnus.observability import record_capacity_gate_breach
from cygnus.capacity.inject import (
    InjectionNotSupported,
    InjectionScenario,
    RecoveryEvidence,
    StagingGuard,
)
from cygnus.capacity.load import PhaseResult, RouteTarget, run_route_phase
from cygnus.capacity.metrics import RouteSample, summarize_samples
from cygnus.capacity.report import (
    ConfigRefs,
    EvidenceRefs,
    InjectionReport,
    LoadGateReport,
    MetricCheck,
    ReleaseRefs,
    RouteResult,
    _meets_threshold,
)
from cygnus.capacity.schema import (
    APP_NAME,
    ENVIRONMENT_NOT_STAGING,
    ENVIRONMENT_STAGING,
    GATE_FAIL,
    GATE_NOT_CERTIFIED,
    GATE_PASS,
    INJECTION_NOT_EXERCISED,
    InjectionTarget,
    METRICS,
    RELEASE_REFS_MISSING,
    RECOVERY_NOT_OBSERVED,
    ROUTE_NOT_MEASURED,
    SUITE_NAME,
    THRESHOLDS_MISSING,
    THRESHOLD_VIOLATION,
    GateStatus,
    RouteId,
)
from cygnus.capacity.thresholds import CapacityThresholds, RouteThresholds


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_route_result(
    route: RouteId,
    phase: PhaseResult | None,
    route_thresholds: RouteThresholds,
    alert_rule_mappings: Mapping[str, str],
) -> RouteResult:
    """Compose one route verdict from its measured phase and explicit thresholds."""
    if phase is None or not phase.samples:
        return RouteResult(
            route=route,
            measured=False,
            samples=0,
            status=GATE_NOT_CERTIFIED,
            summary=None,
            checks=(),
        )
    samples: Sequence[RouteSample] = phase.samples
    summary = summarize_samples(
        samples,
        wall_seconds=phase.wall_seconds,
        recovery_seconds=(
            phase.recovery.recovery_seconds if phase.recovery is not None else None
        ),
    )
    checks: list[MetricCheck] = []
    for metric in METRICS:
        threshold = route_thresholds.threshold_for(metric)
        value = summary.value_for(metric)
        comparator = threshold.resolved_comparator(metric)
        alert_rule = alert_rule_mappings[f"{route}.{metric}"]
        if value is None:
            passed = False
            detail = "not measured"
        else:
            passed = _meets_threshold(value, threshold.value, comparator)
            detail = f"{value:g} {comparator} {threshold.value:g}"
        checks.append(
            MetricCheck(
                metric=metric,
                value=value,
                threshold=threshold.value,
                comparator=comparator,
                alert_rule=alert_rule,
                passed=passed,
                detail=detail,
            )
        )
    measured = all(check.value is not None for check in checks)
    if not measured:
        status: GateStatus = GATE_NOT_CERTIFIED
    elif all(check.passed for check in checks):
        status = GATE_PASS
    else:
        status = GATE_FAIL
    return RouteResult(
        route=route,
        measured=measured,
        samples=len(samples),
        status=status,
        summary=summary,
        checks=tuple(checks),
    )


def build_blocked_report(
    *,
    reasons: Sequence[str],
    environment: str,
    released_at: str,
    release: ReleaseRefs | None,
    config: ConfigRefs | None,
    evidence: EvidenceRefs,
) -> LoadGateReport:
    """Emit the machine-readable NOT_CERTIFIED report for missing inputs."""
    return LoadGateReport(
        suite_name=SUITE_NAME,
        status=GATE_NOT_CERTIFIED,
        environment=environment,
        released_at=released_at,
        application={
            "name": APP_NAME,
            "version": (release.app_version if release is not None else None) or "",
        },
        release=release,
        config=config,
        evidence=evidence,
        alert_rule_mappings={},
        routes=(),
        failure_injection=InjectionReport(
            enabled=False,
            guard_allowed=False,
            expected_targets=(),
            exercised_targets=(),
            max_recovery_seconds=None,
            targets=(),
            recovered_all=False,
        ),
        reasons=tuple(reasons),
    )


def _recovery_ok(
    evidence: RecoveryEvidence, max_recovery_seconds: float | None
) -> bool:
    if not evidence.recovered or evidence.failures_during_window <= 0:
        return False
    if max_recovery_seconds is not None:
        return (
            evidence.recovery_seconds is not None
            and evidence.recovery_seconds <= max_recovery_seconds
        )
    return True


def _record_capacity_check_metrics(
    route_results: Sequence[RouteResult],
    *,
    approval_ref: str,
    thresholds_ref: str,
    targets_ref: str,
    thresholds_fingerprint: str,
) -> None:
    """Publish only measured gate outcomes, bound to approved inputs.

    An unmeasured check is intentionally omitted rather than reported as a
    healthy zero; the report remains ``NOT_CERTIFIED`` for that condition.
    """
    for route_result in route_results:
        for check in route_result.checks:
            if check.value is None:
                continue
            try:
                record_capacity_gate_breach(
                    route=route_result.route,
                    metric=check.metric,
                    breached=not check.passed,
                    approval_ref=approval_ref,
                    thresholds_ref=thresholds_ref,
                    targets_ref=targets_ref,
                    thresholds_fingerprint=thresholds_fingerprint,
                )
            except Exception:
                # Capacity certification truth is the report, never telemetry.
                continue


async def run_load_gate(
    *,
    thresholds: CapacityThresholds | None,
    thresholds_path: str,
    thresholds_sha256: str,
    release: ReleaseRefs | None,
    evidence: EvidenceRefs,
    targets: Mapping[RouteId, RouteTarget] | None = None,
    replay_phases: Mapping[RouteId, PhaseResult] | None = None,
    injection_confirmed: bool = False,
    released_at: str | None = None,
    workload_file: str | None = None,
    workload_sha256: str | None = None,
    targets_file: str | None = None,
    targets_sha256: str | None = None,
) -> tuple[LoadGateReport, dict[RouteId, PhaseResult]]:
    """Run (or replay) the capacity gate and return (report, phases)."""
    released_at = released_at or _iso_now()

    blocked: list[str] = []
    if thresholds is None:
        blocked.append(THRESHOLDS_MISSING)
    if release is None:
        blocked.append(RELEASE_REFS_MISSING)
    if thresholds is not None and thresholds.environment != ENVIRONMENT_STAGING:
        blocked.append(ENVIRONMENT_NOT_STAGING)
    if blocked:
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
                    thresholds.approval.thresholds_ref
                    if thresholds is not None
                    else None
                ),
                targets_ref=(
                    thresholds.approval.targets_ref if thresholds is not None else None
                ),
                thresholds_fingerprint=(
                    thresholds.fingerprint() if thresholds is not None else None
                ),
                workload_file=workload_file or thresholds_path,
                workload_sha256=workload_sha256 or thresholds_sha256,
                targets_file=targets_file,
                targets_sha256=targets_sha256,
            )
            if thresholds_path
            else None
        )
        report = build_blocked_report(
            reasons=blocked,
            environment=(
                thresholds.environment
                if thresholds is not None
                else ENVIRONMENT_STAGING
            ),
            released_at=released_at,
            release=release,
            config=config,
            evidence=evidence,
        )
        return report, {}

    assert thresholds is not None
    injection_config = thresholds.failure_injection
    guard = StagingGuard(
        environment=thresholds.environment,
        config_enabled=injection_config.enabled,
        runtime_confirmed=injection_confirmed,
    )
    expected_targets = tuple(
        sorted(set(injection_config.route_targets.values()))
        if injection_config.enabled
        else ()
    )

    reasons: list[str] = []
    route_results: list[RouteResult] = []
    recovery_by_target: dict[InjectionTarget, RecoveryEvidence] = {}
    phases: dict[RouteId, PhaseResult] = (
        {route: phase for route, phase in replay_phases.items()}
        if replay_phases is not None
        else {}
    )

    for route in thresholds.load_profile.routes:
        profile = thresholds.load_profile.routes[route]
        scenario: InjectionScenario | None = None
        target: RouteTarget | None = None
        if replay_phases is None:
            assert targets is not None
            target = targets[route]
            if injection_config.enabled and guard.allowed:
                target_name = injection_config.route_targets.get(route)
                if target_name is not None:
                    if target.supports_injection(target_name):
                        scenario = InjectionScenario(
                            target=target_name,
                            duration_seconds=injection_config.duration_seconds,
                            post_recovery_seconds=injection_config.post_recovery_seconds,
                        )
                    else:
                        reasons.append(f"{INJECTION_NOT_EXERCISED}:{target_name}")
        if replay_phases is not None:
            phase = replay_phases.get(route)
        else:
            assert target is not None
            try:
                phase = await run_route_phase(
                    route=route,
                    target=target,
                    profile=profile,
                    scenario=scenario,
                )
            except InjectionNotSupported:
                # Fault wiring failed at runtime: keep the measurement honest,
                # but the target was never exercised, so certification is blocked.
                if scenario is not None:
                    reasons.append(f"{INJECTION_NOT_EXERCISED}:{scenario.target}")
                phase = await run_route_phase(
                    route=route,
                    target=target,
                    profile=profile,
                    scenario=None,
                )
        if phase is not None and phase.samples:
            phases[route] = phase
        if phase is not None and phase.recovery is not None:
            recovery_by_target.setdefault(phase.recovery.target, phase.recovery)
        route_results.append(
            build_route_result(
                route,
                phase,
                thresholds.thresholds[route],
                thresholds.alert_rule_mappings,
            )
        )

    exercised_targets = tuple(sorted(recovery_by_target))
    if injection_config.enabled:
        if not guard.allowed:
            reasons.append(INJECTION_NOT_EXERCISED)
        for target_name in sorted(set(expected_targets) - set(exercised_targets)):
            reasons.append(f"{INJECTION_NOT_EXERCISED}:{target_name}")

    for result in route_results:
        if not result.measured:
            reasons.append(f"{ROUTE_NOT_MEASURED}:{result.route}")
        else:
            for check in result.checks:
                if check.value is not None and not check.passed:
                    reasons.append(
                        f"{THRESHOLD_VIOLATION}:{result.route}.{check.metric}"
                    )

    for target_name in exercised_targets:
        evidence_for_target = recovery_by_target[target_name]
        if not _recovery_ok(evidence_for_target, injection_config.max_recovery_seconds):
            reasons.append(f"{RECOVERY_NOT_OBSERVED}:{target_name}")

    reasons = sorted(set(reasons))

    route_statuses = {result.status for result in route_results}
    not_certified = GATE_NOT_CERTIFIED in route_statuses or any(
        reason.startswith((f"{ROUTE_NOT_MEASURED}:", f"{INJECTION_NOT_EXERCISED}:"))
        or reason == INJECTION_NOT_EXERCISED
        for reason in reasons
    )
    if not_certified:
        status: GateStatus = GATE_NOT_CERTIFIED
    elif any(
        reason.startswith((f"{THRESHOLD_VIOLATION}:", f"{RECOVERY_NOT_OBSERVED}:"))
        for reason in reasons
    ):
        status = GATE_FAIL
    else:
        status = GATE_PASS

    injection_report = InjectionReport(
        enabled=injection_config.enabled,
        guard_allowed=guard.allowed,
        expected_targets=expected_targets,
        exercised_targets=exercised_targets,
        max_recovery_seconds=injection_config.max_recovery_seconds,
        targets=tuple(
            recovery_by_target[target_name] for target_name in exercised_targets
        ),
        recovered_all=bool(exercised_targets)
        and set(exercised_targets) == set(expected_targets)
        and all(
            _recovery_ok(evidence_for_target, injection_config.max_recovery_seconds)
            for evidence_for_target in recovery_by_target.values()
        ),
    )

    report = LoadGateReport(
        suite_name=SUITE_NAME,
        status=status,
        environment=thresholds.environment,
        released_at=released_at,
        application={
            "name": APP_NAME,
            "version": (release.app_version if release is not None else None) or "",
        },
        release=release,
        config=ConfigRefs(
            thresholds_file=thresholds_path,
            thresholds_sha256=thresholds_sha256,
            profile_budget_seconds=thresholds.load_profile.budget_seconds,
            approval_ref=thresholds.approval.approval_ref,
            thresholds_ref=thresholds.approval.thresholds_ref,
            targets_ref=thresholds.approval.targets_ref,
            thresholds_fingerprint=thresholds.fingerprint(),
            workload_file=workload_file or thresholds_path,
            workload_sha256=workload_sha256 or thresholds_sha256,
            targets_file=targets_file,
            targets_sha256=targets_sha256,
        ),
        evidence=evidence,
        alert_rule_mappings=dict(thresholds.alert_rule_mappings),
        routes=tuple(route_results),
        failure_injection=injection_report,
        reasons=tuple(reasons),
    )
    _record_capacity_check_metrics(
        route_results,
        approval_ref=thresholds.approval.approval_ref,
        thresholds_ref=thresholds.approval.thresholds_ref,
        targets_ref=thresholds.approval.targets_ref,
        thresholds_fingerprint=thresholds.fingerprint(),
    )
    return report, phases
