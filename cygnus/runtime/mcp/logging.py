"""
MCP tool-call execution wrapper and logging (CYG-140 / CYG-142).

Every governed tool invocation routes through the shared manifest-driven
execution path in :mod:`cygnus.substrate.tool_runtime`:

- canonical manifest input-schema validation runs before any handler work;
- the handler executes inside its manifest-declared class deadline;
- read-only transient failures retry under the bounded policy budget;
- rejected/deadlined/failed calls return the same structured envelope
  vocabulary as REST, each echoing ``contract_version``.

The decorator also records one ``mcp_query_log`` row (fire-and-forget) with
the request correlation ID/traceparent from :mod:`cygnus.observability` and
feeds the bounded ``record_mcp_tool`` metric. `_get_identity()` in tools.py
sets `current_identity` after resolving the bearer token so logging can read
employee_id without a second DB call. Legacy non-governed tools keep their
historical execution path and string-heuristic logging.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

from fastmcp.tools.base import ToolResult
from loguru import logger

from cygnus.observability import (
    current_request_id,
    current_traceparent,
    emit_structured_log,
    record_mcp_tool,
    sanitize_error,
    start_span,
)
from cygnus.observability._sanitize import sanitize_annotation
from cygnus.substrate.agent_protocol import (
    SESSION_CONTRACT_VERSION,
    SessionActorScope,
)
from cygnus.substrate.tool_runtime import (
    execute_governed_tool_call,
    session_tool_manifest,
)


# Set inside _get_identity() once the token resolves to an Employee.
# None when auth failed or the call happened before resolution.
current_identity: ContextVar[Optional[Any]] = ContextVar(
    "mcp_current_identity", default=None
)


_AUTH_FAIL_HINTS = (
    "authentication required",
    "invalid or inactive mcp token",
    "no http request context",
)
_DENIED_HINTS = (
    "access denied",
    "you do not have permission",
    "not allowed",
    "forbidden",
)
_ERROR_HINTS = (
    "error:",
    "failed to",
    "could not",
)

# Patterns that announce a result list — e.g. "**Wiki search — 7 result(s) for: ..."
_COUNT_PATTERNS = (
    re.compile(r"(\d+)\s+result\(s\)"),
    re.compile(r"(\d+)\s+pages?\s+found"),
    re.compile(r"(\d+)\s+sources?\s+found"),
    re.compile(r"(\d+)\s+drafts?\s+pending"),
    re.compile(r"\b(\d+)\s+matches?\b"),
)

_ZERO_RESULT_HINTS = (
    "no wiki pages found",
    "no sources found",
    "no results",
    "no pages found",
    "no drafts pending",
)

# Structured envelope statuses produced by the governed adapters and the
# shared dispatcher. `success` maps to the durable log status `ok`, `denied`
# stays `denied`, everything else is an `error` for analytics.
_LOG_OK_STATUSES = frozenset({"success", "ok"})
_LOG_DENIED_STATUSES = frozenset({"denied"})


def _classify_status(result_text: str) -> str:
    """Infer ok | denied | error from a legacy string-returning tool."""
    if not isinstance(result_text, str):
        return "ok"
    low = result_text.lower()
    for hint in _AUTH_FAIL_HINTS:
        if hint in low:
            return "denied"
    for hint in _DENIED_HINTS:
        if hint in low:
            return "denied"
    # Only flag as error when the message strongly signals failure AND has no
    # successful-search prefix.
    if low.startswith("error") or low.startswith("failed"):
        return "error"
    return "ok"


def _log_status_for(envelope_status: str) -> str:
    """Map the structured envelope status onto the durable log vocabulary."""
    if envelope_status in _LOG_OK_STATUSES:
        return "ok"
    if envelope_status in _LOG_DENIED_STATUSES:
        return "denied"
    return "error"


def _estimate_result_count(result_text: str, tool_name: str) -> Optional[int]:
    """Heuristic: pull a count from the formatted output string."""
    if not isinstance(result_text, str):
        return None
    low = result_text.lower()
    for hint in _ZERO_RESULT_HINTS:
        if hint in low:
            return 0
    for pattern in _COUNT_PATTERNS:
        m = pattern.search(result_text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    # Read-style tools that return one page/source — count = 1 on success
    if (
        tool_name in {"read_wiki_page", "get_source", "review_draft"}
        and _classify_status(result_text) == "ok"
    ):
        return 1
    return None


async def _persist_log(
    *,
    tool_name: str,
    employee_id: Optional[Any],
    query_text: Optional[str],
    result_count: Optional[int],
    latency_ms: int,
    status: str,
    error_message: Optional[str],
    correlation_id: Optional[str] = None,
    traceparent: Optional[str] = None,
    scope_metadata: Optional[dict] = None,
) -> None:
    """Write a single mcp_query_log row. Swallows errors so logging never breaks tool calls."""
    effective_correlation_id = correlation_id or current_request_id()
    effective_traceparent = traceparent or current_traceparent()
    try:
        from cygnus.runtime.database import async_session_factory
        from cygnus.runtime.database.models import MCPQueryLog

        async with async_session_factory() as session:
            row = MCPQueryLog(
                employee_id=employee_id,
                tool_name=tool_name,
                query_text=(
                    sanitize_annotation(query_text, max_length=2000)
                    if query_text
                    else None
                ),
                result_count=result_count,
                latency_ms=latency_ms,
                scope_metadata=scope_metadata,
                status=status,
                error_message=(
                    sanitize_annotation(error_message, max_length=1000)
                    if error_message
                    else None
                ),
                correlation_id=(
                    uuid.UUID(effective_correlation_id)
                    if effective_correlation_id is not None
                    else None
                ),
                traceparent=effective_traceparent,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        emit_structured_log(
            logger,
            "warning",
            event="mcp_log_persist_failed",
            route=f"mcp:{tool_name}",
            status="telemetry_failed",
            actor_class="system",
            error=exc,
            tool=tool_name,
        )


def _bind_arguments(
    fn: Callable[..., Any], args: tuple, kwargs: dict
) -> dict[str, Any]:
    """Bind positional/keyword arguments to parameter names for validation."""
    if not args:
        return dict(kwargs)
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
    except TypeError:
        return dict(kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def _serialize_payload(payload: dict[str, Any]) -> str:
    """Serialize one structured envelope for the MCP string return contract."""
    return json.dumps(payload, ensure_ascii=False, default=str)


async def _run_governed_tool(
    fn: Callable[..., Awaitable[Any]],
    tool_name: str,
    args: tuple,
    kwargs: dict,
) -> Any:
    """Execute one tool through the shared manifest-driven dispatcher.

    Governed tools (the canonical twelve) are validated against their manifest
    input schema before the handler runs, execute inside the per-class
    deadline, and retry read-only transient failures under the bounded policy.
    The MCP transport itself (ScopedToolsMiddleware) remains the listing/deny
    gate; per-resource authorization stays in the tool bodies.
    """
    try:
        tool = session_tool_manifest().tool(tool_name)
    except ValueError:
        # Legacy non-governed tools keep their historical execution path.
        return await fn(*args, **kwargs)

    envelope = await execute_governed_tool_call(
        tool=tool,
        arguments=_bind_arguments(fn, args, kwargs),
        handler=fn,
        actor_scope=SessionActorScope.from_actor(current_identity.get()),
        contract_version=SESSION_CONTRACT_VERSION,
    )
    return envelope


def logged_tool(
    tool_name: str,
    query_arg: Optional[str] = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """
    Decorator: wraps an MCP tool function with the shared governed execution
    path and records a row in `mcp_query_log`.

    Args:
        tool_name: Name to record (use the function name).
        query_arg: Kwarg or first positional arg name to capture as `query_text`
                   (e.g. "query" for search_wiki, "slug" for read_wiki_page).
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            status = "ok"
            envelope_status = "ok"
            error_message: Optional[str] = None
            failure: BaseException | None = None
            deadline_exceeded = False
            result: Any = None
            count_source: Any = None
            with start_span("cygnus.mcp.tool", {"tool": tool_name}):
                try:
                    result = await _run_governed_tool(fn, tool_name, args, kwargs)
                    if isinstance(result, dict):
                        envelope_status = str(result.get("status") or "ok")
                        envelope = result
                        count_source = _serialize_payload(envelope)
                        result = ToolResult(
                            content=count_source,
                            structured_content=envelope,
                        )
                    elif isinstance(result, str):
                        envelope_status = _classify_status(result)
                        count_source = result
                    else:
                        envelope_status = "ok"
                        count_source = result
                    status = _log_status_for(envelope_status)
                    deadline_exceeded = envelope_status == "deadline_exceeded"
                    return result
                except Exception as exc:  # noqa: BLE001
                    status = "error"
                    envelope_status = "error"
                    failure = exc
                    error_message = sanitize_error(exc)
                    raise
                finally:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    # Pull query text from kwargs first, then first positional arg.
                    query_text: Optional[str] = None
                    if query_arg:
                        query_text = kwargs.get(query_arg)
                        if query_text is None and args:
                            query_text = args[0] if isinstance(args[0], str) else None
                    # Resolve identity from ContextVar set inside _get_identity().
                    identity = current_identity.get()
                    employee_id = (
                        getattr(identity, "employee_id", None) if identity else None
                    )
                    correlation_id = current_request_id()
                    traceparent = current_traceparent()
                    result_count = (
                        _estimate_result_count(count_source, tool_name)
                        if status == "ok"
                        else None
                    )
                    record_mcp_tool(
                        tool=tool_name,
                        status=envelope_status,
                        duration_ms=latency_ms,
                        deadline_exceeded=deadline_exceeded,
                    )
                    command_id = kwargs.get("command_id")
                    if command_id is None and isinstance(result, dict):
                        command_id = result.get("command_id")
                    emit_structured_log(
                        logger,
                        "error" if failure is not None or status == "error" else "info",
                        event="mcp_tool",
                        route=f"mcp:{tool_name}",
                        status=envelope_status,
                        duration_ms=latency_ms,
                        actor_class="authenticated" if identity else "anonymous",
                        job_id=kwargs.get("_job_id"),
                        command_id=command_id,
                        terminal_reason=(
                            envelope_status
                            if envelope_status
                            in {"denied", "error", "deadline_exceeded"}
                            else None
                        ),
                        error=failure,
                        tool=tool_name,
                    )
                    asyncio.create_task(
                        _persist_log(
                            tool_name=tool_name,
                            employee_id=employee_id,
                            query_text=(
                                str(query_text) if query_text is not None else None
                            ),
                            result_count=result_count,
                            latency_ms=latency_ms,
                            status=status,
                            error_message=error_message,
                            correlation_id=correlation_id,
                            traceparent=traceparent,
                        )
                    )

        return wrapper

    return decorator
