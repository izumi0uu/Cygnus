"""Request-scoped governed adapter for durable consumption feedback."""

from __future__ import annotations

import uuid
from typing import Any, cast, final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain import AudienceContext
from cygnus.governance.feedback import (
    FeedbackCommandConflict,
    FeedbackSignalInput,
    FeedbackSignalType,
    create_feedback_signal,
    feedback_signal_to_dict,
    replay_feedback_signal,
)
from cygnus.governance.feedback_routing import (
    project_feedback_route,
    route_feedback_signal,
)
from cygnus.integrations.nanobot_tools import audience_context_from_payload
from cygnus.retrieval.substrate_provider import wiki_page_to_knowledge_object
from cygnus.runtime.database.models import Employee, WikiPage, WikiPageDraft
from cygnus.runtime.services.audit_service import log_audit
from cygnus.runtime.services.permission_engine import (
    build_wiki_draft_scope_clause,
    build_wiki_scope_clause,
)
from cygnus.substrate.agent_protocol import ToolDefinition


_SIGNAL_TYPE_VALUES = frozenset(item.value for item in FeedbackSignalType)
_AUDIENCE_KEYS = frozenset(
    {
        "visibility",
        "brand",
        "product_line",
        "plan_tier",
        "region",
        "language",
        "product_version",
    }
)


def normalize_feedback_arguments(
    *,
    command_id: object,
    signal_type: object,
    audience_context: object,
    object_id: object = None,
    draft_id: object = None,
    notes: object = None,
    source_context_ref: object = None,
) -> FeedbackSignalInput:
    """Validate tool arguments without resolving any governed resource."""
    normalized_type = _normalize_signal_type(signal_type)
    normalized_context = _normalize_audience_context(audience_context)
    return FeedbackSignalInput(
        command_id=_required_text(command_id, label="command_id", max_length=220),
        signal_type=normalized_type,
        audience_context=normalized_context,
        object_id=_optional_text(object_id, label="object_id", max_length=320),
        draft_id=(
            _parse_uuid(draft_id, label="draft_id") if draft_id is not None else None
        ),
        notes=_optional_text(notes, label="notes", max_length=10_000),
        source_context_ref=_optional_text(
            source_context_ref,
            label="source_context_ref",
            max_length=500,
        ),
    )


