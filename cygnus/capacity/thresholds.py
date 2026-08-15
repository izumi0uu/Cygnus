"""Machine-readable capacity threshold inputs (CYG-142).

Every pass number must arrive as an explicit external deployment input;
the gate never invents values and never falls back to defaults. Loading
failures raise :class:`ThresholdInputError`, which the CLI maps to a
blocked ``NOT_CERTIFIED`` report: production cannot be certified without
the complete threshold set.

The required config shape is also exposed as JSON Schema via
:func:`threshold_schema` so tooling can validate configs before a run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from cygnus.capacity.schema import (
    DEFAULT_COMPARATOR,
    ENVIRONMENT_STAGING,
    HARD_MAX_CONCURRENCY,
    HARD_MAX_DURATION_SECONDS,
    HARD_MAX_INJECTION_WINDOW_SECONDS,
    HARD_MAX_REQUESTS,
    HARD_MAX_TOTAL_BUDGET_SECONDS,
    INJECTION_TARGETS,
    METRICS,
    ROUTES,
    Comparator,
    InjectionTarget,
    MetricId,
    RouteId,
)


def _approved_ref(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    if len(normalized) > 512 or any(char.isspace() for char in normalized):
        raise ValueError(f"{label} must be a bounded, whitespace-free reference")
    return normalized


class CapacityApproval(BaseModel):
    """Deployment-owned CYG-144 authority for one capacity input set.

    References are opaque evidence identifiers. Their existence and matching
    environment bindings are verified by the production-input gate; this model
    prevents an unreferenced thresholds document from producing a certification
    report in the first place.
    """

    model_config = ConfigDict(extra="forbid")

    approval_ref: str
    thresholds_ref: str
    targets_ref: str

    @field_validator("approval_ref", "thresholds_ref", "targets_ref")
    @classmethod
    def _validate_ref(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "approval_ref")
        return _approved_ref(value, label=str(field_name))


class ThresholdInputError(ValueError):
    """Raised when required external threshold inputs are missing or invalid."""


class MetricThreshold(BaseModel):
    """One explicit pass number for one metric with its comparison direction."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0.0, description="Explicit deployment threshold.")
    comparator: Comparator | None = Field(
        default=None,
        description="lte for lower-is-better metrics; throughput defaults to gte.",
    )

    def resolved_comparator(self, metric: MetricId) -> Comparator:
        return self.comparator or DEFAULT_COMPARATOR.get(metric, "lte")


class RouteThresholds(BaseModel):
    """Required thresholds for every measured metric of one route."""

    model_config = ConfigDict(extra="forbid")

    p50_ms: MetricThreshold
    p95_ms: MetricThreshold
    p99_ms: MetricThreshold
    throughput_rps: MetricThreshold
    error_rate: MetricThreshold
    denial_rate: MetricThreshold
    retry_rate: MetricThreshold
    queue_age_seconds: MetricThreshold
    pool_saturation: MetricThreshold

    def threshold_for(self, metric: MetricId) -> MetricThreshold:
        return getattr(self, metric)


