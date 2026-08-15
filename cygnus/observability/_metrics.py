"""Bounded metrics registry and RED-style record helpers.

Self-contained implementation: no prometheus_client dependency. The registry
holds counters, gauges, and histograms with sanitized, capped label sets and
renders Prometheus text format on demand. When telemetry is disabled or a
metric exceeds its series cap, the sample is dropped and
``cygnus_telemetry_failures_total`` increments instead of raising.

Cardinality control:
- every label value passes through ``sanitize_label_value`` (bounded length)
- every metric enforces ``max_series_per_metric`` distinct label combinations
- metric and label names are static constants below (never user-supplied)

Names follow the ``cygnus_`` prefix and the RED pattern
(request rate/errors/duration) plus dependency, queue, worker, provider,
delivery, governance, propagation, and telemetry-health families.
"""

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from cygnus.observability._config import (
    ObservabilityConfig,
)
from cygnus.observability._sanitize import (
    sanitize_identifier_label,
    sanitize_label_value,
)

_TelemetryFailure = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Metric:
    """One registered metric family."""

    name: str
    kind: str  # "counter" | "gauge" | "histogram"
    help: str
    label_names: tuple[str, ...] = ()
    buckets: tuple[float, ...] = ()
    #: Label names whose values must be plain snake_case identifiers from a
    #: bounded vocabulary (see ``sanitize_identifier_label``). Use for labels
    #: that could carry user-adjacent content (e.g. MCP tool names) so raw
    #: tool/query strings never reach the exposition.
    identifier_labels: frozenset[str] = frozenset()


class _SeriesStore:
    """Thread-safe label-combination → value store with a series cap."""

    __slots__ = ("_data", "_lock", "_max_series", "_overflow")

    def __init__(self, max_series: int) -> None:
        self._data: "OrderedDict[tuple[str, ...], float]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_series = max_series
        self._overflow = 0

    def _ensure(self, labels: tuple[str, ...]) -> bool:
        """Return True when the label combo may be recorded."""
        if labels in self._data:
            return True
        if len(self._data) < self._max_series:
            self._data[labels] = 0.0
            return True
        self._overflow += 1
        return False

    def add(self, labels: tuple[str, ...], value: float) -> None:
        with self._lock:
            if self._ensure(labels):
                self._data[labels] = self._data.get(labels, 0.0) + value

    def set(self, labels: tuple[str, ...], value: float) -> None:
        with self._lock:
            if self._ensure(labels):
                self._data[labels] = value

    def observe(
        self, labels: tuple[str, ...], value: float, buckets: tuple[float, ...]
    ) -> None:
        with self._lock:
            # A Prometheus histogram always has an explicit +Inf bucket.  Do
            # not create a bare ``metric{labels}`` sample: that is not a valid
            # histogram series and wastes the bounded series budget.
            tails = tuple(buckets) + (float("inf"),)
            required = len(tails) + 2  # buckets + _sum + _count
            existing = any(
                key[: len(labels)] == labels and len(key) > len(labels)
                for key in self._data
            )
            if not existing and len(self._data) + required > self._max_series:
                self._overflow += 1
                return
            for bucket in tails:
                tail = "+Inf" if math.isinf(bucket) else f"{bucket:g}"
                key = labels + (tail,)
                if key in self._data:
                    if value <= bucket:
                        self._data[key] += 1.0
                else:
                    self._data[key] = 1.0 if value <= bucket else 0.0
            sum_key = labels + ("_sum",)
            count_key = labels + ("_count",)
            self._data[sum_key] = self._data.get(sum_key, 0.0) + value
            self._data[count_key] = self._data.get(count_key, 0.0) + 1.0

    def overflow(self) -> int:
        with self._lock:
            return self._overflow

    def snapshot(self) -> dict[tuple[str, ...], float]:
        with self._lock:
            return dict(self._data)


