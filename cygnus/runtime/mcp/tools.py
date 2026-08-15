"""
Cygnus MCP Tools — governed session tool surface for Claude.

The externally callable surface is exactly the canonical twelve governed
session tools (cygnus/integrations/governed_session_tools.py), executed
through the shared manifest-driven dispatcher and denied/listed by
ScopedToolsMiddleware. The legacy wiki / raw-source / direct-mutation
registrations remain only as fail-closed placeholders so the dispatch gate
can reject their names mechanically; their bodies are unreachable.
"""

import functools
from contextvars import ContextVar
from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic.json_schema import WithJsonSchema
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.feedback import FeedbackSignalType
from cygnus.integrations.governed_draft_review_tools import GovernedDraftReviewTools
from cygnus.integrations.governed_drift_tools import (
    GovernedDriftTools,
    normalize_drift_alert_arguments,
)
from cygnus.integrations.governed_feedback_tools import (
    GovernedFeedbackTools,
    normalize_feedback_arguments,
)
from cygnus.integrations.governed_publish_tools import GovernedPublishTools
from cygnus.integrations.governed_session_tools import governed_session_tool_definition
from cygnus.integrations.mcp_auth import ResolvedIdentity
from cygnus.integrations.nanobot_tools import (
    GovernedKnowledgeTools,
    normalize_evidence_search_arguments,
    normalize_knowledge_read_arguments,
    normalize_knowledge_search_arguments,
    normalize_source_trace_arguments,
)
from cygnus.runtime.mcp.logging import _bind_arguments, current_identity, logged_tool
from cygnus.runtime.mcp.permissions import (
    ADMIN_ONLY,
    ANY_AUTHENTICATED,
    CAN_CONTRIBUTE_WIKI,
    CAN_CREATE_WIKI_DIRECT,
    CAN_REVIEW_WIKI,
    kb_tool,
)

_DRIFT_TOOL_PARAMETERS = governed_session_tool_definition(
    "list_drift_alerts"
).parameters["properties"]
_DriftFiltersInput = Annotated[
    object | None,
    WithJsonSchema(_DRIFT_TOOL_PARAMETERS["filters"]),
]
_DriftLimitInput = Annotated[
    object,
    WithJsonSchema(_DRIFT_TOOL_PARAMETERS["limit"]),
]
_FEEDBACK_TOOL_PARAMETERS = governed_session_tool_definition(
    "record_feedback_signal"
).parameters["properties"]
_FeedbackCommandIdInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["command_id"]),
]
_FeedbackSignalTypeInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["signal_type"]),
]
_FeedbackAudienceInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["audience_context"]),
]
_FeedbackObjectIdInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["object_id"]),
]
_FeedbackDraftIdInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["draft_id"]),
]
_FeedbackNotesInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["notes"]),
]
_FeedbackSourceContextInput = Annotated[
    object,
    WithJsonSchema(_FEEDBACK_TOOL_PARAMETERS["source_context_ref"]),
]

_KNOWLEDGE_TOOL_PARAMETERS = governed_session_tool_definition(
    "search_knowledge_objects"
).parameters["properties"]
_KNOWLEDGE_TRACE_PARAMETERS = governed_session_tool_definition(
    "get_source_trace"
).parameters["properties"]
_KnowledgeQueryInput = Annotated[
    object,
    WithJsonSchema(_KNOWLEDGE_TOOL_PARAMETERS["query"]),
]
_KnowledgeAudienceInput = Annotated[
    object,
    WithJsonSchema(_KNOWLEDGE_TOOL_PARAMETERS["audience_context"]),
]
_KnowledgeChannelInput = Annotated[
    object,
    WithJsonSchema(_KNOWLEDGE_TOOL_PARAMETERS["channel"]),
]
_KnowledgeObjectTypesInput = Annotated[
    object | None,
    WithJsonSchema(_KNOWLEDGE_TOOL_PARAMETERS["object_types"]),
]
_KnowledgeLimitInput = Annotated[
    object,
    WithJsonSchema(_KNOWLEDGE_TOOL_PARAMETERS["limit"]),
]
_KnowledgeObjectIdInput = Annotated[
    object,
    WithJsonSchema(_KNOWLEDGE_TRACE_PARAMETERS["object_id"]),
]
_KnowledgeEvidenceFiltersInput = Annotated[
    object | None,
    WithJsonSchema(
        governed_session_tool_definition("search_support_evidence").parameters[
            "properties"
        ]["filters"]
    ),
]