@final
class GovernedFeedbackTools:
    """One authenticated request's durable feedback write surface."""

    __slots__ = ("_actor", "_session")

    def __init__(self, session: AsyncSession, *, actor: Employee) -> None:
        self._session = session
        self._actor = actor

    async def record_feedback_signal(
        self,
        *,
        command_id: str,
        signal_type: str,
        audience_context: dict[str, Any],
        object_id: str | None = None,
        draft_id: str | None = None,
        notes: str | None = None,
        source_context_ref: str | None = None,
    ) -> dict[str, Any]:
        """Persist one feedback command and any deterministic durable route."""

        try:
            normalized_input = normalize_feedback_arguments(
                command_id=command_id,
                signal_type=signal_type,
                audience_context=audience_context,
                object_id=object_id,
                draft_id=draft_id,
                notes=notes,
                source_context_ref=source_context_ref,
            )
            normalized_type = FeedbackSignalType(normalized_input.signal_type).value
            normalized_command_id = normalized_input.command_id
            normalized_context = dict(normalized_input.audience_context)
            normalized_object_id = normalized_input.object_id
            normalized_draft_id = cast(uuid.UUID | None, normalized_input.draft_id)
            normalized_notes = normalized_input.notes
            normalized_source_ref = normalized_input.source_context_ref
        except (TypeError, ValueError, AttributeError) as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        try:
            write = await replay_feedback_signal(
                self._session,
                FeedbackSignalInput(
                    command_id=normalized_command_id,
                    signal_type=normalized_type,
                    audience_context=normalized_context,
                    object_id=normalized_object_id,
                    draft_id=normalized_draft_id,
                    notes=normalized_notes,
                    source_context_ref=normalized_source_ref,
                ),
                actor_id=self._actor.id,
            )
        except FeedbackCommandConflict:
            return _idempotency_conflict()
        except (TypeError, ValueError) as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        if write is None:
            page = None
            draft = None
            if normalized_object_id is not None:
                page = await self._scoped_object(normalized_object_id)
                if page is None:
                    return _not_found()

            if normalized_draft_id is not None:
                draft, draft_page = await self._scoped_draft(normalized_draft_id)
                if draft is None:
                    return _not_found()
                if page is not None and (
                    draft_page is None or page.id != draft_page.id
                ):
                    return _reference_conflict()
                if page is None:
                    page = draft_page

                draft_object_id = _draft_object_id(draft, draft_page)
                if (
                    normalized_object_id is not None
                    and normalized_object_id != draft_object_id
                ):
                    return _reference_conflict()
                if normalized_object_id is None:
                    normalized_object_id = draft_object_id

            try:
                signal_input = FeedbackSignalInput(
                    command_id=normalized_command_id,
                    signal_type=normalized_type,
                    audience_context=normalized_context,
                    object_id=normalized_object_id,
                    page_id=page.id if page is not None else None,
                    draft_id=normalized_draft_id,
                    notes=normalized_notes,
                    source_context_ref=normalized_source_ref,
                )
                write = await create_feedback_signal(
                    self._session,
                    signal_input,
                    actor_id=self._actor.id,
                )
            except FeedbackCommandConflict:
                return _idempotency_conflict()
            except (TypeError, ValueError) as exc:
                return _error("invalid", str(exc), "invalid_arguments")
        else:
            normalized_type = write.signal.signal_type
            normalized_object_id = write.signal.object_id
            normalized_draft_id = write.signal.draft_id

        signal = write.signal
        route = await route_feedback_signal(
            self._session,
            signal,
            replayed=write.replayed,
        )
        routing = project_feedback_route(route)
        if not write.replayed:
            audit_reason = (
                f"governed_session:{normalized_type}; "
                f"routing_state={routing.routing_state}"
            )
            if routing.route_ref is not None:
                audit_reason += f"; route_ref={routing.route_ref}"
            await log_audit(
                self._session,
                self._actor,
                "record_feedback_signal",
                "governance_feedback_signal",
                str(signal.id),
                reason=audit_reason,
            )
            await self._session.flush()

        signal_payload = feedback_signal_to_dict(signal)
        return {
            "status": "success",
            "summary": (
                "Feedback command replayed from durable routing truth."
                if write.replayed
                else (
                    "Consumption feedback recorded durably; no routing was queued."
                    if routing.route_ref is None
                    else f"Consumption feedback recorded durably with one {routing.route_kind} route queued."
                )
            ),
            "data": {
                **signal_payload,
                **routing.to_dict(),
                "replayed": write.replayed,
            },
            "signal_id": str(signal.id),
            "command_id": normalized_command_id,
            "replayed": write.replayed,
            "signal_type": normalized_type,
            "object_id": normalized_object_id,
            "draft_id": str(normalized_draft_id)
            if normalized_draft_id is not None
            else None,
            **routing.to_dict(),
            "trace_ref": f"feedback-signal:{signal.id}",
            "persisted": True,
            "rehearsal": False,
            "warnings": [],
            "errors": [],
        }

    async def _scoped_object(self, object_id: str) -> WikiPage | None:
        """Resolve a typed wiki object through the actor's SQL scope."""

        if not object_id.startswith("ko-") or len(object_id) <= 3:
            return None
        statement = select(WikiPage).where(WikiPage.slug == object_id[3:])
        scope_clause = build_wiki_scope_clause(self._actor, action="read")
        if scope_clause is not None:
            statement = statement.where(scope_clause)
        pages = tuple((await self._session.execute(statement.limit(2))).scalars().all())
        if len(pages) != 1:
            return None
        page = pages[0]
        projected = wiki_page_to_knowledge_object(page)
        if projected is None or projected.object_id != object_id:
            return None
        return page

    async def _scoped_draft(
        self,
        draft_id: uuid.UUID,
    ) -> tuple[WikiPageDraft | None, WikiPage | None]:
        """Resolve a draft and its target page inside SQL wiki scope."""

        statement = select(WikiPageDraft).where(WikiPageDraft.id == draft_id)
        scope_clause = build_wiki_draft_scope_clause(self._actor, action="read")
        if scope_clause is not None:
            statement = statement.where(scope_clause)
        draft = (await self._session.execute(statement)).scalar_one_or_none()
        if draft is None:
            return None, None

        page: WikiPage | None = None
        if draft.page_id is not None:
            page_statement = select(WikiPage).where(WikiPage.id == draft.page_id)
            page_scope = build_wiki_scope_clause(self._actor, action="read")
            if page_scope is not None:
                page_statement = page_statement.where(page_scope)
            page = (await self._session.execute(page_statement)).scalar_one_or_none()
            if page is None:
                return None, None
            if wiki_page_to_knowledge_object(page) is None:
                return None, None
        return draft, page