class MetricsRegistry:
    """Bounded metric registry with explicit degradation."""

    def __init__(self, config: Optional[ObservabilityConfig] = None) -> None:
        cfg = config or ObservabilityConfig()
        self._config = cfg
        self._lock = threading.Lock()
        self._metrics: dict[str, Metric] = {}
        self._stores: dict[str, _SeriesStore] = {}
        self._failure_count = 0

    # -- registration ----------------------------------------------------
    def register(self, metric: Metric) -> None:
        with self._lock:
            if metric.name in self._metrics:
                return
            self._metrics[metric.name] = metric
            self._stores[metric.name] = _SeriesStore(
                cfg_max_series(metric, self._config.max_series_per_metric)
            )

    def _store(self, name: str) -> _SeriesStore:
        with self._lock:
            store = self._stores.get(name)
        if store is None:
            raise KeyError(f"metric not registered: {name}")
        return store

    # -- degradation -----------------------------------------------------
    def record_telemetry_failure(self, component: str) -> None:
        """Increment the local telemetry-failure counter (never raises)."""
        label = sanitize_label_value(
            component, max_length=self._config.max_label_length
        )
        self._failure_count += 1
        try:
            store = self._store("cygnus_telemetry_failures_total")
            store.add((label,), 1.0)
        except KeyError:
            pass

    # -- record helpers --------------------------------------------------
    def _labels(self, metric: Metric, values: Mapping[str, object]) -> tuple[str, ...]:
        labels: list[str] = []
        for name in metric.label_names:
            value = values.get(name)
            if name in metric.identifier_labels:
                labels.append(sanitize_identifier_label(value))
            else:
                labels.append(
                    sanitize_label_value(
                        value, max_length=self._config.max_label_length
                    )
                )
        return tuple(labels)

    def inc(
        self,
        name: str,
        values: Optional[Mapping[str, object]] = None,
        amount: float = 1.0,
    ) -> None:
        metric = self._metrics[name]
        labels = self._labels(metric, values or {})
        self._store(name).add(labels, amount)

    def set(
        self,
        name: str,
        value: float,
        values: Optional[Mapping[str, object]] = None,
    ) -> None:
        metric = self._metrics[name]
        labels = self._labels(metric, values or {})
        self._store(name).set(labels, float(value))

    def observe(
        self,
        name: str,
        value: float,
        values: Optional[Mapping[str, object]] = None,
    ) -> None:
        metric = self._metrics[name]
        if metric.kind != "histogram":
            raise ValueError(f"observe() requires a histogram metric: {name}")
        labels = self._labels(metric, values or {})
        self._store(name).observe(labels, float(value), metric.buckets)

    # -- render ----------------------------------------------------------
    def render(self, enabled: bool = True) -> str:
        """Render Prometheus text format. Empty string when disabled."""
        if not enabled:
            return ""
        lines: list[str] = []
        for name in sorted(self._metrics):
            metric = self._metrics[name]
            lines.append(f"# HELP {name} {metric.help}")
            lines.append(f"# TYPE {name} {metric.kind}")
            store = self._stores[name]
            items = sorted(
                store.snapshot().items(),
                key=lambda kv: _series_sort_key(metric.label_names, kv[0], metric.kind),
            )
            for labels, value in items:
                rendered = _render_series(name, metric.label_names, labels, value)
                if rendered:
                    lines.append(rendered)
        if self._failure_count:
            lines.append(
                "# HELP cygnus_telemetry_failures_total "
                "Total telemetry write/degradation events."
            )
            lines.append("# TYPE cygnus_telemetry_failures_total counter")
            lines.append(f"cygnus_telemetry_failures_total {self._failure_count}")
        return "\n".join(lines) + "\n" if lines else ""

    def metric_names(self) -> list[str]:
        """Registered metric family names.

        Histogram families also register their Prometheus series suffixes
        (``_bucket`` / ``_sum`` / ``_count``) so alert expressions that
        reference the exact series names validate against the registry.
        """
        names: set[str] = set()
        for metric in self._metrics.values():
            names.add(metric.name)
            if metric.kind == "histogram":
                names.add(f"{metric.name}_bucket")
                names.add(f"{metric.name}_sum")
                names.add(f"{metric.name}_count")
        return sorted(names)