_AUTHENTICATED_REQUEST: ContextVar[object | None] = ContextVar(
    "mcp_authenticated_request",
    default=None,
)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def _get_identity():
    """Resolve the bearer token to a ResolvedIdentity, or return an error string."""
    # A failed or contextless resolution must not inherit an identity from an
    # earlier call sharing this task context.
    current_identity.set(None)
    _AUTHENTICATED_REQUEST.set(None)
    from fastmcp.server.dependencies import get_http_request

    from cygnus.integrations.mcp_auth import MCPAuthService, parse_bearer_token
    from cygnus.runtime.database import async_session_factory

    try:
        request = get_http_request()
        # Shared case-insensitive parser: same credential rules as the /mcp
        # HTTP gate, so malformed forms are rejected uniformly everywhere.
        token = parse_bearer_token(request.headers.get("authorization"))
    except RuntimeError:
        return None, "No HTTP request context available."

    if not token:
        return None, (
            "Authentication required. Configure your MCP token in Claude Desktop:\n"
            '{"mcpServers": {"cygnus": {"url": "...", '
            '"headers": {"Authorization": "Bearer <your-token>"}}}}'
        )

    async with async_session_factory() as session:
        auth_svc = MCPAuthService(session)
        identity = await auth_svc.verify_token(token)
        if identity is None:
            return None, "Invalid or inactive MCP token. Contact your administrator."
        # Only commit when verify_token actually bumped last_connected;
        # otherwise this is a pure read and an empty COMMIT round-trips Redis
        # latency for nothing on every MCP tool call.
        if auth_svc.bumped_last_connected:
            await session.commit()

    current_identity.set(identity)
    _AUTHENTICATED_REQUEST.set(request)
    return identity, None


