"""Manifest-driven, failure-safe dispatcher for governed session tool calls.

CYG-140 ownership: pre-handler schema/policy validation, per-class deadlines,
bounded read-only retries, and one correlated structured result per call in
mixed batches. REST, MCP, and neutral-session surfaces share this execution
path so validation, deadlines, retry rules, and error vocabulary cannot drift
between transports.

Outcome vocabulary (shared with the request-scoped adapters):

- ``invalid`` / ``["invalid_arguments"]`` — arguments fail the canonical
  manifest input schema before any handler runs.
- ``invalid`` / ``["unknown_tool"]`` — the call names a tool outside the
  canonical twelve-tool contract.
- ``denied`` / ``["permission_denied"]`` — the authenticated actor policy
  rejects the tool's permission requirement before any handler runs.
- ``deadline_exceeded`` / ``["deadline_exceeded"]`` — the handler exceeded its
  manifest-declared class deadline.
- ``internal_error`` / ``["internal_error"]`` — the handler raised; the
  envelope carries a stable code, never exception text or payload.
- ``success`` — the handler result, echoed with the negotiated
  ``contract_version``.

Retry policy: only ``read_only`` side-effect tools with a
``transient_only`` policy are retried, strictly bounded by
``max_attempts``/``backoff_ms`` and the remaining class deadline, and only for
``TransientToolError`` codes listed in the policy. Writes are never blindly
retried; replay safety is provided by actor-bound command receipts in the
durable write handlers instead.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from cygnus.substrate.agent_protocol import (
    SESSION_CONTRACT_VERSION,
    SessionActorScope,
    SessionContractVersionError,
    SessionManifest,
    SessionToolManifest,
    ToolCall,
    ToolDefinition,
    build_session_manifest,
    negotiate_session_contract_version,
    session_contract_error_envelope,
    session_tool_manifest_result_envelope,
)

ToolHandler = Callable[..., Any]
AsyncToolHandler = Callable[..., Awaitable[Any]]

# Shared structured outcome statuses/codes (CYG-140).
STATUS_INVALID = "invalid"
STATUS_DENIED = "denied"
STATUS_DEADLINE_EXCEEDED = "deadline_exceeded"
STATUS_INTERNAL_ERROR = "internal_error"
ERROR_INVALID_ARGUMENTS = "invalid_arguments"
ERROR_UNKNOWN_TOOL = "unknown_tool"
ERROR_PERMISSION_DENIED = "permission_denied"
ERROR_DEADLINE_EXCEEDED = "deadline_exceeded"
ERROR_INTERNAL = "internal_error"


class TransientToolError(Exception):
    """A transient, retryable failure surfaced by a read-only tool handler.

    The dispatcher retries it only when the tool's manifest policy is
    ``transient_only``, the code is listed in ``retryable_error_codes``, and
    the bounded attempt budget is not exhausted.
    """

    def __init__(
        self,
        message: str = "Upstream service is temporarily unavailable.",
        *,
        code: str = "temporarily_unavailable",
    ) -> None:
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Minimal JSON-schema-subset validator (no external dependency)
# ---------------------------------------------------------------------------
# Covers exactly the constructs used by the canonical governed tool input
# schemas: type, enum, required, properties/additionalProperties, items,
# minLength/maxLength, minimum/maximum, minProperties, and uuid format.


def _type_matches(value: Any, expected: object) -> bool:
    if isinstance(expected, (list, tuple)):
        return any(_type_matches(value, item) for item in expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "null":
        return value is None
    return False


def _validate_schema(schema: Mapping[str, Any], value: Any, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None and not _type_matches(value, expected_type):
        expected_label = (
            " or ".join(str(item) for item in expected_type)
            if isinstance(expected_type, (list, tuple))
            else str(expected_type)
        )
        return [f"{path}: expected {expected_label}"]

    if "const" in schema and value != schema["const"]:
        return [f"{path}: must equal the declared constant"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: not one of the allowed values"]
    if value is None:
        return errors

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"{path}: shorter than {min_length} characters")
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > max_length:
            errors.append(f"{path}: longer than {max_length} characters")
        pattern = schema.get("pattern")
        if pattern is not None:
            try:
                matches = re.fullmatch(str(pattern), value) is not None
            except re.error:
                matches = False
            if not matches:
                errors.append(f"{path}: does not match the required pattern")
        if schema.get("format") == "uuid":
            try:
                uuid.UUID(value)
            except ValueError:
                errors.append(f"{path}: not a valid uuid")
        return errors

    if isinstance(value, bool):
        return errors

    if isinstance(value, (int, float)):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: below the minimum of {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: above the maximum of {maximum}")
        return errors

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        required_fields = set(schema.get("required", ()))
        present_items = {key: item for key, item in value.items() if item is not None}
        min_properties = schema.get("minProperties")
        if min_properties is not None and len(present_items) < min_properties:
            errors.append(f"{path}: fewer than {min_properties} properties")
        max_properties = schema.get("maxProperties")
        if max_properties is not None and len(present_items) > max_properties:
            errors.append(f"{path}: more than {max_properties} properties")
        for required in sorted(required_fields):
            if required not in value:
                errors.append(f"{path}: missing required field {required!r}")
            elif value[required] is None:
                errors.append(f"{path}.{required}: required field must not be null")
        for key, item in value.items():
            if item is None:
                continue
            property_schema = properties.get(key)
            if property_schema is None:
                if schema.get("additionalProperties", True) is False:
                    errors.append(f"{path}: unexpected field {key!r}")
                continue
            errors.extend(_validate_schema(property_schema, item, f"{path}.{key}"))
        return errors

    if isinstance(value, (list, tuple)):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: fewer than {min_items} items")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: more than {max_items} items")
        items_schema = schema.get("items")
        if items_schema is not None:
            for index, item in enumerate(value):
                errors.extend(_validate_schema(items_schema, item, f"{path}[{index}]"))
        return errors

    return errors


def validate_arguments(
    schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> list[str]:
    """Validate one call's arguments against a strict tool input schema."""
    errors = _validate_schema(schema, arguments, "arguments")
    return [
        error.removeprefix("arguments: ").removeprefix("arguments.") for error in errors
    ]


