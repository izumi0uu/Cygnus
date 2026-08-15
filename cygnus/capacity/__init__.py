"""Cygnus production capacity load gate (CYG-142).

A staging-safe, bounded load gate covering publish, ticket import,
ingestion, worker, and query routes, with opt-in DB/queue/tool/provider
fault injection. Every pass number is a required external deployment input
(``cygnus.capacity.thresholds``); the gate emits a machine-readable
PASS/FAIL/NOT_CERTIFIED report bound to release/app/config/evidence refs
and replayable from recorded samples (``cygnus.capacity.gate``).
"""

from cygnus.capacity.gate import build_blocked_report, build_route_result, run_load_gate
from cygnus.capacity.load import PhaseResult, RouteTarget, run_route_phase
from cygnus.capacity.metrics import RouteSample, SummaryMetrics, summarize_samples
from cygnus.capacity.report import (
    ConfigRefs,
    EvidenceRefs,
    InjectionReport,
    LoadGateReport,
    MetricCheck,
    ReleaseRefs,
    RouteResult,
)
from cygnus.capacity.schema import (
    GATE_FAIL,
    GATE_NOT_CERTIFIED,
    GATE_PASS,
    INJECTION_TARGETS,
    METRICS,
    ROUTES,
    SUITE_NAME,
)
from cygnus.capacity.thresholds import (
    CapacityThresholds,
    ThresholdInputError,
    threshold_schema,
)

__all__ = [
    "CapacityThresholds",
    "ConfigRefs",
    "EvidenceRefs",
    "GATE_FAIL",
    "GATE_NOT_CERTIFIED",
    "GATE_PASS",
    "INJECTION_TARGETS",
    "InjectionReport",
    "LoadGateReport",
    "METRICS",
    "MetricCheck",
    "PhaseResult",
    "ROUTES",
    "ReleaseRefs",
    "RouteResult",
    "RouteSample",
    "RouteTarget",
    "SUITE_NAME",
    "SummaryMetrics",
    "ThresholdInputError",
    "build_blocked_report",
    "build_route_result",
    "run_load_gate",
    "run_route_phase",
    "summarize_samples",
    "threshold_schema",
]
