"""Cygnus-owned provider-neutral agent/tool protocol.

Canonical owner for multi-turn tool-calling message shapes and provider-specific
projection helpers. Runtime AI code should import this module directly; the
runtime `agent_protocol` path remains only as a compatibility shim.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("tool call id must not be blank")
        if not self.name.strip():
            raise ValueError("tool call name must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantTurn:
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    finish_reason: str = "end_turn"
    raw_provider_content: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if not self.finish_reason.strip():
            raise ValueError("finish_reason must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    risk_level: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool definition name must not be blank")
        if not self.description.strip():
            raise ValueError("tool definition description must not be blank")
        if not self.risk_level.strip():
            raise ValueError("tool definition risk_level must not be blank")

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


SESSION_CONTRACT_VERSION = "1.0"
SESSION_CONTRACT_VERSION_HEADER = "X-Cygnus-Session-Contract-Version"
_SESSION_CONTRACT_VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)(?:\.(?P<minor>0|[1-9][0-9]*))?(?:\.(?P<patch>0|[1-9][0-9]*))?$"
)
_SESSION_TOOL_NAMES = (
    "search_knowledge_objects",
    "read_knowledge_object",
    "search_support_evidence",
    "get_source_trace",
    "list_drift_alerts",
    "propose_knowledge_object",
    "update_draft_object",
    "request_review",
    "read_review_feedback",
    "record_feedback_signal",
    "validate_publish_policy",
    "publish_knowledge_object",
)


class SessionContractVersionError(ValueError):
    """Raised when a session client cannot negotiate the active contract major."""

    def __init__(self, requested_version: object, *, code: str) -> None:
        self.requested_version = requested_version
        self.code = code
        super().__init__(
            "A session contract version is required."
            if code == "missing_contract_version"
            else "The requested session contract major is not supported."
        )


def negotiate_session_contract_version(requested_version: object) -> str:
    """Return the active version when the client requests its supported major."""
    if not isinstance(requested_version, str) or not requested_version.strip():
        raise SessionContractVersionError(
            requested_version,
            code="missing_contract_version",
        )

    requested_match = _SESSION_CONTRACT_VERSION_PATTERN.fullmatch(
        requested_version.strip()
    )
    active_match = _SESSION_CONTRACT_VERSION_PATTERN.fullmatch(SESSION_CONTRACT_VERSION)
    if requested_match is None or active_match is None:
        raise SessionContractVersionError(
            requested_version,
            code="incompatible_contract_version",
        )
    if requested_match.group("major") != active_match.group("major"):
        raise SessionContractVersionError(
            requested_version,
            code="incompatible_contract_version",
        )
    return SESSION_CONTRACT_VERSION


class SessionToolPermission(str, Enum):
    AUTHENTICATED = "authenticated"
    WIKI_CONTRIBUTE = "wiki:write:*"
    ADMINISTRATOR = "administrator"


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionActorScope:
    """Minimal pure permission view shared by REST and MCP projections."""

    authenticated: bool = True
    is_admin: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", frozenset(self.permissions))

    @classmethod
    def from_actor(cls, actor: object | None) -> "SessionActorScope":
        if actor is None:
            return cls(authenticated=False)
        if isinstance(actor, cls):
            return actor
        raw_permissions = getattr(actor, "permissions", ())
        permissions = (
            frozenset(item for item in raw_permissions if isinstance(item, str))
            if isinstance(raw_permissions, (list, tuple, set, frozenset))
            else frozenset()
        )
        role_is_admin = getattr(actor, "role", None) == "admin"
        return cls(
            authenticated=True,
            is_admin=bool(getattr(actor, "is_admin", False)) or role_is_admin,
            permissions=permissions,
        )

    def allows(self, requirement: SessionToolPermission) -> bool:
        if not self.authenticated:
            return False
        if requirement is SessionToolPermission.AUTHENTICATED:
            return True
        if self.is_admin:
            return True
        if requirement is SessionToolPermission.WIKI_CONTRIBUTE:
            return bool(
                self.permissions.intersection({"wiki:write:own_dept", "wiki:write:all"})
            )
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionRetryPolicy:
    mode: str
    max_attempts: int
    backoff_ms: int = 0
    retryable_error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"never", "transient_only"}:
            raise ValueError("session retry mode must be never or transient_only")
        if self.max_attempts < 1:
            raise ValueError("session retry policy requires at least one attempt")
        if self.backoff_ms < 0:
            raise ValueError("session retry backoff must not be negative")
        object.__setattr__(
            self, "retryable_error_codes", tuple(self.retryable_error_codes)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "max_attempts": self.max_attempts,
            "backoff_ms": self.backoff_ms,
            "retryable_error_codes": list(self.retryable_error_codes),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionToolManifest:
    """Immutable contract for one governed session-facing tool."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    permission_requirement: SessionToolPermission
    risk_class: str
    side_effect_class: str
    idempotency_class: str
    timeout_seconds: int
    retry_policy: SessionRetryPolicy
    availability_semantics: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("session manifest tool name must not be blank")
        if self.risk_class not in {"R0", "R1", "R2", "R3"}:
            raise ValueError("session manifest risk class must be R0 through R3")
        if self.timeout_seconds < 1:
            raise ValueError("session manifest timeout must be positive")
        object.__setattr__(self, "input_schema", _freeze_json(self.input_schema))
        object.__setattr__(self, "output_schema", _freeze_json(self.output_schema))

    @property
    def parameters(self) -> Mapping[str, Any]:
        """Compatibility name for provider tool registries."""
        return self.input_schema

    def to_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=_thaw_json(self.input_schema),
            risk_level=self.risk_class,
        )

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": _thaw_json(self.input_schema),
            "output_schema": _thaw_json(self.output_schema),
            "permission_requirement": self.permission_requirement.value,
            "risk_class": self.risk_class,
            "side_effect_class": self.side_effect_class,
            "idempotency_class": self.idempotency_class,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy.to_dict(),
            "availability_semantics": self.availability_semantics,
        }

    def capability_projection(self, actor: object | None) -> dict[str, object]:
        scope = SessionActorScope.from_actor(actor)
        allowed = scope.allows(self.permission_requirement)
        return {
            **self.metadata(),
            "availability": "available" if allowed else "denied",
            "denial_reason": None if allowed else "permission_required",
        }

    def mcp_projection(self, actor: object | None) -> dict[str, object]:
        projection = self.capability_projection(actor)
        return {
            "name": projection["name"],
            "description": projection["description"],
            "input_schema": projection["input_schema"],
            "output_schema": projection["output_schema"],
            "annotations": {
                "contract_version": SESSION_CONTRACT_VERSION,
                "permission_requirement": projection["permission_requirement"],
                "risk_class": projection["risk_class"],
                "side_effect_class": projection["side_effect_class"],
                "idempotency_class": projection["idempotency_class"],
                "timeout_seconds": projection["timeout_seconds"],
                "retry_policy": projection["retry_policy"],
                "availability": projection["availability"],
            },
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionManifest:
    """The immutable canonical contract from which session surfaces project."""

    contract_version: str
    tools: tuple[SessionToolManifest, ...]
    _by_name: Mapping[str, SessionToolManifest] = field(init=False, repr=False)
    schema_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        negotiated_version = negotiate_session_contract_version(self.contract_version)
        if negotiated_version != self.contract_version:
            raise ValueError("session manifest must use the active contract version")
        object.__setattr__(self, "tools", tuple(self.tools))
        names = tuple(tool.name for tool in self.tools)
        if names != _SESSION_TOOL_NAMES:
            raise ValueError(
                "session manifest must contain the twelve governed tools in order"
            )
        by_name = {tool.name: tool for tool in self.tools}
        object.__setattr__(self, "_by_name", MappingProxyType(by_name))
        normalized = {
            "contract_version": self.contract_version,
            "tools": [tool.metadata() for tool in self.tools],
        }
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        object.__setattr__(
            self, "schema_fingerprint", hashlib.sha256(encoded).hexdigest()
        )

    def tool(self, name: str) -> SessionToolManifest:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise ValueError(f"unknown governed session tool: {name}") from exc

    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.to_tool_definition() for tool in self.tools)

    def capabilities(self, actor: object | None) -> dict[str, object]:
        tools = [tool.capability_projection(actor) for tool in self.tools]
        return {
            "contract_version": self.contract_version,
            "schema_fingerprint": self.schema_fingerprint,
            "governed_tools": tools,
            "visible_tools": [
                tool for tool in tools if tool["availability"] == "available"
            ],
            "denied_tools": [
                tool for tool in tools if tool["availability"] == "denied"
            ],
        }

    def mcp_tools(self, actor: object | None) -> list[dict[str, object]]:
        return [
            tool.mcp_projection(actor)
            for tool in self.tools
            if SessionActorScope.from_actor(actor).allows(tool.permission_requirement)
        ]

    def openapi_projection(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "schema_fingerprint": self.schema_fingerprint,
            "tools": [tool.metadata() for tool in self.tools],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class _SessionToolPolicy:
    permission_requirement: SessionToolPermission
    side_effect_class: str
    idempotency_class: str
    timeout_seconds: int
    retry_policy: SessionRetryPolicy
    availability_semantics: str


_NO_RETRY = SessionRetryPolicy(mode="never", max_attempts=1)
_READ_RETRY = SessionRetryPolicy(
    mode="transient_only",
    max_attempts=2,
    backoff_ms=100,
    retryable_error_codes=("upstream_timeout", "temporarily_unavailable"),
)
_SESSION_TOOL_POLICIES: Mapping[str, _SessionToolPolicy] = MappingProxyType(
    {
        "search_knowledge_objects": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only",
            idempotency_class="not_applicable",
            timeout_seconds=5,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "read_knowledge_object": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only",
            idempotency_class="not_applicable",
            timeout_seconds=5,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "search_support_evidence": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only",
            idempotency_class="not_applicable",
            timeout_seconds=5,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "get_source_trace": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only",
            idempotency_class="not_applicable",
            timeout_seconds=5,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "list_drift_alerts": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only",
            idempotency_class="not_applicable",
            timeout_seconds=5,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "propose_knowledge_object": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.WIKI_CONTRIBUTE,
            side_effect_class="durable_draft_write",
            idempotency_class="non_idempotent",
            timeout_seconds=15,
            retry_policy=_NO_RETRY,
            availability_semantics="available_when_wiki_contributor",
        ),
        "update_draft_object": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.WIKI_CONTRIBUTE,
            side_effect_class="durable_draft_write",
            idempotency_class="optimistic_versioned",
            timeout_seconds=15,
            retry_policy=_NO_RETRY,
            availability_semantics="available_when_wiki_contributor",
        ),
        "request_review": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.WIKI_CONTRIBUTE,
            side_effect_class="durable_review_transition",
            idempotency_class="ledger_replay_safe",
            timeout_seconds=15,
            retry_policy=_NO_RETRY,
            availability_semantics="available_when_wiki_contributor",
        ),
        "read_review_feedback": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only",
            idempotency_class="not_applicable",
            timeout_seconds=5,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "record_feedback_signal": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="durable_feedback_write",
            idempotency_class="command_id_replay_safe",
            timeout_seconds=15,
            retry_policy=_NO_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "validate_publish_policy": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.AUTHENTICATED,
            side_effect_class="read_only_policy_check",
            idempotency_class="not_applicable",
            timeout_seconds=10,
            retry_policy=_READ_RETRY,
            availability_semantics="available_when_authenticated_and_in_scope",
        ),
        "publish_knowledge_object": _SessionToolPolicy(
            permission_requirement=SessionToolPermission.ADMINISTRATOR,
            side_effect_class="durable_publication_commit",
            idempotency_class="command_id_replay_safe",
            timeout_seconds=30,
            retry_policy=_NO_RETRY,
            availability_semantics="available_when_administrator",
        ),
    }
)


