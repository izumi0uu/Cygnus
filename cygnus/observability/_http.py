"""HTTP-facing observability helpers.

- ``prometheus_metrics_endpoint()`` builds a plain-ASGI response handler that
  renders the bounded metric registry as Prometheus text. It performs no auth
  itself — the caller (runtime shell) decides exposure, gating, and whether to
  mount it. Uses lazy imports so this module is import-safe without FastAPI.
- ``record_http_request`` is re-exported here for runtime-shell convenience
  (definition lives in the metrics module).
"""

from __future__ import annotations

from typing import Any

from cygnus.observability._config import configure_observability
from cygnus.observability._metrics import (
    record_http_request,  # noqa: F401
    record_release_info,
    render_prometheus_metrics,
)


def prometheus_metrics_endpoint() -> Any:
    """Return an async ``(scope, receive, send)`` ASGI handler for /metrics.

    Renders the current bounded metric registry. When Prometheus metrics are
    disabled in config the handler returns 204 No Content. The runtime release
    identity gauge is refreshed on every scrape so release metadata stays
    observable without build-time wiring.
    """

    async def _handler(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        cfg = configure_observability()
        if cfg.prometheus_metrics_enabled:
            from cygnus.observability._identity import runtime_identity

            identity = runtime_identity()
            record_release_info(
                release=identity["release"],
                environment=identity["environment"],
                commit_sha=identity["commit_sha"],
            )
        body = render_prometheus_metrics(enabled=bool(cfg.prometheus_metrics_enabled))
        if not body:
            status = 204
            payload = b""
            content_type = "text/plain; charset=utf-8"
        else:
            status = 200
            payload = body.encode("utf-8")
            content_type = "text/plain; version=0.0.4; charset=utf-8"
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", content_type.encode("utf-8")),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    return _handler