class FailureInjectionConfig(BaseModel):
    """Explicit, bounded, opt-in fault injection for recovery evidence."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Injection is opt-in; recovery evidence is required for PASS.",
    )
    route_targets: dict[RouteId, InjectionTarget] = Field(
        default_factory=dict,
        description="Which route exercises which dependency fault (all four targets required).",
    )
    duration_seconds: float = Field(
        default=5.0,
        ge=1.0,
        le=HARD_MAX_INJECTION_WINDOW_SECONDS,
        description="Bounded fault window per target.",
    )
    post_recovery_seconds: float = Field(
        default=3.0,
        ge=1.0,
        le=60.0,
        description="Bounded post-restore sampling window used for recovery evidence.",
    )
    max_recovery_seconds: float | None = Field(
        default=None,
        ge=0.1,
        le=3600.0,
        description="Required explicit recovery SLO when injection is enabled.",
    )

    @model_validator(mode="after")
    def _validate(self) -> "FailureInjectionConfig":
        if not self.enabled:
            return self
        if self.max_recovery_seconds is None:
            raise ValueError(
                "max_recovery_seconds is required when failure injection is enabled"
            )
        if not self.route_targets:
            raise ValueError(
                "route_targets are required when failure injection is enabled"
            )
        unknown_routes = set(self.route_targets) - set(ROUTES)
        if unknown_routes:
            raise ValueError(f"unknown route_targets keys: {sorted(unknown_routes)}")
        missing = set(INJECTION_TARGETS) - set(self.route_targets.values())
        if missing:
            raise ValueError(
                "route_targets must cover every injection target; "
                f"missing: {sorted(missing)}"
            )
        return self


class RouteLoadProfile(BaseModel):
    """Bounded per-route load shape; hard caps are enforced in schema.py."""

    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=4, ge=1, le=HARD_MAX_CONCURRENCY)
    duration_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=HARD_MAX_DURATION_SECONDS,
    )
    max_requests: int = Field(default=2000, ge=1, le=HARD_MAX_REQUESTS)


class LoadProfile(BaseModel):
    """Load shape for every route, with a bounded total budget."""

    model_config = ConfigDict(extra="forbid")

    routes: dict[RouteId, RouteLoadProfile]

    @model_validator(mode="after")
    def _validate(self) -> "LoadProfile":
        missing = set(ROUTES) - set(self.routes)
        extra = set(self.routes) - set(ROUTES)
        problems: list[str] = []
        if missing:
            problems.append(f"missing routes: {sorted(missing)}")
        if extra:
            problems.append(f"unknown routes: {sorted(extra)}")
        if problems:
            raise ValueError("; ".join(problems))
        budget = self.budget_seconds
        if budget > HARD_MAX_TOTAL_BUDGET_SECONDS:
            raise ValueError(
                f"total load budget {budget:g}s exceeds hard cap "
                f"{HARD_MAX_TOTAL_BUDGET_SECONDS:g}s"
            )
        return self

    @property
    def budget_seconds(self) -> float:
        return sum(profile.duration_seconds for profile in self.routes.values())


class CapacityThresholds(BaseModel):
    """Complete external input set for one capacity-gate run.

    Every field is required; there are no invented pass numbers and no
    runtime fallbacks. ``alert_rule_mappings`` binds every gated check to
    the alert rule the deployment owns (coordination contract with the
    alert-rule owner for CYG-142).
    """

    model_config = ConfigDict(extra="forbid")

    environment: Literal["staging"] = ENVIRONMENT_STAGING
    approval: CapacityApproval
    thresholds: dict[RouteId, RouteThresholds]
    alert_rule_mappings: dict[str, str]
    failure_injection: FailureInjectionConfig
    load_profile: LoadProfile

    @model_validator(mode="after")
    def _validate(self) -> "CapacityThresholds":
        missing_routes = set(ROUTES) - set(self.thresholds)
        extra_routes = set(self.thresholds) - set(ROUTES)
        problems: list[str] = []
        if missing_routes:
            problems.append(f"missing route thresholds: {sorted(missing_routes)}")
        if extra_routes:
            problems.append(f"unknown route thresholds: {sorted(extra_routes)}")

        expected_mappings = {
            f"{route}.{metric}" for route in ROUTES for metric in METRICS
        }
        mapping_missing = expected_mappings - set(self.alert_rule_mappings)
        mapping_extra = set(self.alert_rule_mappings) - expected_mappings
        if mapping_missing:
            problems.append(
                f"missing alert_rule_mappings keys: {sorted(mapping_missing)}"
            )
        if mapping_extra:
            problems.append(
                f"unknown alert_rule_mappings keys: {sorted(mapping_extra)}"
            )
        blank = sorted(
            key for key, value in self.alert_rule_mappings.items() if not value.strip()
        )
        if blank:
            problems.append(f"blank alert rule ids for: {blank}")

        if self.failure_injection.enabled:
            for route, _target in self.failure_injection.route_targets.items():
                duration = self.load_profile.routes[route].duration_seconds
                window = self.failure_injection.duration_seconds
                post = self.failure_injection.post_recovery_seconds
                required = 2.0 * (window + post)
                if duration < required:
                    problems.append(
                        f"route {route} duration {duration:g}s is too short for an "
                        f"injection window of {window:g}s plus {post:g}s of "
                        f"post-recovery observation (need >= {required:g}s)"
                    )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> "CapacityThresholds":
        """Load and validate a thresholds config; raise ThresholdInputError."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ThresholdInputError(
                f"cannot read thresholds file {path}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ThresholdInputError(
                f"thresholds file {path} must contain a JSON object"
            )
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise ThresholdInputError(f"invalid thresholds file {path}: {exc}") from exc

    def fingerprint(self) -> str:
        """Stable content hash binding a report to its exact inputs."""
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def threshold_schema() -> dict[str, Any]:
    """Machine-readable JSON Schema for the required capacity inputs."""
    return CapacityThresholds.model_json_schema()
