"""Span tracing — OpenTelemetry-compatible surface with graceful degradation.

- ``start_span(name, attributes=None)`` is a context manager yielding a span
  object with ``set_attribute`` / ``end`` and the standard ``__enter__``/
  ``__exit__`` contract, so callers can write OTel-shaped code without an SDK.
- When ``opentelemetry`` is importable AND an OTLP endpoint is configured, real
  OTel spans are emitted. Otherwise a lightweight in-process span context is
  used (still bounded, still correlated via the request ID) and
  ``cygnus_telemetry_failures_total`` records the degradation once per process
  so exporter unavailability is explicit, not silent.
- ``shutdown_telemetry()`` flushes/drains tracked spans and exporters; safe to
  call repeatedly and after exporters were never configured.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
import threading
import time
from typing import Any, Iterator, Optional

from cygnus.observability._config import ObservabilityConfig, configure_observability
from cygnus.observability._context import current_request_id
from cygnus.observability._metrics import (
    configure_registry,
    record_telemetry_failure,
)
from cygnus.observability._sanitize import (
    safe_metadata_key,
    sanitize_annotation,
    sanitize_label_value,
)

#: Resolved config cache — mirrors the metrics module's config.
_active_config: Optional[ObservabilityConfig] = None
_config_lock = threading.Lock()

#: Set once we attempted an OTel import so degradation is recorded once.
_otel_attempted = False
_otel_available = False
_degradation_recorded = False
_span_depth: ContextVar[int] = ContextVar("cygnus_span_depth", default=0)

_TRACER_PROVIDER = None  # lazily built OTel TracerProvider


def _resolve_config() -> ObservabilityConfig:
    global _active_config
    with _config_lock:
        if _active_config is None:
            _active_config = configure_observability()
        return _active_config


def _ensure_otel() -> bool:
    """Attempt lazy OTel import once. Returns availability."""
    global _otel_attempted, _otel_available, _degradation_recorded
    if _otel_attempted:
        return _otel_available
    _otel_attempted = True
    try:
        import opentelemetry  # noqa: F401
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.sdk.trace import TracerProvider  # noqa: F401

        _otel_available = True
    except Exception:  # noqa: BLE001 — optional dependency
        _otel_available = False
    if not _otel_available and not _degradation_recorded:
        _degradation_recorded = True
        record_telemetry_failure("otel_unavailable")
    return _otel_available


def _build_tracer():
    """Build (or reuse) an OTel tracer when an endpoint is configured."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER
    cfg = _resolve_config()
    if not cfg.otlp_endpoint:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": cfg.otlp_service_name,
                "service.version": "unknown",
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.otlp_endpoint))
        )
        trace.set_tracer_provider(provider)
        _TRACER_PROVIDER = provider
        return provider
    except Exception:  # noqa: BLE001 — exporter must not break the app
        record_telemetry_failure("otlp_exporter_init")
        return None


def _span_attributes(attributes: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Filter span attributes to bounded, secret-free scalar values."""
    if not attributes:
        return {}
    filtered: dict[str, Any] = {}
    for key, value in attributes.items():
        if key is None or len(filtered) >= 32:
            continue
        safe_key = safe_metadata_key(str(key))
        if safe_key is None:
            continue
        if isinstance(value, str):
            filtered[safe_key] = sanitize_annotation(value, max_length=256)
        elif isinstance(value, (int, float, bool)) or value is None:
            filtered[safe_key] = value
        else:
            # Lists/dicts can contain support content; never serialize them.
            continue
    return filtered


def _span_name(name: Any) -> str:
    """Return a bounded span operation name without request/support content."""
    normalized = sanitize_label_value(name, max_length=128)
    return normalized if normalized != "unknown" else "cygnus.operation"


class _NoopSpan:
    """In-process span fallback when OTel is unavailable/not configured."""

    __slots__ = ("name", "_started", "_ended", "_attributes")

    def __init__(self, name: str, attributes: Optional[dict[str, Any]]) -> None:
        self.name = _span_name(name)
        self._started = time.monotonic()
        self._ended = False
        self._attributes = dict(attributes or {})

    def set_attribute(self, key: str, value: Any) -> None:
        if self._ended:
            return
        self._attributes.update(_span_attributes({key: value}))

    def end(self) -> None:
        if not self._ended:
            self._ended = True

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.end()


@contextlib.contextmanager
def start_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Iterator[Any]:
    """Start a span; yields an OTel span when available, else a no-op span.

    Bounded attributes only (secrets filtered). Never raises: any exporter or
    SDK failure degrades into the telemetry-failure counter.
    """
    safe_name = _span_name(name)
    cfg = _resolve_config()
    if not cfg.telemetry_enabled:
        # Yield a no-op span so callers keep a uniform contract.
        yield _NoopSpan(safe_name, {})
        return

    filtered = _span_attributes(attributes)
    request_id = current_request_id()
    if request_id:
        filtered.setdefault("cygnus.correlation_id", request_id)

    otel = _ensure_otel()
    if otel and cfg.otlp_endpoint:
        provider = _build_tracer()
        if provider is not None:
            try:
                from opentelemetry import trace

                tracer = trace.get_tracer(cfg.otlp_service_name)
                with tracer.start_as_current_span(
                    safe_name, attributes=filtered
                ) as span:
                    yield span
                return
            except Exception:  # noqa: BLE001 — degrade, never raise
                record_telemetry_failure("otel_span_start")

    token = _span_depth.set(_span_depth.get() + 1)
    try:
        yield _NoopSpan(safe_name, filtered)
    finally:
        _span_depth.reset(token)


def shutdown_telemetry() -> None:
    """Gracefully drain tracked spans and exporters.

    Safe to call multiple times and when no exporter was configured. After
    shutdown, further span starts use the in-process fallback.
    """
    global _TRACER_PROVIDER
    provider = _TRACER_PROVIDER
    _TRACER_PROVIDER = None
    if provider is not None:
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001
            record_telemetry_failure("otel_shutdown")


def active_span_depth() -> int:
    """Number of active in-process spans in this context (test/ops helper)."""
    return _span_depth.get()


def apply_observability_config(config: ObservabilityConfig) -> None:
    """Apply a resolved config to both spans and metrics (startup hook)."""
    global _active_config
    with _config_lock:
        _active_config = config
    configure_registry(config)
