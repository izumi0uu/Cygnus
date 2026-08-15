"""Cygnus observability primitives for Production V1 (CYG-142).

Ownership:
- this package owns request/trace correlation context, bounded RED metrics,
  sanitized exception recording, runtime release identity, and machine-readable
  alert-rule configuration
- it is a bounded instrumentation surface, NOT a runtime app-shell owner:
  HTTP/MCP/ARQ/governance/outbound wiring stays in the runtime shell and calls
  these helpers through lazy, exception-swallowed integration points
- instrumentation must never change product responses; failures increment a
  local telemetry-failure counter instead of raising

Public API (stable contract consumed by the runtime shell, ToolRuntime,
DeliveryReceipt, SecurityBaseline, and ReadinessOps):
- ``current_request_id()`` / ``current_traceparent()`` — process-scoped context
- ``request_correlation(request_id)`` — context manager binding a request scope
- ``outbound_trace_headers()`` — headers to attach to outbound HTTP calls
- ``start_span(name, attributes=None)`` — OTel-compatible span context manager
- ``runtime_identity()`` — sanitized release/commit/image/env/deployment/Alembic head
- ``configure_observability(settings=None, **overrides)`` — env-driven config
- ``render_prometheus_metrics()`` / ``prometheus_metrics_endpoint()`` — scrape surface
- ``record_*`` helpers — bounded counters/gauges/histograms (RED + dependencies)
- ``sanitize_error(exc)`` — exception string with secrets/values redacted
- ``shutdown_telemetry()`` — graceful drain of tracked spans and exporters

Design constraints:
- no hard dependency on opentelemetry/prometheus_client: the metrics registry is
  self-contained and OTel import is lazy and optional, so telemetry degrades
  explicitly when exporters are unavailable
- bounded cardinality: every label value is sanitized/truncated and per-metric
  series are capped; over-limit samples drop into ``cygnus_telemetry_failures_total``
- sensitive payloads never appear: only bounded sanitized labels and counts
"""

from cygnus.observability._config import (
    DEFAULT_MAX_LABEL_LENGTH,
    DEFAULT_MAX_SERIES_PER_METRIC,
    ObservabilityConfig,
    configure_observability,
)
from cygnus.observability._context import (
    current_request_id,
    current_traceparent,
    outbound_trace_headers,
    request_correlation,
    resolve_request_id_header,
)
from cygnus.observability._http import (
    prometheus_metrics_endpoint,
    record_http_request,
)
from cygnus.observability._identity import (
    EXPECTED_ALEMBIC_HEAD_ENV,
    runtime_identity,
)
from cygnus.observability._metrics import (
    record_capacity_gate_breach,
    record_db_pool,
    record_delivery,
    record_governance_route,
    record_mcp_tool,
    record_propagation_mismatch,
    record_provider,
    record_queue,
    record_readiness_dependency,
    record_release_info,
    record_stale_evidence,
    record_telemetry_failure,
    record_worker_drain,
    record_worker_heartbeat,
    render_prometheus_metrics,
)
from cygnus.observability._sanitize import sanitize_error
from cygnus.observability._logging import emit_structured_log, structured_log_fields
from cygnus.observability._spans import shutdown_telemetry, start_span


__all__ = [
    "DEFAULT_MAX_LABEL_LENGTH",
    "DEFAULT_MAX_SERIES_PER_METRIC",
    "EXPECTED_ALEMBIC_HEAD_ENV",
    "ObservabilityConfig",
    "configure_observability",
    "current_request_id",
    "current_traceparent",
    "emit_structured_log",
    "outbound_trace_headers",
    "prometheus_metrics_endpoint",
    "record_capacity_gate_breach",
    "record_db_pool",
    "record_delivery",
    "record_governance_route",
    "record_http_request",
    "record_mcp_tool",
    "record_propagation_mismatch",
    "record_provider",
    "record_queue",
    "record_readiness_dependency",
    "record_release_info",
    "record_stale_evidence",
    "record_telemetry_failure",
    "record_worker_drain",
    "record_worker_heartbeat",
    "render_prometheus_metrics",
    "request_correlation",
    "resolve_request_id_header",
    "runtime_identity",
    "sanitize_error",
    "shutdown_telemetry",
    "start_span",
    "structured_log_fields",
]
