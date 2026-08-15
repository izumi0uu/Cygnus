"""Secret-safe structured log fields for Cygnus runtime surfaces.

The application uses Loguru today, but the field contract lives here so HTTP,
MCP, workers, and governance code cannot drift into ad-hoc payload logging.
Only bounded scalar metadata is emitted; request/support content, credentials,
and exception messages are normalized before they reach a logger sink.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from cygnus.observability._context import current_request_id, current_traceparent
from cygnus.observability._sanitize import (
    safe_metadata_key,
    sanitize_annotation,
    sanitize_error,
    sanitize_identifier_label,
    sanitize_label_value,
)

_REQUIRED_FIELDS = (
    "correlation_id",
    "traceparent",
    "route",
    "status",
    "duration_ms",
    "actor_class",
    "job_id",
    "command_id",
    "terminal_reason",
)


def _bounded_scalar(
    value: Any, *, max_length: int = 128
) -> str | int | float | bool | None:
    """Return a safe scalar suitable for a structured log field."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return sanitize_label_value(value, max_length=max_length)


def structured_log_fields(
    *,
    event: str,
    route: Any = None,
    status: Any = None,
    duration_ms: Any = None,
    actor_class: Any = None,
    job_id: Any = None,
    command_id: Any = None,
    terminal_reason: Any = None,
    error: BaseException | str | None = None,
    correlation_id: Any = None,
    traceparent: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the canonical, payload-free structured log context.

    Required operational fields are present even when unavailable (``None``),
    which makes log queries stable across HTTP/MCP/job events.  ``route`` must
    be a route template supplied by the framework; callers must never pass a
    raw query string or request body.
    """
    effective_correlation = correlation_id or current_request_id()
    effective_traceparent = traceparent or current_traceparent()
    if isinstance(error, BaseException):
        safe_error: str | None = sanitize_error(error)
    elif error is None:
        safe_error = None
    else:
        safe_error = sanitize_annotation(error, max_length=512)

    fields: dict[str, Any] = {
        "event": sanitize_identifier_label(event),
        "correlation_id": (
            sanitize_label_value(effective_correlation, max_length=64)
            if effective_correlation
            else None
        ),
        "traceparent": (
            sanitize_label_value(effective_traceparent, max_length=64)
            if effective_traceparent
            else None
        ),
        "route": sanitize_label_value(route, max_length=128),
        "status": sanitize_label_value(status, max_length=64),
        "duration_ms": _bounded_scalar(duration_ms, max_length=32),
        "actor_class": sanitize_identifier_label(actor_class),
        "job_id": _bounded_scalar(job_id),
        "command_id": _bounded_scalar(command_id),
        "terminal_reason": sanitize_label_value(terminal_reason, max_length=128),
        "error": safe_error,
    }
    # Keep the required key set stable while allowing explicitly named scalar
    # dimensions such as method, tool, or outcome.  Mapping/list payloads are
    # intentionally dropped rather than recursively serialized.
    for key, value in extra.items():
        safe_key = safe_metadata_key(str(key))
        if safe_key is None or safe_key in fields:
            continue
        if isinstance(value, (Mapping, list, tuple, set)):
            continue
        fields[safe_key] = _bounded_scalar(value)
    for key in _REQUIRED_FIELDS:
        fields.setdefault(key, None)
    return fields


def emit_structured_log(
    sink: Any,
    level: str,
    *,
    event: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Bind canonical fields and emit one event through a Loguru-like sink.

    This helper deliberately swallows sink failures: telemetry/logging cannot
    change the API or worker truth path.  The sanitized fields are returned so
    tests and alternate JSON sinks can inspect the exact event envelope.
    """
    fields = structured_log_fields(event=event, **kwargs)
    try:
        bound = sink.bind(**fields)
        method = getattr(bound, level.lower(), None)
        if callable(method):
            method(event)
        else:
            bound.log(str(level).upper(), event)
    except Exception:
        # The caller's product path must remain fail-closed and observable via
        # the dedicated telemetry-failure metric, not a logging exception.
        try:
            from cygnus.observability._metrics import record_telemetry_failure

            record_telemetry_failure("structured_log")
        except Exception:
            pass
    return fields