def cfg_max_series(metric: Metric, configured: int) -> int:
    """Per-metric series cap. Histograms multiply by bucket+sentinel count."""
    if metric.kind == "histogram":
        multiplier = len(metric.buckets) + 2
        return max(configured // multiplier, 8)
    return configured


def _series_sort_key(
    label_names: tuple[str, ...], labels: tuple[str, ...], kind: str
) -> tuple:
    """Sort histogram series by numeric ``le`` value, then sentinels."""
    if kind != "histogram" or len(labels) <= len(label_names):
        return (labels, 0)
    base = labels[: len(label_names)]
    tail = labels[len(label_names) :][0]
    if tail == "_sum":
        return (base, float("inf") + 1.0)
    if tail == "_count":
        return (base, float("inf") + 2.0)
    if tail == "+Inf":
        return (base, float("inf"))
    try:
        return (base, float(tail))
    except ValueError:
        return (base, float("inf") + 3.0)


def _render_series(
    name: str,
    label_names: tuple[str, ...],
    labels: tuple[str, ...],
    value: float,
) -> str:
    """Render one series line, splitting histogram bucket/sentinel series."""
    if label_names:
        joined = ",".join(
            f'{label_names[i]}="{labels[i]}"' for i in range(len(label_names))
        )
        # Histogram store appends bucket/sentinel keys at the tail of labels.
        tail = labels[len(label_names) :]
        if tail:
            sentinel = tail[0]
            if sentinel == "_sum":
                return f"{name}_sum{{{joined}}} {value:g}"
            if sentinel == "_count":
                return f"{name}_count{{{joined}}} {value:g}"
            return f'{name}_bucket{{{joined},le="{sentinel}"}} {value:g}'
        return f"{name}{{{joined}}} {value:g}"
    if value != int(value) or name.endswith("_total"):
        return f"{name} {value:g}"
    return f"{name} {value:g}"


# ---------------------------------------------------------------------------
# Shared registry instance + bounded record_* facade
# ---------------------------------------------------------------------------

_config = ObservabilityConfig()
_registry = MetricsRegistry(_config)


def reset_registry_for_tests(
    config: Optional[ObservabilityConfig] = None,
) -> None:
    """Replace the module registry (test isolation only)."""
    global _config, _registry
    _config = config or ObservabilityConfig()
    _registry = MetricsRegistry(_config)
    _register_all()


def configure_registry(config: ObservabilityConfig) -> None:
    """Apply a resolved config to the shared registry."""
    global _config
    _config = config
    _registry._config = config
    for metric in _registry._metrics.values():
        _registry._stores[metric.name] = _SeriesStore(
            cfg_max_series(metric, config.max_series_per_metric)
        )


def _register_all() -> None:
    _registry.register(
        Metric(
            "cygnus_http_requests_total",
            "counter",
            "HTTP requests by route/method/status (RED).",
            ("route", "method", "status"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_http_request_duration_seconds",
            "histogram",
            "HTTP request duration by route/method.",
            ("route", "method"),
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
    )
    _registry.register(
        Metric(
            "cygnus_mcp_tool_calls_total",
            "counter",
            "MCP tool executions by tool/status.",
            ("tool", "status"),
            identifier_labels=frozenset({"tool"}),
        )
    )
    _registry.register(
        Metric(
            "cygnus_mcp_tool_duration_seconds",
            "histogram",
            "MCP tool duration by tool.",
            ("tool",),
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            identifier_labels=frozenset({"tool"}),
        )
    )
    _registry.register(
        Metric(
            "cygnus_mcp_tool_deadline_exceeded_total",
            "counter",
            "MCP tool executions that exceeded their deadline.",
            ("tool",),
            identifier_labels=frozenset({"tool"}),
        )
    )
    _registry.register(
        Metric(
            "cygnus_db_pool_connections",
            "gauge",
            "DB pool connections by state (checked_out|checked_in|overflow).",
            ("pool", "state"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_db_pool_errors_total",
            "counter",
            "DB pool operational errors by pool.",
            ("pool",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_queue_jobs_total",
            "counter",
            "Queue jobs observed by queue/terminal state.",
            ("queue", "state"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_queue_job_age_seconds",
            "gauge",
            "Oldest observed queue job age by queue.",
            ("queue",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_queue_attempts_total",
            "counter",
            "Queue job attempts by queue.",
            ("queue",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_worker_heartbeat",
            "gauge",
            "Worker heartbeat freshness by role (1 fresh, 0 stale).",
            ("role",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_worker_draining_total",
            "counter",
            "Worker drain/shutdown events by role.",
            ("role",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_provider_calls_total",
            "counter",
            "Provider (LLM/storage) calls by provider/model/operation/status.",
            ("provider", "model", "operation", "status"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_provider_duration_seconds",
            "histogram",
            "Provider call duration by provider/model/operation.",
            ("provider", "model", "operation"),
            buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
        )
    )
    _registry.register(
        Metric(
            "cygnus_provider_tokens_total",
            "counter",
            "Provider token usage by provider/model/operation/direction.",
            ("provider", "model", "operation", "direction"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_delivery_calls_total",
            "counter",
            "Outbound delivery calls by channel/status.",
            ("channel", "status"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_delivery_duration_seconds",
            "histogram",
            "Outbound delivery duration by channel.",
            ("channel",),
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
        )
    )
    _registry.register(
        Metric(
            "cygnus_governance_route_terminal_total",
            "counter",
            "Governance route terminal events by route kind/reason.",
            ("route_kind", "reason"),
        )
    )
    _registry.register(
        Metric(
            "cygnus_propagation_mismatch_total",
            "counter",
            "Propagation/publish mismatch or correlation loss events by kind.",
            ("kind",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_capacity_gate_breach",
            "gauge",
            "Approved deployment capacity threshold breach (1 breached).",
            (
                "route",
                "metric",
                "approval_ref",
                "thresholds_ref",
                "targets_ref",
                "thresholds_fingerprint",
            ),
        )
    )
    _registry.register(
        Metric(
            "cygnus_stale_evidence",
            "gauge",
            "Count of stale evidence rows by kind.",
            ("kind",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_readiness_dependency",
            "gauge",
            "Readiness dependency state (1 ready, 0 failed).",
            ("dependency",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_telemetry_failures_total",
            "counter",
            "Telemetry write/degradation events by component.",
            ("component",),
        )
    )
    _registry.register(
        Metric(
            "cygnus_release_info",
            "gauge",
            "Runtime release identity (always 1 when present).",
            ("release", "environment", "commit_sha"),
        )
    )


_register_all()


def _enabled() -> bool:
    return _config.telemetry_enabled


def record_telemetry_failure(component: str) -> None:
    """Record a telemetry write/degradation event (never raises).

    Exposed for spans and runtime-shell callers; delegates to the registry's
    bounded failure counter.
    """
    _registry.record_telemetry_failure(component)


def _safe(fn: Callable[[], None]) -> None:
    """Run a record helper, degrading to a failure counter on error."""
    try:
        if _enabled():
            fn()
    except Exception:  # noqa: BLE001 — instrumentation must never raise
        _registry.record_telemetry_failure("record_helper")


def _route_label(route: object) -> str:
    """Normalize a framework route template and reject query/body strings."""
    raw = str(route or "").strip()
    if not raw or "?" in raw or "@" in raw:
        return "unknown"
    return sanitize_label_value(raw, max_length=128)


def _duration_seconds(duration_ms: object) -> float:
    if not isinstance(duration_ms, (int, float, str)):
        return 0.0
    try:
        value = float(duration_ms)
    except (TypeError, ValueError):
        return 0.0
    return value / 1000.0 if math.isfinite(value) and value >= 0 else 0.0


def _status_label(status: object) -> str:
    if not isinstance(status, (int, float, str)):
        return sanitize_label_value(status, max_length=32)
    try:
        value = int(status)
    except (TypeError, ValueError):
        return sanitize_label_value(status, max_length=32)
    return str(value) if 100 <= value <= 599 else "unknown"


def record_http_request(
    *, route: str, method: str, status: int, duration_ms: float
) -> None:
    """Record one HTTP request (RED) using only route-template metadata."""

    def _record() -> None:
        safe_route = _route_label(route)
        safe_method = sanitize_label_value(method, max_length=16)
        values = {
            "route": safe_route,
            "method": safe_method,
            "status": _status_label(status),
        }
        _registry.inc("cygnus_http_requests_total", values)
        _registry.observe(
            "cygnus_http_request_duration_seconds",
            _duration_seconds(duration_ms),
            {"route": safe_route, "method": safe_method},
        )

    _safe(_record)


def record_mcp_tool(
    *,
    tool: str,
    status: str,
    duration_ms: float,
    deadline_exceeded: bool = False,
) -> None:
    """Record one MCP tool execution with a bounded identifier label."""

    def _record() -> None:
        safe_tool = sanitize_identifier_label(tool)
        safe_status = sanitize_label_value(status, max_length=32)
        _registry.inc(
            "cygnus_mcp_tool_calls_total", {"tool": safe_tool, "status": safe_status}
        )
        _registry.observe(
            "cygnus_mcp_tool_duration_seconds",
            _duration_seconds(duration_ms),
            {"tool": safe_tool},
        )
        if deadline_exceeded:
            _registry.inc(
                "cygnus_mcp_tool_deadline_exceeded_total", {"tool": safe_tool}
            )

    _safe(_record)


def record_db_pool(
    *,
    pool: str,
    checked_out: Optional[float] = None,
    checked_in: Optional[float] = None,
    overflow: Optional[float] = None,
    errors: int = 0,
) -> None:
    """Record DB pool utilization and errors."""

    def _record() -> None:
        base = {"pool": pool}
        if checked_out is not None:
            _registry.set(
                "cygnus_db_pool_connections",
                checked_out,
                {**base, "state": "checked_out"},
            )
        if checked_in is not None:
            _registry.set(
                "cygnus_db_pool_connections",
                checked_in,
                {**base, "state": "checked_in"},
            )
        if overflow is not None:
            _registry.set(
                "cygnus_db_pool_connections",
                overflow,
                {**base, "state": "overflow"},
            )
        if errors:
            _registry.inc("cygnus_db_pool_errors_total", base, amount=float(errors))

    _safe(_record)


def record_queue(
    *,
    queue: str,
    terminal_state: Optional[str] = None,
    age_seconds: Optional[float] = None,
    attempts: int = 0,
) -> None:
    """Record one queue observation: terminal state, age, attempts."""

    def _record() -> None:
        base = {"queue": queue}
        if terminal_state:
            _registry.inc("cygnus_queue_jobs_total", {**base, "state": terminal_state})
        if age_seconds is not None:
            _registry.set("cygnus_queue_job_age_seconds", age_seconds, base)
        if attempts:
            _registry.inc("cygnus_queue_attempts_total", base, amount=float(attempts))

    _safe(_record)


def record_worker_heartbeat(*, role: str, fresh: bool) -> None:
    """Record worker heartbeat freshness (1 fresh / 0 stale)."""

    def _record() -> None:
        _registry.set("cygnus_worker_heartbeat", 1.0 if fresh else 0.0, {"role": role})

    _safe(_record)


def record_worker_drain(*, role: str) -> None:
    """Record a worker drain/shutdown event."""

    def _record() -> None:
        _registry.inc("cygnus_worker_draining_total", {"role": role})

    _safe(_record)


def record_provider(
    *,
    provider: str,
    operation: str,
    status: str,
    duration_ms: float,
    model: str | None = None,
    tokens: int | float | None = None,
    input_tokens: int | float | None = None,
    output_tokens: int | float | None = None,
) -> None:
    """Record one provider call, latency, and optional token usage."""

    def _record() -> None:
        safe_provider = sanitize_identifier_label(provider)
        safe_model = sanitize_label_value(model, max_length=128)
        safe_operation = sanitize_identifier_label(operation)
        safe_status = sanitize_identifier_label(status)
        values = {
            "provider": safe_provider,
            "model": safe_model,
            "operation": safe_operation,
            "status": safe_status,
        }
        _registry.inc("cygnus_provider_calls_total", values)
        _registry.observe(
            "cygnus_provider_duration_seconds",
            _duration_seconds(duration_ms),
            {
                "provider": safe_provider,
                "model": safe_model,
                "operation": safe_operation,
            },
        )
        token_values = {
            "input": input_tokens,
            "output": output_tokens,
            "total": tokens,
        }
        if tokens is None and (input_tokens is not None or output_tokens is not None):
            token_values["total"] = sum(
                float(value or 0.0) for value in (input_tokens, output_tokens)
            )
        for direction, amount in token_values.items():
            if amount is None:
                continue
            numeric = float(amount)
            if not math.isfinite(numeric) or numeric < 0:
                continue
            _registry.inc(
                "cygnus_provider_tokens_total",
                {
                    "provider": safe_provider,
                    "model": safe_model,
                    "operation": safe_operation,
                    "direction": direction,
                },
                amount=numeric,
            )

    _safe(_record)


def record_delivery(
    *,
    channel: str,
    status: str,
    duration_ms: float,
) -> None:
    """Record one outbound delivery attempt without destination payloads."""

    def _record() -> None:
        safe_channel = sanitize_label_value(channel, max_length=64)
        safe_status = sanitize_label_value(status, max_length=32)
        _registry.inc(
            "cygnus_delivery_calls_total",
            {"channel": safe_channel, "status": safe_status},
        )
        _registry.observe(
            "cygnus_delivery_duration_seconds",
            _duration_seconds(duration_ms),
            {"channel": safe_channel},
        )

    _safe(_record)


def record_governance_route(*, route_kind: str, reason: str) -> None:
    """Record one governance terminal state and bounded terminal reason."""

    def _record() -> None:
        _registry.inc(
            "cygnus_governance_route_terminal_total",
            {
                "route_kind": sanitize_identifier_label(route_kind),
                "reason": sanitize_label_value(reason, max_length=80),
            },
        )

    _safe(_record)


def record_propagation_mismatch(*, kind: str, count: int = 1) -> None:
    """Record publish/propagation mismatch or correlation-loss events."""

    def _record() -> None:
        numeric = max(0, int(count))
        if numeric:
            _registry.inc(
                "cygnus_propagation_mismatch_total",
                {"kind": sanitize_identifier_label(kind)},
                amount=float(numeric),
            )

    _safe(_record)


def record_capacity_gate_breach(
    *,
    route: str,
    metric: str,
    breached: bool,
    approval_ref: str | None = None,
    thresholds_ref: str | None = None,
    targets_ref: str | None = None,
    thresholds_fingerprint: str | None = None,
) -> None:
    """Expose an approved deployment-threshold breach without pass values."""

    def _record() -> None:
        _registry.set(
            "cygnus_capacity_gate_breach",
            1.0 if breached else 0.0,
            {
                "route": sanitize_identifier_label(route),
                "metric": sanitize_identifier_label(metric),
                "approval_ref": sanitize_label_value(approval_ref, max_length=128),
                "thresholds_ref": sanitize_label_value(thresholds_ref, max_length=128),
                "targets_ref": sanitize_label_value(targets_ref, max_length=128),
                "thresholds_fingerprint": sanitize_label_value(
                    thresholds_fingerprint,
                    max_length=64,
                ),
            },
        )

    _safe(_record)


def record_stale_evidence(*, kind: str, count: int) -> None:
    """Record the current stale-evidence gauge value for a kind."""

    def _record() -> None:
        _registry.set("cygnus_stale_evidence", float(count), {"kind": kind})

    _safe(_record)


def record_readiness_dependency(*, dependency: str, status: str) -> None:
    """Record one readiness probe outcome (status: ready|failed).

    Contract consumed by ReadinessOps: keyword args ``dependency: str`` and
    ``status: str`` in {"ready", "failed"}.
    """

    def _record() -> None:
        ready = 1.0 if status == "ready" else 0.0
        _registry.set("cygnus_readiness_dependency", ready, {"dependency": dependency})

    _safe(_record)


def record_release_info(*, release: str, environment: str, commit_sha: str) -> None:
    """Record the runtime release identity as a gauge (value 1)."""

    def _record() -> None:
        _registry.set(
            "cygnus_release_info",
            1.0,
            {
                "release": release,
                "environment": environment,
                "commit_sha": commit_sha,
            },
        )

    _safe(_record)


def render_prometheus_metrics(*, enabled: Optional[bool] = None) -> str:
    """Render the full Prometheus text exposition.

    ``enabled`` defaults to the current config's prometheus flag; pass True
    explicitly to force render regardless (used by the /metrics endpoint after
    its own gate).
    """
    effective = _config.prometheus_metrics_enabled if enabled is None else enabled
    if not effective:
        return ""
    return _registry.render(enabled=True)