# ---------------------------------------------------------------------------
# Canonical manifest resolution
# ---------------------------------------------------------------------------

_session_manifest_cache: SessionManifest | None = None


def session_tool_manifest() -> SessionManifest:
    """Return the canonical twelve-tool session manifest (lazily built).

    Built from ``governed_session_tool_definitions()`` so REST capabilities,
    MCP, and the dispatcher all derive from one contract. Lazy import keeps
    the substrate layer free of the integrations dependency cycle.
    """
    global _session_manifest_cache
    if _session_manifest_cache is None:
        from cygnus.integrations.governed_session_tools import (
            governed_session_tool_definitions,
        )

        _session_manifest_cache = build_session_manifest(
            governed_session_tool_definitions()
        )
    return _session_manifest_cache


def _error_envelope(
    *,
    status: str,
    summary: str,
    code: str,
    contract_version: str,
    trace_ref: str | None = None,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return session_tool_manifest_result_envelope(
        status=status,
        summary=summary,
        data=dict(data or {}),
        errors=(code,),
        trace_ref=trace_ref,
        contract_version=contract_version,
    )


# ---------------------------------------------------------------------------
# Core execution path (shared by REST, MCP, and neutral dispatch)
# ---------------------------------------------------------------------------


async def _invoke_handler(
    handler: ToolHandler | AsyncToolHandler,
    arguments: Mapping[str, Any],
) -> Any:
    result = handler(**arguments)
    if inspect.isawaitable(result):
        return await result
    return result


async def execute_governed_tool_call(
    *,
    tool: SessionToolManifest,
    arguments: Mapping[str, Any],
    handler: ToolHandler | AsyncToolHandler,
    actor_scope: SessionActorScope | None = None,
    contract_version: str = SESSION_CONTRACT_VERSION,
) -> dict[str, Any]:
    """Run one governed tool call under the canonical manifest contract.

    Order of enforcement, before any handler work:

    1. Negotiate the client contract major (incompatible versions fail first).
    2. Validate arguments against the manifest input schema.
    3. Require and evaluate an authenticated actor scope.

    Then execute within the tool's class deadline, retrying only read-only
    transient failures under the bounded policy budget. Every path returns one
    structured envelope; ``success`` echoes the handler result with the
    negotiated ``contract_version`` injected.
    """
    try:
        negotiated = negotiate_session_contract_version(contract_version)
    except SessionContractVersionError as exc:
        return session_contract_error_envelope(exc)

    schema_errors = validate_arguments(tool.input_schema, arguments)
    if schema_errors:
        return _error_envelope(
            status=STATUS_INVALID,
            summary=f"Tool arguments failed manifest validation: {schema_errors[0]}",
            code=ERROR_INVALID_ARGUMENTS,
            contract_version=negotiated,
            data={"errors": schema_errors},
        )

    resolved_actor_scope = actor_scope or SessionActorScope(authenticated=False)
    if not resolved_actor_scope.allows(tool.permission_requirement):
        return _error_envelope(
            status=STATUS_DENIED,
            summary=(
                f"Tool {tool.name} requires {tool.permission_requirement.value}; "
                "the current actor scope is not permitted."
            ),
            code=ERROR_PERMISSION_DENIED,
            contract_version=negotiated,
        )

    retryable = (
        tool.side_effect_class == "read_only"
        and tool.retry_policy.mode == "transient_only"
        and bool(tool.retry_policy.retryable_error_codes)
    )
    deadline_seconds = float(tool.timeout_seconds)
    attempt = 1
    started = time.monotonic()

    while True:
        remaining = deadline_seconds - (time.monotonic() - started)
        if remaining <= 0:
            return _error_envelope(
                status=STATUS_DEADLINE_EXCEEDED,
                summary=f"Tool {tool.name} exceeded its {int(deadline_seconds)}s deadline.",
                code=ERROR_DEADLINE_EXCEEDED,
                contract_version=negotiated,
            )

        try:
            result = await asyncio.wait_for(
                _invoke_handler(handler, arguments),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            return _error_envelope(
                status=STATUS_DEADLINE_EXCEEDED,
                summary=f"Tool {tool.name} exceeded its {int(deadline_seconds)}s deadline.",
                code=ERROR_DEADLINE_EXCEEDED,
                contract_version=negotiated,
            )
        except TransientToolError as exc:
            if (
                retryable
                and exc.code in tool.retry_policy.retryable_error_codes
                and attempt < tool.retry_policy.max_attempts
            ):
                attempt += 1
                backoff = min(
                    tool.retry_policy.backoff_ms / 1000.0,
                    max(remaining, 0.0),
                )
                if backoff > 0:
                    await asyncio.sleep(backoff)
                continue
            return _error_envelope(
                status=STATUS_INTERNAL_ERROR,
                summary=(
                    "Transient tool failure exceeded the bounded retry policy."
                    if retryable
                    else "Tool execution failed."
                ),
                code=exc.code if retryable else ERROR_INTERNAL,
                contract_version=negotiated,
            )
        except Exception:
            return _error_envelope(
                status=STATUS_INTERNAL_ERROR,
                summary="Tool execution failed.",
                code=ERROR_INTERNAL,
                contract_version=negotiated,
            )

        if isinstance(result, dict) and "contract_version" not in result:
            return {**result, "contract_version": negotiated}
        return result


# ---------------------------------------------------------------------------
# Registry and mixed-batch dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, *, manifest: SessionManifest | None = None) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._manifest = manifest

    @property
    def manifest(self) -> SessionManifest:
        if self._manifest is None:
            return session_tool_manifest()
        return self._manifest

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = RegisteredTool(
            definition=definition, handler=handler
        )

    def list_definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(item.definition for item in self._tools.values())

    def handler_for(self, name: str) -> ToolHandler | None:
        registered = self._tools.get(name)
        return registered.handler if registered is not None else None

    def call(self, tool_call: ToolCall) -> Any:
        registered = self._tools.get(tool_call.name)
        if registered is None:
            raise ValueError(f"unknown tool: {tool_call.name}")
        return registered.handler(**tool_call.arguments)


async def dispatch_tool_calls(
    registry: ToolRegistry,
    tool_calls: tuple[ToolCall, ...] | list[ToolCall],
    *,
    actor: object | None = None,
    contract_version: str = SESSION_CONTRACT_VERSION,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Execute a mixed batch without aborting: one correlated result per call.

    Pre-handler validation/policy evaluation and deadlines apply per call; a
    rejected call never runs its handler, and one call's failure never aborts
    the remaining calls. Results keep the ``(call_id, tool_name, envelope)``
    correlation shape consumed by neutral tool-result projections.
    """
    try:
        negotiated = negotiate_session_contract_version(contract_version)
    except SessionContractVersionError as exc:
        incompatible = session_contract_error_envelope(exc)
        return [
            (tool_call.id, tool_call.name, incompatible) for tool_call in tool_calls
        ]

    actor_scope = SessionActorScope.from_actor(actor)
    results: list[tuple[str, str, dict[str, Any]]] = []
    for tool_call in tool_calls:
        try:
            tool = registry.manifest.tool(tool_call.name)
        except ValueError:
            results.append(
                (
                    tool_call.id,
                    tool_call.name,
                    _error_envelope(
                        status=STATUS_INVALID,
                        summary=f"Unknown governed session tool: {tool_call.name}",
                        code=ERROR_UNKNOWN_TOOL,
                        contract_version=negotiated,
                    ),
                )
            )
            continue

        handler = registry.handler_for(tool_call.name)
        if handler is None:
            results.append(
                (
                    tool_call.id,
                    tool_call.name,
                    _error_envelope(
                        status=STATUS_INVALID,
                        summary=f"Tool {tool_call.name} has no registered handler.",
                        code=ERROR_UNKNOWN_TOOL,
                        contract_version=negotiated,
                    ),
                )
            )
            continue

        envelope = await execute_governed_tool_call(
            tool=tool,
            arguments=tool_call.arguments,
            handler=handler,
            actor_scope=actor_scope,
            contract_version=negotiated,
        )
        results.append((tool_call.id, tool_call.name, envelope))
    return results


__all__ = [
    "AsyncToolHandler",
    "RegisteredTool",
    "ToolHandler",
    "ToolRegistry",
    "TransientToolError",
    "dispatch_tool_calls",
    "execute_governed_tool_call",
    "session_tool_manifest",
    "validate_arguments",
]
