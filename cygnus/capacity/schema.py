"""Stable vocabulary for the Cygnus production capacity load gate (CYG-142).

The gate vocabulary is deliberately frozen: routes, metrics, injection
targets, and verdict statuses are string constants so machine-readable
reports stay comparable and replayable across releases. Nothing in this
module carries a numeric pass value -- every threshold arrives as an
explicit external deployment input (see ``cygnus.capacity.thresholds``).
"""

from __future__ import annotations

from typing import Literal

SUITE_NAME = "cygnus-production-capacity-gate"
APP_NAME = "cygnus"
ENVIRONMENT_STAGING: Literal["staging"] = "staging"

RouteId = Literal["publish", "ticket_import", "ingestion", "worker", "query"]
ROUTES: tuple[RouteId, ...] = (
    "publish",
    "ticket_import",
    "ingestion",
    "worker",
    "query",
)

ROUTE_LABELS: dict[str, str] = {
    "publish": "review/publish",
    "ticket_import": "ticket import",
    "ingestion": "source ingestion",
    "worker": "worker jobs",
    "query": "retrieval query",
}

MetricId = Literal[
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "throughput_rps",
    "error_rate",
    "denial_rate",
    "retry_rate",
    "queue_age_seconds",
    "pool_saturation",
]
METRICS: tuple[MetricId, ...] = (
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "throughput_rps",
    "error_rate",
    "denial_rate",
    "retry_rate",
    "queue_age_seconds",
    "pool_saturation",
)

METRIC_LABELS: dict[str, str] = {
    "p50_ms": "median latency (ms)",
    "p95_ms": "95th percentile latency (ms)",
    "p99_ms": "99th percentile latency (ms)",
    "throughput_rps": "completed requests per second",
    "error_rate": "failed request fraction",
    "denial_rate": "denied request fraction",
    "retry_rate": "retried request fraction",
    "queue_age_seconds": "mean pending queue age (s)",
    "pool_saturation": "mean pool utilization fraction",
}

Comparator = Literal["lte", "gte"]
# Lower is better for latency/rates/saturation; throughput is higher-is-better.
DEFAULT_COMPARATOR: dict[MetricId, Comparator] = {"throughput_rps": "gte"}

Outcome = Literal["success", "error", "denied", "retry"]
OUTCOMES: tuple[Outcome, ...] = ("success", "error", "denied", "retry")

InjectionTarget = Literal["db", "queue", "tool", "provider"]
INJECTION_TARGETS: tuple[InjectionTarget, ...] = ("db", "queue", "tool", "provider")

GateStatus = Literal["PASS", "FAIL", "NOT_CERTIFIED"]
GATE_PASS: GateStatus = "PASS"
GATE_FAIL: GateStatus = "FAIL"
GATE_NOT_CERTIFIED: GateStatus = "NOT_CERTIFIED"

# --- Machine-readable verdict reasons (blocked / not-certified / failure) ---
ENVIRONMENT_NOT_STAGING = "environment_not_staging"
THRESHOLDS_MISSING = "thresholds_missing"
RELEASE_REFS_MISSING = "release_refs_missing"
RUN_INPUTS_MISSING = "run_inputs_missing"
APPROVAL_REFS_MISSING = "approval_refs_missing"
APPROVAL_REFS_MISMATCH = "approval_refs_mismatch"
ROUTE_NOT_MEASURED = "route_not_measured"
INJECTION_NOT_EXERCISED = "injection_not_exercised"
THRESHOLD_VIOLATION = "threshold_violation"
RECOVERY_NOT_OBSERVED = "recovery_not_observed"

# Hard staging-safety caps. These bound the gate even when a deployment
# config asks for more; a profile exceeding them is a blocked input, never a
# silently relaxed run.
HARD_MAX_CONCURRENCY = 32
HARD_MAX_DURATION_SECONDS = 300.0
HARD_MAX_REQUESTS = 100_000
HARD_MAX_TOTAL_BUDGET_SECONDS = 900.0
HARD_MAX_INJECTION_WINDOW_SECONDS = 30.0
