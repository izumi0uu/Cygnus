"""Machine-readable capacity gate report (CYG-142).

The report binds release refs (commit/image/Alembic revision), app refs,
config refs (thresholds path + content hash + load budget) and evidence
refs (report/samples paths), then states a verdict: PASS, FAIL, or
NOT_CERTIFIED. Reports are deterministic: the same inputs produce the same
``to_dict()``, so CI can re-derive and retain them per release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from cygnus.capacity.inject import RecoveryEvidence
from cygnus.capacity.metrics import SummaryMetrics
from cygnus.capacity.schema import (
    GATE_FAIL,
    GATE_NOT_CERTIFIED,
    GATE_PASS,
    METRICS,
    ROUTES,
    SUITE_NAME,
    Comparator,
    GateStatus,
    InjectionTarget,
    MetricId,
    RouteId,
)


def _require_blank(values: Mapping[str, str], label: str) -> None:
    blank = [key for key, value in values.items() if not value.strip()]
    if blank:
        raise ValueError(f"{label} must not be blank: {blank}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseRefs:
    """Release identity the report binds to (all required)."""

    commit_sha: str
    image_tag: str
    alembic_revision: str
    app_version: str | None = None
    identity_verified: bool = False

    def __post_init__(self) -> None:
        _require_blank(
            {
                "commit_sha": self.commit_sha,
                "image_tag": self.image_tag,
                "alembic_revision": self.alembic_revision,
            },
            "release refs",
        )
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", self.commit_sha):
            raise ValueError("commit_sha must be a full 40- or 64-hex commit id")
        if any(ch.isspace() for ch in self.image_tag) or len(self.image_tag) > 512:
            raise ValueError("image_tag must be a bounded, whitespace-free image ref")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.alembic_revision):
            raise ValueError("alembic_revision has an invalid shape")

    def to_dict(self) -> dict[str, object]:
        return {
            "commit_sha": self.commit_sha,
            "image_tag": self.image_tag,
            "alembic_revision": self.alembic_revision,
            "app_version": self.app_version,
            "identity_verified": self.identity_verified,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigRefs:
    """Which external approved inputs produced this report."""

    thresholds_file: str
    thresholds_sha256: str
    profile_budget_seconds: float
    approval_ref: str | None = None
    thresholds_ref: str | None = None
    targets_ref: str | None = None
    thresholds_fingerprint: str | None = None
    workload_file: str | None = None
    workload_sha256: str | None = None
    targets_file: str | None = None
    targets_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.thresholds_file.strip():
            raise ValueError("thresholds_file must not be blank")
        if self.profile_budget_seconds < 0:
            raise ValueError("profile_budget_seconds must be non-negative")
        for label, value in (
            ("approval_ref", self.approval_ref),
            ("thresholds_ref", self.thresholds_ref),
            ("targets_ref", self.targets_ref),
            ("workload_file", self.workload_file),
            ("targets_file", self.targets_file),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"{label} must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "thresholds_file": self.thresholds_file,
            "thresholds_sha256": self.thresholds_sha256,
            "approval_ref": self.approval_ref,
            "thresholds_ref": self.thresholds_ref,
            "targets_ref": self.targets_ref,
            "thresholds_fingerprint": self.thresholds_fingerprint,
            "profile_budget_seconds": round(self.profile_budget_seconds, 3),
            "workload_file": self.workload_file,
            "workload_sha256": self.workload_sha256,
            "targets_file": self.targets_file,
            "targets_sha256": self.targets_sha256,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceRefs:
    """Where raw load evidence is retained and how it is bound."""

    run_id: str | None = None
    report_path: str | None = None
    samples_path: str | None = None
    samples_sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "report_path": self.report_path,
            "samples_path": self.samples_path,
            "samples_sha256": self.samples_sha256,
        }


def _meets_threshold(value: float, threshold: float, comparator: Comparator) -> bool:
    if comparator == "lte":
        return value <= threshold
    if comparator == "gte":
        return value >= threshold
    raise ValueError(f"unsupported comparator: {comparator}")


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricCheck:
    """One measured metric against its explicit deployment threshold."""

    metric: MetricId
    value: float | None
    threshold: float
    comparator: Comparator
    alert_rule: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if self.metric not in METRICS:
            raise ValueError(f"unknown metric: {self.metric}")
        if self.comparator not in ("lte", "gte"):
            raise ValueError(f"unsupported comparator: {self.comparator}")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "comparator": self.comparator,
            "passed": self.passed,
            "alert_rule": self.alert_rule,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RouteResult:
    """Verdict for one route: measured metrics, checks, and status."""

    route: RouteId
    measured: bool
    samples: int
    status: GateStatus
    summary: SummaryMetrics | None
    checks: tuple[MetricCheck, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise ValueError(f"unknown route: {self.route}")
        if self.status not in (GATE_PASS, GATE_FAIL, GATE_NOT_CERTIFIED):
            raise ValueError(f"unsupported route status: {self.status}")
        object.__setattr__(
            self, "checks", tuple(sorted(self.checks, key=lambda c: c.metric))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "route": self.route,
            "measured": self.measured,
            "samples": self.samples,
            "status": self.status,
            "metrics": self.summary.to_dict() if self.summary is not None else None,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionReport:
    """Aggregate fault-injection evidence for the whole gate run."""

    enabled: bool
    guard_allowed: bool
    expected_targets: tuple[InjectionTarget, ...]
    exercised_targets: tuple[InjectionTarget, ...]
    max_recovery_seconds: float | None
    targets: tuple[RecoveryEvidence, ...] = field(default_factory=tuple)
    recovered_all: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "guard_allowed": self.guard_allowed,
            "expected_targets": list(self.expected_targets),
            "exercised_targets": list(self.exercised_targets),
            "max_recovery_seconds": self.max_recovery_seconds,
            "targets": [evidence.to_dict() for evidence in self.targets],
            "recovered_all": self.recovered_all,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadGateReport:
    """The machine-readable capacity gate report."""

    suite_name: str
    status: GateStatus
    environment: str
    released_at: str
    application: dict[str, str]
    release: ReleaseRefs | None
    config: ConfigRefs | None
    evidence: EvidenceRefs
    alert_rule_mappings: dict[str, str]
    routes: tuple[RouteResult, ...] = field(default_factory=tuple)
    failure_injection: InjectionReport
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.suite_name != SUITE_NAME:
            raise ValueError(f"unexpected suite_name: {self.suite_name}")
        if self.status not in (GATE_PASS, GATE_FAIL, GATE_NOT_CERTIFIED):
            raise ValueError(f"unsupported status: {self.status}")
        object.__setattr__(
            self, "routes", tuple(sorted(self.routes, key=lambda r: r.route))
        )
        object.__setattr__(self, "reasons", tuple(sorted(set(self.reasons))))

    @property
    def totals(self) -> dict[str, int]:
        measured = [route for route in self.routes if route.measured]
        passed_routes = [route for route in self.routes if route.status == GATE_PASS]
        failed_routes = [route for route in self.routes if route.status == GATE_FAIL]
        not_certified = [
            route for route in self.routes if route.status == GATE_NOT_CERTIFIED
        ]
        checks = [check for route in self.routes for check in route.checks]
        return {
            "routes": len(self.routes),
            "measured_routes": len(measured),
            "passed_routes": len(passed_routes),
            "failed_routes": len(failed_routes),
            "not_certified_routes": len(not_certified),
            "checks": len(checks),
            "passed_checks": sum(check.passed for check in checks),
            "failed_checks": sum(
                not check.passed and check.value is not None for check in checks
            ),
            "unmeasured_checks": sum(check.value is None for check in checks),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "suite_name": self.suite_name,
            "status": self.status,
            "environment": self.environment,
            "released_at": self.released_at,
            "application": dict(sorted(self.application.items())),
            "release": self.release.to_dict() if self.release is not None else None,
            "config": self.config.to_dict() if self.config is not None else None,
            "evidence": self.evidence.to_dict(),
            "alert_rule_mappings": dict(sorted(self.alert_rule_mappings.items())),
            "totals": self.totals,
            "routes": [route.to_dict() for route in self.routes],
            "failure_injection": self.failure_injection.to_dict(),
            "reasons": list(self.reasons),
        }