def _authenticate_before_manifest_dispatch(tool_name: str):
    """Resolve the real MCP actor after schema validation, before policy.

    Production middleware normally authenticates first. Direct FastMCP calls
    bypass that middleware, so this adapter fills the same request context
    without granting an anonymous scope or moving validation after auth.
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from fastmcp.server.dependencies import get_http_request

            from cygnus.substrate.tool_runtime import (
                session_tool_manifest,
                validate_arguments,
            )

            tool = session_tool_manifest().tool(tool_name)
            arguments = _bind_arguments(fn, args, kwargs)
            if validate_arguments(tool.input_schema, arguments):
                # The logged dispatcher owns the deterministic invalid envelope
                # and must reject it before this adapter attempts authentication.
                return await fn(*args, **kwargs)

            try:
                request = get_http_request()
            except RuntimeError:
                request = None

            if (
                request is None
                or current_identity.get() is None
                or _AUTHENTICATED_REQUEST.get() is not request
            ):
                current_identity.set(None)
                _AUTHENTICATED_REQUEST.set(None)
                identity, _error = await _get_identity()
                if identity is not None:
                    # Test/direct adapters may substitute the resolver; bind its
                    # authenticated result exactly as the production resolver does.
                    current_identity.set(identity)
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


async def _load_identity_employee(
    identity: ResolvedIdentity,
    session: AsyncSession,
):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from cygnus.runtime.database.models import Employee

    return (
        await session.execute(
            select(Employee)
            .where(Employee.id == identity.employee_id)
            .options(selectinload(Employee.employee_departments))
        )
    ).scalar_one_or_none()


async def _get_governed_knowledge_tools() -> tuple[
    GovernedKnowledgeTools | None, str | None
]:
    """Resolve one authenticated, permission-filtered knowledge tool surface."""
    identity, error = await _get_identity()
    if error is not None:
        return None, error
    assert identity is not None

    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.routers.governance.dependencies import (
        load_governance_knowledge_snapshot,
    )

    async with async_session_factory() as session:
        employee = await _load_identity_employee(identity, session)
        if employee is None:
            return None, "Authenticated employee no longer exists."
        snapshot = await load_governance_knowledge_snapshot(employee, session)
    return GovernedKnowledgeTools(snapshot), None


async def _get_governed_publish_tools(
    identity: ResolvedIdentity,
    session: AsyncSession,
) -> tuple[GovernedPublishTools | None, str | None]:
    from cygnus.runtime.routers.governance.dependencies import (
        load_governance_knowledge_snapshot,
    )

    employee = await _load_identity_employee(identity, session)
    if employee is None:
        return None, "Authenticated employee no longer exists."
    snapshot = await load_governance_knowledge_snapshot(employee, session)
    return (
        GovernedPublishTools(
            session,
            actor_id=identity.employee_id,
            is_admin=identity.is_admin,
            visible_object_ids=(item.object_id for item in snapshot.objects),
        ),
        None,
    )


async def _get_governed_draft_review_tools(
    identity: ResolvedIdentity,
    session: AsyncSession,
) -> tuple[GovernedDraftReviewTools | None, str | None]:
    employee = await _load_identity_employee(identity, session)
    if employee is None:
        return None, "Authenticated employee no longer exists."
    return GovernedDraftReviewTools(session, actor=employee), None


async def _get_governed_drift_tools(
    identity: ResolvedIdentity,
    session: AsyncSession,
) -> tuple[GovernedDriftTools | None, str | None]:
    """Resolve scoped durable drift truth within this MCP request session."""
    from cygnus.governance.drift_signals import load_drift_signal_provider

    employee = await _load_identity_employee(identity, session)
    if employee is None:
        return None, "Authenticated employee no longer exists."
    provider = await load_drift_signal_provider(session, current_user=employee)
    return GovernedDriftTools(provider), None


async def _get_governed_feedback_tools(
    identity: ResolvedIdentity,
    session: AsyncSession,
) -> tuple[GovernedFeedbackTools | None, str | None]:
    """Resolve feedback writes against the current employee and DB session."""
    employee = await _load_identity_employee(identity, session)
    if employee is None:
        return None, "Authenticated employee no longer exists."
    return GovernedFeedbackTools(session, actor=employee), None


def _structured_tool_error(
    summary: str,
    *,
    code: str = "scope_denied",
    status: str = "denied",
) -> dict[str, Any]:
    """Return one structured error envelope (serialized by the MCP wrapper)."""
    return {
        "status": status,
        "summary": summary,
        "data": {},
        "warnings": [],
        "errors": [code],
    }


def _legacy_tool_disabled(name: str) -> dict[str, Any]:
    """Mechanical fail for the legacy non-governed MCP tool registrations.

    The ScopedToolsMiddleware denies every non-canonical name before dispatch,
    so these bodies are unreachable through /mcp. The registrations stay (the
    deny gate needs the names to exist), but each body fails closed so a
    legacy wiki / raw-source / direct-mutation path can never execute even if
    the gate is bypassed.
    """
    return _structured_tool_error(
        f"Tool '{name}' cannot be called: it is not part of the governed "
        "Cygnus profile. Generic wiki, raw source, and direct mutation tools "
        "are disabled on /mcp for every role.",
        code="not_governed",
        status="denied",
    )


async def _get_allowed_source_ids(
    identity, session: Optional[AsyncSession] = None
) -> Optional[set[str]]:
    """Allowed source UUID strings, or None when access is unrestricted.

    Pass an existing session to avoid opening a second DB connection.
    """
    if identity.is_admin:
        return None
    if identity.allowed_source_ids is None and identity.allowed_knowledge_types is None:
        return None

    from sqlalchemy import select

    from cygnus.integrations.mcp_auth import apply_scope_filter
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source

    async def _query(s: AsyncSession) -> set[str]:
        stmt = select(Source.id).where(Source.status == "ready")
        stmt = apply_scope_filter(stmt, identity)
        result = await s.execute(stmt)
        return {str(r[0]) for r in result.all()}

    if session is not None:
        return await _query(session)

    async with async_session_factory() as session:
        return await _query(session)


# ---------------------------------------------------------------------------
# Permission helpers (shared across review/contribute tools)
# ---------------------------------------------------------------------------


async def _can_review_page(session: AsyncSession, employee, page) -> bool:
    """Fail closed: the legacy wiki review surface is not dispatchable on /mcp.

    This helper only fed the legacy wiki/review tool bodies, which the
    ScopedToolsMiddleware denies before dispatch; the workspace-compat
    permission engine functions it used (`get_workspace_role`,
    `workspace_role_can`) no longer exist. It now refuses every caller so no
    stale path can ever grant access.
    """
    return False


async def _can_contribute_to_page(session: AsyncSession, employee, page) -> bool:
    """Fail closed: the legacy wiki contribute surface is not dispatchable on /mcp.

    This helper only fed the legacy wiki/review tool bodies, which the
    ScopedToolsMiddleware denies before dispatch; the workspace-compat
    permission engine functions it used (`get_workspace_role`,
    `workspace_role_can`) no longer exist. It now refuses every caller so no
    stale path can ever grant access.
    """
    return False


# ---------------------------------------------------------------------------
# Out-of-scope hint (Tier 1 — count + scope name, no titles/content leaked)
# ---------------------------------------------------------------------------


async def _format_oos_hint(session: AsyncSession, oos_hits: list) -> str:
    """Aggregate out-of-scope search hits into a short "ask for access" hint.

    Intentionally leaks ONLY (count, scope_type, scope_name) — never titles
    or summaries — to avoid information disclosure across department or
    workspace boundaries. A page title can itself be sensitive
    (e.g. "Q1 layoffs — Engineering").
    """
    if not oos_hits:
        return ""

    from collections import Counter

    from cygnus.runtime.database.models import Department

    # Group by (scope_type, scope_id) → count.
    buckets: Counter[tuple[str, str | None]] = Counter()
    for page, _sim in oos_hits:
        scope_type = page.scope_type or "global"
        if scope_type == "global":
            continue  # global pages should already be visible; defensive skip
        scope_id = str(page.scope_id) if page.scope_id else None
        buckets[(scope_type, scope_id)] += 1

    if not buckets:
        return ""

    # Resolve human-readable scope labels.
    labels: dict[tuple[str, str | None], str] = {}
    for scope_type, scope_id in buckets.keys():
        label: str | None = None
        if scope_id:
            import uuid as _uuid

            try:
                sid = _uuid.UUID(scope_id)
            except (ValueError, TypeError):
                sid = None
            if sid is not None:
                if scope_type == "department":
                    d = await session.get(Department, sid)
                    label = d.name if d else None
        labels[(scope_type, scope_id)] = label or "(unknown)"

    lines = ["**Out-of-scope matches** — matching page(s) exist outside your access:"]
    for (scope_type, scope_id), count in buckets.most_common():
        label = labels[(scope_type, scope_id)]
        if scope_type == "department":
            lines.append(
                f"- {count} page(s) in department **{label}** — "
                f"contact the {label} department admin to request access."
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP):
    """Register all KB tools on the MCP server."""

    # =========================================================================
    # Governed support object layer — the default path for support questions
    # =========================================================================

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("search_knowledge_objects").name,
        description=governed_session_tool_definition(
            "search_knowledge_objects"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("search_knowledge_objects")
    @logged_tool("search_knowledge_objects", query_arg="query")
    async def search_knowledge_objects(
        query: _KnowledgeQueryInput,
        audience_context: _KnowledgeAudienceInput,
        channel: _KnowledgeChannelInput,
        object_types: _KnowledgeObjectTypesInput = None,
        limit: _KnowledgeLimitInput = 10,
    ) -> dict[str, Any]:
        """Search current delivered objects for one required audience and channel."""
        tools, error = await _get_governed_knowledge_tools()
        if tools is None:
            return _structured_tool_error(error or "Governed retrieval is unavailable.")
        try:
            arguments = normalize_knowledge_search_arguments(
                query=query,
                audience_context=audience_context,
                channel=channel,
                object_types=object_types,
                limit=limit,
            )
        except ValueError as exc:
            return _structured_tool_error(
                str(exc),
                code="invalid_arguments",
                status="invalid",
            )
        return tools.search_knowledge_objects(**arguments)

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("read_knowledge_object").name,
        description=governed_session_tool_definition(
            "read_knowledge_object"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("read_knowledge_object")
    @logged_tool("read_knowledge_object", query_arg="object_id")
    async def read_knowledge_object(
        object_id: _KnowledgeObjectIdInput,
        audience_context: _KnowledgeAudienceInput,
        channel: _KnowledgeChannelInput,
        include_variants: bool = True,
        include_trace: bool = True,
    ) -> dict[str, Any]:
        """Read one current delivered object by immutable ID and audience."""
        tools, error = await _get_governed_knowledge_tools()
        if tools is None:
            return _structured_tool_error(error or "Governed retrieval is unavailable.")
        try:
            arguments = normalize_knowledge_read_arguments(
                object_id=object_id,
                audience_context=audience_context,
                channel=channel,
                include_variants=include_variants,
                include_trace=include_trace,
            )
        except ValueError as exc:
            return _structured_tool_error(
                str(exc),
                code="invalid_arguments",
                status="invalid",
            )
        return tools.read_knowledge_object(**arguments)

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("search_support_evidence").name,
        description=governed_session_tool_definition(
            "search_support_evidence"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("search_support_evidence")
    @logged_tool("search_support_evidence", query_arg="query")
    async def search_support_evidence(
        query: _KnowledgeQueryInput,
        audience_context: _KnowledgeAudienceInput,
        channel: _KnowledgeChannelInput,
        filters: _KnowledgeEvidenceFiltersInput = None,
        limit: _KnowledgeLimitInput = 10,
    ) -> dict[str, Any]:
        """Search only evidence backed by current delivered governed truth."""
        tools, error = await _get_governed_knowledge_tools()
        if tools is None:
            return _structured_tool_error(error or "Governed retrieval is unavailable.")
        try:
            arguments = normalize_evidence_search_arguments(
                query=query,
                audience_context=audience_context,
                channel=channel,
                filters=filters,
                limit=limit,
            )
        except ValueError as exc:
            return _structured_tool_error(
                str(exc),
                code="invalid_arguments",
                status="invalid",
            )
        return tools.search_support_evidence(**arguments)

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("get_source_trace").name,
        description=governed_session_tool_definition("get_source_trace").description,
    )
    @_authenticate_before_manifest_dispatch("get_source_trace")
    @logged_tool("get_source_trace", query_arg="object_id")
    async def get_source_trace(
        object_id: _KnowledgeObjectIdInput,
        audience_context: _KnowledgeAudienceInput,
        channel: _KnowledgeChannelInput,
    ) -> dict[str, Any]:
        """Return a trace only for current delivered governed truth."""
        tools, error = await _get_governed_knowledge_tools()
        if tools is None:
            return _structured_tool_error(error or "Governed retrieval is unavailable.")
        try:
            arguments = normalize_source_trace_arguments(
                object_id=object_id,
                audience_context=audience_context,
                channel=channel,
            )
        except ValueError as exc:
            return _structured_tool_error(
                str(exc),
                code="invalid_arguments",
                status="invalid",
            )
        return tools.get_source_trace(**arguments)

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("list_drift_alerts").name,
        description=governed_session_tool_definition("list_drift_alerts").description,
    )
    @_authenticate_before_manifest_dispatch("list_drift_alerts")
    @logged_tool("list_drift_alerts")
    async def list_drift_alerts(
        filters: _DriftFiltersInput = None,
        limit: _DriftLimitInput = 20,
    ) -> dict[str, Any]:
        """Read current durable release and incident drift alerts in scope."""
        try:
            normalized_filters, normalized_limit = normalize_drift_alert_arguments(
                filters=filters,
                limit=limit,
            )
        except ValueError as exc:
            return _structured_tool_error(
                str(exc),
                code="invalid_arguments",
                status="invalid",
            )

        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_drift_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed drift alerts are unavailable."
                )
            payload = tools.list_drift_alerts(
                filters=normalized_filters,
                limit=normalized_limit,
            )
        return payload

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("record_feedback_signal").name,
        description=governed_session_tool_definition(
            "record_feedback_signal"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("record_feedback_signal")
    @logged_tool("record_feedback_signal", query_arg="object_id")
    async def record_feedback_signal(
        command_id: _FeedbackCommandIdInput,
        signal_type: _FeedbackSignalTypeInput,
        audience_context: _FeedbackAudienceInput,
        object_id: _FeedbackObjectIdInput = None,
        draft_id: _FeedbackDraftIdInput = None,
        notes: _FeedbackNotesInput = None,
        source_context_ref: _FeedbackSourceContextInput = None,
    ) -> dict[str, Any]:
        """Record durable feedback after validating arguments locally."""
        try:
            normalized = normalize_feedback_arguments(
                command_id=command_id,
                signal_type=signal_type,
                audience_context=audience_context,
                object_id=object_id,
                draft_id=draft_id,
                notes=notes,
                source_context_ref=source_context_ref,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            return _structured_tool_error(
                str(exc),
                code="invalid_arguments",
                status="invalid",
            )

        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_feedback_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed feedback is unavailable."
                )
            payload = await tools.record_feedback_signal(
                command_id=normalized.command_id,
                signal_type=FeedbackSignalType(normalized.signal_type).value,
                audience_context=dict(normalized.audience_context),
                object_id=normalized.object_id,
                draft_id=(
                    str(normalized.draft_id)
                    if normalized.draft_id is not None
                    else None
                ),
                notes=normalized.notes,
                source_context_ref=normalized.source_context_ref,
            )
            if (
                payload.get("status") == "success"
                and payload.get("persisted") is True
                and payload.get("replayed") is not True
            ):
                await session.commit()
        return payload

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("validate_publish_policy").name,
        description=governed_session_tool_definition(
            "validate_publish_policy"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("validate_publish_policy")
    @logged_tool("validate_publish_policy", query_arg="draft_id")
    async def validate_publish_policy(
        draft_id: str,
        target_channel: str,
        audience_context: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Validate current persisted publish truth without mutating it."""
        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_publish_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed publication is unavailable."
                )
            payload = await tools.validate_publish_policy(
                draft_id=draft_id,
                target_channel=target_channel,
                audience_context=audience_context,
                expected_version=expected_version,
            )
        return payload

    @kb_tool(
        mcp,
        requires=ADMIN_ONLY,
        name=governed_session_tool_definition("publish_knowledge_object").name,
        description=governed_session_tool_definition(
            "publish_knowledge_object"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("publish_knowledge_object")
    @logged_tool("publish_knowledge_object", query_arg="draft_id")
    async def publish_knowledge_object(
        draft_id: str,
        approval_ref: str,
        approval_digest: str,
        scope_digest: str,
        signal_id: str,
        signal_freshness: str,
        command_id: str,
        action_key: str,
        target_channels: list[str],
        expected_version: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Commit one approved, idempotent durable publication."""
        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_publish_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed publication is unavailable."
                )
            payload = await tools.publish_knowledge_object(
                draft_id=draft_id,
                approval_ref=approval_ref,
                approval_digest=approval_digest,
                scope_digest=scope_digest,
                signal_id=signal_id,
                signal_freshness=signal_freshness,
                command_id=command_id,
                action_key=action_key,
                target_channels=target_channels,
                expected_version=expected_version,
                reason=reason,
            )
            if payload.get("persisted") is True:
                await session.commit()
        return payload

    @kb_tool(
        mcp,
        requires=CAN_CONTRIBUTE_WIKI,
        name=governed_session_tool_definition("propose_knowledge_object").name,
        description=governed_session_tool_definition(
            "propose_knowledge_object"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("propose_knowledge_object")
    @logged_tool("propose_knowledge_object", query_arg="title")
    async def propose_knowledge_object(
        command_id: str,
        proposed_object_type: str,
        title: str,
        input_summary: str,
        audience_context: dict[str, Any],
        scope_type: str | None = None,
        scope_id: str | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        ticket_cluster_ref: str | None = None,
    ) -> dict[str, Any]:
        """Create a durable staged knowledge draft without entering review."""
        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_draft_review_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed draft lifecycle is unavailable."
                )
            payload = await tools.propose_knowledge_object(
                command_id=command_id,
                proposed_object_type=proposed_object_type,
                title=title,
                input_summary=input_summary,
                audience_context=audience_context,
                scope_type=scope_type,
                scope_id=scope_id,
                source_refs=source_refs,
                evidence_refs=evidence_refs,
                ticket_cluster_ref=ticket_cluster_ref,
            )
            if payload.get("persisted") is True:
                await session.commit()
        return payload

    @kb_tool(
        mcp,
        requires=CAN_CONTRIBUTE_WIKI,
        name=governed_session_tool_definition("update_draft_object").name,
        description=governed_session_tool_definition("update_draft_object").description,
    )
    @_authenticate_before_manifest_dispatch("update_draft_object")
    @logged_tool("update_draft_object", query_arg="draft_id")
    async def update_draft_object(
        command_id: str,
        draft_id: str,
        expected_version: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an authored staged draft with optimistic version protection."""
        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_draft_review_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed draft lifecycle is unavailable."
                )
            payload = await tools.update_draft_object(
                command_id=command_id,
                draft_id=draft_id,
                expected_version=expected_version,
                patch=patch,
            )
            if payload.get("persisted") is True:
                await session.commit()
        return payload

    @kb_tool(
        mcp,
        requires=CAN_CONTRIBUTE_WIKI,
        name=governed_session_tool_definition("request_review").name,
        description=governed_session_tool_definition("request_review").description,
    )
    @_authenticate_before_manifest_dispatch("request_review")
    @logged_tool("request_review", query_arg="draft_id")
    async def request_review(
        draft_id: str,
        review_type: str,
        expected_version: int,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Submit an authored staged draft into the durable review queue."""
        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_draft_review_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed draft lifecycle is unavailable."
                )
            payload = await tools.request_review(
                draft_id=draft_id,
                review_type=review_type,
                expected_version=expected_version,
                notes=notes,
            )
            if payload.get("persisted") is True:
                await session.commit()
        return payload

    @kb_tool(
        mcp,
        requires=ANY_AUTHENTICATED,
        name=governed_session_tool_definition("read_review_feedback").name,
        description=governed_session_tool_definition(
            "read_review_feedback"
        ).description,
    )
    @_authenticate_before_manifest_dispatch("read_review_feedback")
    @logged_tool("read_review_feedback", query_arg="draft_id")
    async def read_review_feedback(draft_id: str) -> dict[str, Any]:
        """Read scoped durable review feedback and approval truth."""
        identity, error = await _get_identity()
        if identity is None:
            return _structured_tool_error(error or "Authentication required.")

        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as session:
            tools, error = await _get_governed_draft_review_tools(identity, session)
            if tools is None:
                return _structured_tool_error(
                    error or "Governed draft lifecycle is unavailable."
                )
            payload = await tools.read_review_feedback(draft_id=draft_id)
        return payload

    # =========================================================================
    # Wiki layer — synthesized markdown pages compiled from sources
    # =========================================================================

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("search_wiki", query_arg="query")
    async def search_wiki(query: str, top_k: int = 10) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("search_wiki")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("read_wiki_index")
    async def read_wiki_index() -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("read_wiki_index")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("read_wiki_page", query_arg="slug")
    async def read_wiki_page(slug: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("read_wiki_page")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("list_wiki_pages")
    async def list_wiki_pages(
        page_type: Optional[str] = None,
        knowledge_type: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("list_wiki_pages")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("get_source", query_arg="source_id")
    async def get_source(source_id: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("get_source")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("get_source_outline", query_arg="source_id")
    async def get_source_outline(source_id: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("get_source_outline")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("get_source_pages", query_arg="source_id")
    async def get_source_pages(source_id: str, pages: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("get_source_pages")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("search_source_content", query_arg="query")
    async def search_source_content(
        query: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("search_source_content")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("list_sources")
    async def list_sources(
        status: str = "ready",
        knowledge_type: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("list_sources")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("list_knowledge_types")
    async def list_knowledge_types() -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("list_knowledge_types")

    @kb_tool(mcp, requires=ANY_AUTHENTICATED)
    @logged_tool("get_knowledge_type_docs", query_arg="knowledge_type_slug")
    async def get_knowledge_type_docs(
        knowledge_type_slug: str, limit: int = 10
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("get_knowledge_type_docs")

    @kb_tool(mcp, requires=CAN_CONTRIBUTE_WIKI)
    @logged_tool("propose_wiki_edit", query_arg="slug")
    async def propose_wiki_edit(
        slug: str,
        content_md: str,
        note: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        base_version: Optional[int] = None,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("propose_wiki_edit")

    @kb_tool(mcp, requires=CAN_CREATE_WIKI_DIRECT)
    @logged_tool("edit_wiki_page", query_arg="slug")
    async def edit_wiki_page(
        slug: str,
        content_md: str,
        change_note: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("edit_wiki_page")

    @kb_tool(mcp, requires=CAN_REVIEW_WIKI)
    @logged_tool("list_pending_drafts")
    async def list_pending_drafts(
        workspace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("list_pending_drafts")

    @kb_tool(mcp, requires=CAN_REVIEW_WIKI)
    @logged_tool("review_draft", query_arg="draft_id")
    async def review_draft(draft_id: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("review_draft")

    @kb_tool(mcp, requires=CAN_REVIEW_WIKI)
    @logged_tool("approve_draft", query_arg="draft_id")
    async def approve_draft(
        draft_id: str,
        reviewer_note: Optional[str] = None,
        edited_content_md: Optional[str] = None,
        allow_conflict: bool = False,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("approve_draft")

    @kb_tool(mcp, requires=CAN_REVIEW_WIKI)
    @logged_tool("reject_draft", query_arg="draft_id")
    async def reject_draft(draft_id: str, reviewer_note: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("reject_draft")

    @kb_tool(mcp, requires=CAN_REVIEW_WIKI)
    @logged_tool("request_changes_on_draft", query_arg="draft_id")
    async def request_changes_on_draft(
        draft_id: str, reviewer_note: str
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("request_changes_on_draft")

    @kb_tool(mcp, requires=CAN_CONTRIBUTE_WIKI)
    @logged_tool("resubmit_draft", query_arg="draft_id")
    async def resubmit_draft(
        draft_id: str,
        content_md: str,
        note: Optional[str] = None,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("resubmit_draft")

    @kb_tool(mcp, requires=CAN_CONTRIBUTE_WIKI)
    @logged_tool("withdraw_draft", query_arg="draft_id")
    async def withdraw_draft(draft_id: str) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("withdraw_draft")

    @kb_tool(mcp, requires=CAN_CONTRIBUTE_WIKI)
    @logged_tool("propose_wiki_create", query_arg="slug")
    async def propose_wiki_create(
        slug: str,
        title: str,
        content_md: str,
        page_type: str = "concept",
        knowledge_type_slugs: Optional[list[str]] = None,
        scope_type: str = "global",
        scope_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("propose_wiki_create")

    @kb_tool(mcp, requires=CAN_CREATE_WIKI_DIRECT)
    @logged_tool("create_wiki_page", query_arg="slug")
    async def create_wiki_page(
        slug: str,
        title: str,
        content_md: str,
        page_type: str = "concept",
        knowledge_type_slugs: Optional[list[str]] = None,
        scope_type: str = "global",
        scope_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Disabled: legacy surface, denied by ScopedToolsMiddleware before dispatch."""
        return _legacy_tool_disabled("create_wiki_page")