def build_session_manifest(
    definitions: tuple[ToolDefinition, ...],
    *,
    contract_version: str = SESSION_CONTRACT_VERSION,
) -> SessionManifest:
    definitions_by_name = {definition.name: definition for definition in definitions}
    if (
        len(definitions) != len(_SESSION_TOOL_NAMES)
        or len(definitions_by_name) != len(_SESSION_TOOL_NAMES)
        or set(definitions_by_name) != set(_SESSION_TOOL_NAMES)
    ):
        raise ValueError(
            "governed session definitions must contain the canonical twelve names"
        )

    tools = tuple(
        _session_tool_manifest_from_definition(
            definitions_by_name[name],
            _SESSION_TOOL_POLICIES[name],
            contract_version=contract_version,
        )
        for name in _SESSION_TOOL_NAMES
    )
    return SessionManifest(contract_version=contract_version, tools=tools)


def session_tool_manifest_result_envelope(
    *,
    status: str,
    summary: str,
    data: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] | list[str] = (),
    errors: tuple[str, ...] | list[str] = (),
    trace_ref: str | None = None,
    contract_version: str = SESSION_CONTRACT_VERSION,
) -> dict[str, Any]:
    """Build the common result shape while always echoing the negotiated contract."""
    negotiated_version = negotiate_session_contract_version(contract_version)
    payload: dict[str, Any] = {
        "contract_version": negotiated_version,
        "status": status,
        "summary": summary,
        "data": dict(data or {}),
        "warnings": list(warnings),
        "errors": list(errors),
    }
    if trace_ref is not None:
        payload["trace_ref"] = trace_ref
    return payload