def feedback_tool_definitions() -> tuple[ToolDefinition, ...]:
    return _FEEDBACK_TOOL_DEFINITIONS


def feedback_tool_bindings(
    tools: GovernedFeedbackTools,
) -> tuple[tuple[ToolDefinition, Any], ...]:
    definition = feedback_tool_definitions()[0]
    return ((definition, tools.record_feedback_signal),)


def _normalize_signal_type(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("signal_type must be a nonblank string")
    normalized = value.strip()
    if normalized not in _SIGNAL_TYPE_VALUES:
        raise ValueError(
            "signal_type must be one of " + ", ".join(sorted(_SIGNAL_TYPE_VALUES))
        )
    return normalized


def _normalize_audience_context(value: object) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise ValueError("audience_context must be an object")
    unknown = sorted(set(value) - _AUDIENCE_KEYS)
    if unknown:
        raise ValueError(
            "audience_context contains unsupported fields: " + ", ".join(unknown)
        )
    try:
        context = audience_context_from_payload(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(str(exc)) from exc
    if context is None:
        raise ValueError("audience_context.visibility is required")
    return _audience_payload(context)


def _audience_payload(context: AudienceContext) -> dict[str, str | None]:
    return {
        "visibility": context.visibility.value,
        "brand": context.brand,
        "product_line": context.product_line,
        "plan_tier": context.plan,
        "region": context.region,
        "language": context.language,
        "product_version": context.product_version,
    }


def _draft_object_id(
    draft: WikiPageDraft,
    page: WikiPage | None,
) -> str | None:
    if page is not None:
        projected = wiki_page_to_knowledge_object(page)
        return projected.object_id if projected is not None else None
    metadata = draft.suggested_metadata
    if not isinstance(metadata, dict):
        return None
    slug = metadata.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        return None
    return f"ko-{slug.strip()}"


def _parse_uuid(value: object, *, label: str) -> uuid.UUID:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a UUID")
    try:
        return uuid.UUID(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _required_text(value: object, *, label: str, max_length: int) -> str:
    normalized = _optional_text(value, label=label, max_length=max_length)
    if normalized is None:
        raise ValueError(f"{label} is required")
    return normalized


def _optional_text(
    value: object,
    *,
    label: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank when provided")
    if len(normalized) > max_length:
        raise ValueError(f"{label} exceeds {max_length} characters")
    return normalized


def _error(
    status: str,
    summary: str,
    code: str,
    *,
    data: dict[str, object] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "data": data or {},
        "warnings": [],
        "errors": [code],
    }


def _not_found() -> dict[str, Any]:
    return _error(
        "not_found",
        "Feedback resource is not available in the current scope.",
        "not_found",
    )


def _reference_conflict() -> dict[str, Any]:
    return _error(
        "conflict",
        "Feedback references do not identify the same governed resource.",
        "reference_mismatch",
    )


def _idempotency_conflict() -> dict[str, Any]:
    return _error(
        "conflict",
        "Feedback command ID is already bound to different input.",
        "idempotency_conflict",
    )


_FEEDBACK_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="record_feedback_signal",
        description=(
            "Record one durable support-consumption feedback command and "
            "persist its deterministic review or refresh route when required."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 220,
                },
                "signal_type": {
                    "type": "string",
                    "enum": sorted(_SIGNAL_TYPE_VALUES),
                },
                "audience_context": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "visibility": {
                            "type": "string",
                            "enum": ["internal", "external"],
                        },
                        "brand": {"type": "string", "minLength": 1, "maxLength": 200},
                        "product_line": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "plan_tier": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "region": {"type": "string", "minLength": 1, "maxLength": 200},
                        "language": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "product_version": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                    },
                    "required": ["visibility"],
                },
                "object_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "draft_id": {"type": "string", "format": "uuid"},
                "notes": {"type": "string", "minLength": 1, "maxLength": 10_000},
                "source_context_ref": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            },
            "required": ["command_id", "signal_type", "audience_context"],
        },
        risk_level="R1",
    ),
)


__all__ = [
    "GovernedFeedbackTools",
    "feedback_tool_bindings",
    "feedback_tool_definitions",
    "normalize_feedback_arguments",
]
