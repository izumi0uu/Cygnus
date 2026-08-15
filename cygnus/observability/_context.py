"""Request/trace correlation context.

One canonical correlation ID (a UUID string) propagates across HTTP requests,
MCP tool executions, audit rows, ARQ job payloads, and outbound delivery
receipts. The context lives in ``ContextVar`` so async tasks inherit it when
spawned inside the request scope.

Design:
- ``request_correlation(request_id)`` binds a validated request ID for the
  duration of the block (context manager).
- ``current_request_id()`` returns the active correlation ID or None.
- ``current_traceparent()`` returns a W3C ``traceparent`` header value derived
  deterministically from the correlation ID, so HTTP outbound calls carry the
  same identity without needing an OTel SDK.
- ``resolve_request_id_header(raw)`` validates an inbound ``X-Request-ID``:
  malformed values are rejected (never trusted across proxy boundaries), the
  raw value is echoed back only when it matches a strict UUID format.
- ``outbound_trace_headers()`` returns the bounded header set for outbound
  HTTP/delivery calls: ``X-Request-ID`` and ``traceparent``.

No secrets ever enter these values: the correlation ID is a random UUID, and
``traceparent`` is derived from it with a fixed span/flag suffix.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from contextvars import ContextVar
from typing import Iterator, Optional

from cygnus.observability._sanitize import sanitize_label_value

#: Inbound header we trust for correlation. Bounded to strict UUIDs.
REQUEST_ID_HEADER = "X-Request-ID"
TRACEPARENT_HEADER = "traceparent"
OUTBOUND_HEADERS = (REQUEST_ID_HEADER, TRACEPARENT_HEADER)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

#: W3C traceparent: version 00, 16-byte trace id, 8-byte span id, flags 01.
#: The span id is a fixed deterministic value so the same request always maps
#: to the same trace line without external span state.
_TRACEPARENT_VERSION = "00"
_TRACEPARENT_FLAGS = "01"
_SPAN_ID = "0000000000000001"  # 16 hex chars

_current_request_id: ContextVar[Optional[str]] = ContextVar(
    "cygnus_request_id", default=None
)


def _new_request_id() -> str:
    return str(uuid.uuid4())


def resolve_request_id_header(raw: Optional[str]) -> Optional[str]:
    """Validate an inbound X-Request-ID header value.

    Returns the normalized value when it is a strict UUID, else None (the
    caller should generate a fresh ID and treat the inbound value as
    untrusted). ``raw`` may be None (absent header).
    """
    if not raw:
        return None
    value = str(raw).strip()
    if len(value) > 64:
        return None
    if not _UUID_RE.match(value):
        return None
    return value.lower()


def traceparent_for(request_id: str) -> str:
    """Derive a stable W3C traceparent from a validated correlation ID.

    The correlation ID (UUID) supplies the 32-hex trace id; the span id is a
    fixed deterministic suffix so the same request always maps to the same
    trace line without external span state.
    """
    trace_id = request_id.replace("-", "")
    if len(trace_id) < 32:
        trace_id = trace_id.ljust(32, "0")
    return f"{_TRACEPARENT_VERSION}-{trace_id}-{_SPAN_ID}-{_TRACEPARENT_FLAGS}"


@contextlib.contextmanager
def request_correlation(
    request_id: Optional[str] = None,
) -> Iterator[Optional[str]]:
    """Bind a correlation ID for the duration of the block.

    - omitted (``None``) → a fresh UUID is generated and bound
    - a valid UUID → bound as-is
    - explicitly provided but malformed → nothing is bound; the block runs
      without correlation (yields ``None``) so untrusted IDs never enter the
      context
    """
    if request_id is None:
        effective: Optional[str] = _new_request_id()
    else:
        effective = resolve_request_id_header(request_id)
    if effective is None:
        yield None
        return
    token = _current_request_id.set(effective)
    try:
        yield effective
    finally:
        _current_request_id.reset(token)


def current_request_id() -> Optional[str]:
    """Return the active correlation ID, or None outside any request scope."""
    return _current_request_id.get()


def current_traceparent() -> Optional[str]:
    """Return the W3C traceparent for the active correlation ID, if any."""
    request_id = current_request_id()
    if not request_id:
        return None
    return traceparent_for(request_id)


def outbound_trace_headers() -> dict[str, str]:
    """Return bounded trace headers for outbound HTTP/delivery calls.

    Only the active correlation ID and its derived traceparent are included;
    no auth, payload, or identity data leaks into headers.
    """
    request_id = current_request_id()
    if not request_id:
        return {}
    headers = {REQUEST_ID_HEADER: request_id}
    traceparent = current_traceparent()
    if traceparent:
        headers[TRACEPARENT_HEADER] = traceparent
    return headers


def sanitize_request_id(value: str) -> str:
    """Bounded label-safe rendering of a correlation ID (for metrics)."""
    return sanitize_label_value(value, max_length=64)