def session_contract_error_envelope(
    error: SessionContractVersionError,
) -> dict[str, object]:
    return {
        "contract_version": SESSION_CONTRACT_VERSION,
        "status": "incompatible_contract_version",
        "summary": str(error),
        "data": {
            "requested_contract_version": error.requested_version,
            "supported_major": SESSION_CONTRACT_VERSION.split(".", 1)[0],
        },
        "warnings": [],
        "errors": [error.code],
    }


def _session_tool_manifest_from_definition(
    definition: ToolDefinition,
    policy: _SessionToolPolicy,
    *,
    contract_version: str,
) -> SessionToolManifest:
    input_schema = _strict_input_schema(definition.parameters)
    output_schema = _session_tool_output_schema(definition.name, contract_version)
    return SessionToolManifest(
        name=definition.name,
        description=definition.description,
        input_schema=input_schema,
        output_schema=output_schema,
        permission_requirement=policy.permission_requirement,
        risk_class=definition.risk_level,
        side_effect_class=policy.side_effect_class,
        idempotency_class=policy.idempotency_class,
        timeout_seconds=policy.timeout_seconds,
        retry_policy=policy.retry_policy,
        availability_semantics=policy.availability_semantics,
    )


def _session_tool_output_schema(name: str, contract_version: str) -> dict[str, object]:
    return {
        "type": "object",
        "title": f"{name} result",
        "required": [
            "contract_version",
            "status",
            "summary",
            "data",
            "warnings",
            "errors",
        ],
        "properties": {
            "contract_version": {"type": "string", "const": contract_version},
            "status": {"type": "string"},
            "summary": {"type": "string"},
            "data": {"type": "object"},
            "trace_ref": {"type": ["string", "null"]},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "errors": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    }


def _strict_input_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the source schema and close every object with declared properties."""
    copied = _thaw_json(schema)
    if not isinstance(copied, dict):
        raise ValueError("tool input schema must be an object")

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            normalized = {key: visit(item) for key, item in value.items()}
            if normalized.get("type") == "object" and "properties" in normalized:
                normalized.setdefault("additionalProperties", False)
            return normalized
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    normalized_schema = visit(copied)
    if normalized_schema.get("type") != "object":
        raise ValueError("tool input schema root must be an object")
    normalized_schema.setdefault("additionalProperties", False)
    return normalized_schema


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def assistant_message_from_turn(turn: AssistantTurn) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": turn.text,
        "tool_calls": list(turn.tool_calls),
    }
    if turn.raw_provider_content is not None:
        message["_raw_content"] = turn.raw_provider_content
    return message


def tool_results_message(results: list[tuple[str, str, Any]]) -> dict[str, Any]:
    return {
        "role": "user",
        "tool_results": [
            {
                "id": call_id,
                "name": call_name,
                "content": json.dumps(result, ensure_ascii=False, default=str)
                if not isinstance(result, str)
                else result,
            }
            for call_id, call_name, result in results
        ],
    }


def neutral_to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            if "tool_results" in message:
                output.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": item["id"],
                                "content": item["content"],
                            }
                            for item in message["tool_results"]
                        ],
                    }
                )
            else:
                output.append({"role": "user", "content": message.get("content") or ""})
        elif role == "assistant":
            content_blocks: list[dict[str, Any]] = []
            if message.get("content"):
                content_blocks.append({"type": "text", "text": message["content"]})
            for tool_call in message.get("tool_calls", []):
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.arguments,
                    }
                )
            output.append(
                {
                    "role": "assistant",
                    "content": content_blocks or [{"type": "text", "text": ""}],
                }
            )
    return output


def neutral_to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            if "tool_results" in message:
                for item in message["tool_results"]:
                    output.append(
                        {
                            "role": "tool",
                            "tool_call_id": item["id"],
                            "content": item["content"],
                        }
                    )
            else:
                output.append({"role": "user", "content": message.get("content") or ""})
        elif role == "assistant":
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content"),
            }
            if message.get("tool_calls"):
                assistant_message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments),
                        },
                    }
                    for tool_call in message["tool_calls"]
                ]
            output.append(assistant_message)
    return output


def neutral_to_gemini_contents(messages: list[dict[str, Any]]):
    """Convert neutral messages to Gemini Content objects.

    Assistant messages may carry `_raw_content` so the originating provider can
    replay thought-signature-bearing content without lossy reconstruction.
    """
    from google.genai import types as gtypes

    output = []
    for message in messages:
        role = message["role"]
        if role == "user":
            if "tool_results" in message:
                parts = [
                    gtypes.Part(
                        function_response=gtypes.FunctionResponse(
                            name=item["name"],
                            response={"result": item["content"]},
                        )
                    )
                    for item in message["tool_results"]
                ]
                output.append(gtypes.Content(role="user", parts=parts))
            else:
                output.append(
                    gtypes.Content(
                        role="user",
                        parts=[gtypes.Part(text=message.get("content") or "")],
                    )
                )
        elif role == "assistant":
            if "_raw_content" in message:
                output.append(message["_raw_content"])
                continue

            parts = []
            if message.get("content"):
                parts.append(gtypes.Part(text=message["content"]))
            for tool_call in message.get("tool_calls", []):
                parts.append(
                    gtypes.Part(
                        function_call=gtypes.FunctionCall(
                            name=tool_call.name,
                            args=tool_call.arguments,
                        )
                    )
                )
            if not parts:
                parts = [gtypes.Part(text="")]
            output.append(gtypes.Content(role="model", parts=parts))
    return output


def openai_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "input_schema": tool["function"].get(
                "parameters",
                {"type": "object", "properties": {}},
            ),
        }
        for tool in tools
    ]


def openai_tools_to_gemini(tools: list[dict[str, Any]]):
    from google.genai import types as gtypes

    declarations = []
    for tool in tools:
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        declarations.append(
            gtypes.FunctionDeclaration(
                name=function["name"],
                description=function.get("description", ""),
                parameters=_json_schema_to_gemini_schema(parameters),
            )
        )
    return [gtypes.Tool(function_declarations=declarations)]


def _json_schema_to_gemini_schema(schema: dict[str, Any]):
    from google.genai import types as gtypes

    type_map = {
        "string": gtypes.Type.STRING,
        "number": gtypes.Type.NUMBER,
        "integer": gtypes.Type.INTEGER,
        "boolean": gtypes.Type.BOOLEAN,
        "array": gtypes.Type.ARRAY,
        "object": gtypes.Type.OBJECT,
    }
    gemini_type = type_map.get(
        (schema.get("type") or "string").lower(), gtypes.Type.STRING
    )

    properties = None
    if schema.get("properties"):
        properties = {
            name: _json_schema_to_gemini_schema(value)
            for name, value in schema["properties"].items()
        }

    items = None
    if schema.get("items"):
        items = _json_schema_to_gemini_schema(schema["items"])

    return gtypes.Schema(
        type=gemini_type,
        description=schema.get("description"),
        properties=properties,
        required=schema.get("required"),
        items=items,
        enum=schema.get("enum"),
    )


__all__ = [
    "AssistantTurn",
    "SESSION_CONTRACT_VERSION",
    "SESSION_CONTRACT_VERSION_HEADER",
    "SessionActorScope",
    "SessionContractVersionError",
    "SessionManifest",
    "SessionRetryPolicy",
    "SessionToolManifest",
    "SessionToolPermission",
    "ToolCall",
    "ToolDefinition",
    "assistant_message_from_turn",
    "build_session_manifest",
    "negotiate_session_contract_version",
    "neutral_to_anthropic_messages",
    "neutral_to_gemini_contents",
    "neutral_to_openai_messages",
    "openai_tools_to_anthropic",
    "openai_tools_to_gemini",
    "session_contract_error_envelope",
    "session_tool_manifest_result_envelope",
    "tool_results_message",
]
