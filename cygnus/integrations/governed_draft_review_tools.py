from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any, final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cygnus.domain import AudienceContext, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.governance.ledger import (
    GovernanceEventType,
    GovernanceLedgerConflict,
    event_to_dict,
    governance_state_for_draft_status,
    list_draft_events,
)
from cygnus.governance.tool_command_receipts import (
    ToolCommandReceiptConflict,
    ToolCommandReceiptWrite,
    create_tool_command_receipt,
    replay_tool_command_receipt,
    tool_command_request_fingerprint,
)
from cygnus.retrieval import slugify
from cygnus.review.contributions import (
    DraftVersionConflict,
    InvalidTransition,
    build_initial_draft_content,
    create_wiki_draft,
    submit_wiki_draft,
    update_wiki_draft,
)
from cygnus.runtime.database.models import Employee, Source, WikiPageDraft
from cygnus.runtime.services.audit_service import log_audit
from cygnus.runtime.services.permission_engine import (
    build_document_scope_clause,
    build_wiki_draft_scope_clause,
    get_effective_permissions,
)
from cygnus.substrate.agent_protocol import ToolDefinition


_OBJECT_TYPE_VALUES = frozenset(item.value for item in KnowledgeObjectType)
_REVIEW_TYPE_VALUES = frozenset(
    {"content", "policy", "compliance", "publish_readiness"}
)
_SOURCE_TYPE_VALUES = frozenset(
    {
        "help_center",
        "ticket",
        "chat",
        "release_note",
        "incident",
        "wiki",
        "other",
    }
)
_FRESHNESS_VALUES = frozenset({"fresh", "stale", "unknown"})
_AUDIENCE_KEYS = frozenset(
    {
        "brand",
        "product_line",
        "plan_tier",
        "region",
        "language",
        "product_version",
        "visibility",
    }
)
_REVIEW_EVENT_TYPES = frozenset(
    {
        GovernanceEventType.PROPOSAL_CREATED.value,
        GovernanceEventType.DRAFT_UPDATED.value,
        GovernanceEventType.REVIEW_REQUESTED.value,
        GovernanceEventType.CHANGES_REQUESTED.value,
        GovernanceEventType.REVIEW_RESUBMITTED.value,
        GovernanceEventType.APPROVED.value,
        GovernanceEventType.REJECTED.value,
        GovernanceEventType.WITHDRAWN.value,
    }
)


@final
class GovernedDraftReviewTools:
    """Request-scoped typed adapters over the durable WikiPageDraft lifecycle."""

    __slots__ = ("_actor", "_session")

    def __init__(self, session: AsyncSession, *, actor: Employee) -> None:
        self._session = session
        self._actor = actor

    def _can_create_draft(self) -> bool:
        if self._actor.role == "admin":
            return True
        permissions = get_effective_permissions(self._actor)
        return "wiki:write:all" in permissions or "wiki:write:own_dept" in permissions

    async def propose_knowledge_object(
        self,
        *,
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
        """Persist one scoped, unsubmitted typed knowledge-object draft.

        A contributor limited to ``wiki:write:own_dept`` can never silently
        create global content. Its target scope must be explicit and permitted
        or be derived from a homogeneous set of current visible sources.
        """
        if not self._can_create_draft():
            return _error(
                "denied",
                "Current identity may not create governed drafts.",
                "permission_denied",
            )
        try:
            normalized_command_id = _required_string(
                command_id, label="command_id", max_length=220
            )
            object_type, inferred = _normalize_object_type(proposed_object_type)
            normalized_title = _required_string(title, label="title", max_length=500)
            normalized_summary = _required_string(
                input_summary,
                label="input_summary",
                max_length=50_000,
            )
            content_md = build_initial_draft_content(
                normalized_title, normalized_summary
            )
            normalized_audience = _normalize_audience_context(audience_context)
            normalized_requested_scope = _normalize_requested_scope(
                scope_type, scope_id
            )
            normalized_source_refs = _normalize_source_refs(source_refs or [])
            normalized_evidence_refs = _normalize_evidence_refs(evidence_refs or [])
            normalized_ticket_cluster_ref = _optional_string(
                ticket_cluster_ref,
                label="ticket_cluster_ref",
                max_length=500,
            )
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        requested_scope_type = (
            normalized_requested_scope[0]
            if normalized_requested_scope is not None
            else None
        )
        requested_scope_id = (
            normalized_requested_scope[1]
            if normalized_requested_scope is not None
            else None
        )
        normalized_arguments = {
            "proposed_object_type": object_type,
            "title": normalized_title,
            "input_summary": normalized_summary,
            "audience_context": normalized_audience,
            "scope_type": requested_scope_type,
            "scope_id": requested_scope_id,
            "source_refs": normalized_source_refs,
            "evidence_refs": normalized_evidence_refs,
            "ticket_cluster_ref": normalized_ticket_cluster_ref,
        }
        request_fingerprint = tool_command_request_fingerprint(
            actor_id=self._actor.id,
            tool_name="propose_knowledge_object",
            command_id=normalized_command_id,
            normalized_arguments=normalized_arguments,
        )
        try:
            replay = await replay_tool_command_receipt(
                self._session,
                actor_id=self._actor.id,
                tool_name="propose_knowledge_object",
                command_id=normalized_command_id,
                request_fingerprint=request_fingerprint,
            )
        except ToolCommandReceiptConflict:
            return _receipt_conflict()
        if replay is not None:
            return _replayed_result(replay)

        source_ids = _linked_source_ids(
            normalized_source_refs,
            normalized_evidence_refs,
        )
        source_rows = await self._visible_sources(source_ids)
        if source_rows is None:
            return _unavailable_resource()
        try:
            target_scope_type, target_scope_id = _resolve_proposal_scope(
                actor=self._actor,
                requested_scope=normalized_requested_scope,
                source_rows=source_rows.values(),
            )
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        warnings, completeness = _draft_completeness(
            source_refs=normalized_source_refs,
            evidence_refs=normalized_evidence_refs,
            source_rows=source_rows.values(),
        )
        suggested_metadata = {
            "slug": slugify(normalized_title),
            "title": normalized_title,
            "page_type": "concept",
            "knowledge_type_slugs": [object_type],
            "scope_type": target_scope_type,
            "scope_id": target_scope_id,
        }
        source_metadata = {
            "origin": "nanobot_session",
            "object_type": object_type,
            "audience_context": normalized_audience,
            "source_refs": normalized_source_refs,
            "evidence_refs": normalized_evidence_refs,
            "source_ids": [str(source_id) for source_id in source_ids],
            "ticket_cluster_ref": normalized_ticket_cluster_ref,
            "audience_variants": [],
        }
        draft = await create_wiki_draft(
            self._session,
            page_id=None,
            author_id=self._actor.id,
            content_md=content_md,
            source="mcp_other",
            source_metadata=source_metadata,
            draft_kind="create",
            suggested_metadata=suggested_metadata,
            submit_for_review=False,
        )
        await log_audit(
            self._session,
            self._actor,
            "create",
            "wiki_draft",
            str(draft.id),
            reason=f"governed_session_proposal:{object_type}",
        )
        result = {
            "status": "success",
            "summary": "Durable knowledge-object draft created.",
            "data": {
                **_draft_projection(draft),
                "inferred_object_type": object_type,
                "object_type_inferred": inferred,
                "audience_context": normalized_audience,
                "source_trace": {
                    "source_refs": normalized_source_refs,
                    "evidence_refs": normalized_evidence_refs,
                },
                "draft_completeness": completeness,
                "next_recommended_step": "update_draft_object_or_request_review",
            },
            "trace_ref": f"draft:{draft.id}",
            "persisted": True,
            "rehearsal": False,
            "warnings": warnings,
            "errors": [],
        }
        receipt_write = await create_tool_command_receipt(
            self._session,
            actor_id=self._actor.id,
            tool_name="propose_knowledge_object",
            command_id=normalized_command_id,
            request_fingerprint=request_fingerprint,
            result_payload=result,
        )
        result["receipt_ref"] = receipt_write.receipt_ref
        return result

    async def update_draft_object(
        self,
        *,
        command_id: str,
        draft_id: str,
        expected_version: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply one version-protected mutation to an authored durable draft."""
        try:
            normalized_command_id = _required_string(
                command_id, label="command_id", max_length=220
            )
            parsed_draft_id = _parse_uuid(draft_id, label="draft_id")
            normalized_expected_version = _positive_int(
                expected_version,
                label="expected_version",
            )
            normalized_patch = _normalize_patch(patch)
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        normalized_arguments = {
            "draft_id": str(parsed_draft_id),
            "expected_version": normalized_expected_version,
            "patch": normalized_patch,
        }
        request_fingerprint = tool_command_request_fingerprint(
            actor_id=self._actor.id,
            tool_name="update_draft_object",
            command_id=normalized_command_id,
            normalized_arguments=normalized_arguments,
        )
        try:
            replay = await replay_tool_command_receipt(
                self._session,
                actor_id=self._actor.id,
                tool_name="update_draft_object",
                command_id=normalized_command_id,
                request_fingerprint=request_fingerprint,
            )
        except ToolCommandReceiptConflict:
            return _receipt_conflict()
        if replay is not None:
            return _replayed_result(replay)

        draft = await self._scoped_draft(parsed_draft_id, action="write")
        if draft is None:
            return _unavailable_resource()

        try:
            (
                content_md,
                suggested_metadata,
                source_metadata,
            ) = await self._updated_fields(
                draft,
                normalized_patch,
            )
        except _ScopedResourceNotFound:
            return _unavailable_resource()
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        try:
            event, replayed = await update_wiki_draft(
                self._session,
                draft,
                self._actor,
                expected_version=normalized_expected_version,
                content_md=content_md,
                suggested_metadata=suggested_metadata,
                source_metadata=source_metadata,
            )
        except DraftVersionConflict as exc:
            return _error("conflict", str(exc), "stale_draft")
        except (InvalidTransition, GovernanceLedgerConflict) as exc:
            return _error("conflict", str(exc), "invalid_transition")
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        changed_fields = sorted(normalized_patch)
        result = {
            "status": "success",
            "summary": (
                "Draft update replayed without a new version."
                if replayed
                else "Durable draft updated."
            ),
            "data": {
                **_draft_projection(draft),
                "changed_fields": changed_fields,
                "replayed": replayed,
                "ledger_event": event_to_dict(event) if event is not None else None,
            },
            "trace_ref": f"draft:{draft.id}",
            "persisted": True,
            "rehearsal": False,
            "warnings": _draft_warnings(draft),
            "errors": [],
        }
        receipt_write = await create_tool_command_receipt(
            self._session,
            actor_id=self._actor.id,
            tool_name="update_draft_object",
            command_id=normalized_command_id,
            request_fingerprint=request_fingerprint,
            result_payload=result,
        )
        result["receipt_ref"] = receipt_write.receipt_ref
        return result

    async def request_review(
        self,
        *,
        draft_id: str,
        review_type: str,
        expected_version: int,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Submit a staged draft through the review queue and ledger owner."""
        try:
            parsed_draft_id = _parse_uuid(draft_id, label="draft_id")
            normalized_review_type = _enum_string(
                review_type,
                label="review_type",
                allowed=_REVIEW_TYPE_VALUES,
            )
            normalized_expected_version = _positive_int(
                expected_version,
                label="expected_version",
            )
            normalized_notes = _optional_string(notes, label="notes", max_length=2_000)
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        draft = await self._scoped_draft(parsed_draft_id, action="write")
        if draft is None:
            return _unavailable_resource()

        try:
            event, replayed = await submit_wiki_draft(
                self._session,
                draft,
                self._actor,
                expected_version=normalized_expected_version,
                review_type=normalized_review_type,
                notes=normalized_notes,
            )
        except DraftVersionConflict as exc:
            return _error("conflict", str(exc), "stale_draft")
        except (InvalidTransition, GovernanceLedgerConflict) as exc:
            return _error("conflict", str(exc), "invalid_transition")
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        return {
            "status": "success",
            "summary": (
                "Review request replayed from the durable transition."
                if replayed
                else "Draft submitted to the durable review queue."
            ),
            "data": {
                **_draft_projection(draft),
                "review_request_id": str(event.id),
                "review_type": normalized_review_type,
                "queue_state": "in_review",
                "expected_reviewer_role": "wiki:write:all",
                "replayed": replayed,
                "ledger_event": event_to_dict(event),
            },
            "trace_ref": f"governance-event:{event.id}",
            "persisted": True,
            "rehearsal": False,
            "warnings": _draft_warnings(draft),
            "errors": [],
        }

    async def read_review_feedback(self, *, draft_id: str) -> dict[str, Any]:
        """Read current durable review state and feedback within the caller's scope."""
        try:
            parsed_draft_id = _parse_uuid(draft_id, label="draft_id")
        except ValueError as exc:
            return _error("invalid", str(exc), "invalid_arguments")

        draft = await self._scoped_draft(parsed_draft_id, action="read")
        if draft is None or not self._can_read_feedback(draft):
            return _unavailable_resource()

        events = await list_draft_events(self._session, draft.id)
        approval = next(
            (
                event
                for event in reversed(events)
                if event.event_type
                in {
                    GovernanceEventType.APPROVED.value,
                    GovernanceEventType.STATE_IMPORTED.value,
                }
                and event.to_state == "approved"
            ),
            None,
        )
        feedback: list[dict[str, Any]] = []
        if draft.last_returned_note:
            feedback.append(
                {
                    "kind": "changes_requested",
                    "note": draft.last_returned_note,
                    "revision_round": draft.revision_round,
                }
            )
        if draft.reviewer_note:
            feedback.append(
                {
                    "kind": draft.status,
                    "note": draft.reviewer_note,
                    "reviewed_at": (
                        draft.reviewed_at.isoformat() if draft.reviewed_at else None
                    ),
                    "reviewed_by_id": (
                        str(draft.reviewed_by_id)
                        if draft.reviewed_by_id is not None
                        else None
                    ),
                }
            )
        blocking_issues = [entry["note"] for entry in feedback if entry["note"]]
        if draft.ai_check_status == "failed":
            blocking_issues.append("ai_pre_review_failed")

        return {
            "status": "success",
            "summary": "Durable review feedback loaded.",
            "data": {
                **_draft_projection(draft),
                "review_status": governance_state_for_draft_status(draft.status),
                "review_feedback": feedback,
                "blocking_issues": blocking_issues,
                "approval": {
                    "state": "approved" if approval is not None else "not_approved",
                    "approval_ref": str(approval.id) if approval is not None else None,
                },
                "review_events": [
                    event_to_dict(event)
                    for event in events
                    if event.event_type in _REVIEW_EVENT_TYPES
                ],
            },
            "trace_ref": f"draft:{draft.id}",
            "persisted": True,
            "rehearsal": False,
            "warnings": _draft_warnings(draft),
            "errors": [],
        }

    async def _scoped_draft(
        self,
        draft_id: uuid.UUID,
        *,
        action: str,
    ) -> WikiPageDraft | None:
        statement = (
            select(WikiPageDraft)
            .where(WikiPageDraft.id == draft_id)
            .options(selectinload(WikiPageDraft.page))
        )
        scope_clause = build_wiki_draft_scope_clause(self._actor, action)
        if scope_clause is not None:
            statement = statement.where(scope_clause)
        draft = (await self._session.execute(statement)).scalar_one_or_none()
        if draft is None:
            return None
        source_ids = _draft_scope_source_ids(draft.source_metadata)
        if source_ids is None:
            return None
        source_rows = await self._visible_sources(source_ids)
        if source_rows is None:
            return None
        try:
            _resolve_proposal_scope(
                actor=self._actor,
                requested_scope=_scope_from_draft(draft),
                source_rows=source_rows.values(),
            )
        except ValueError:
            return None
        return draft

    async def _visible_sources(
        self,
        source_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, Source] | None:
        unique_ids = tuple(dict.fromkeys(source_ids))
        if not unique_ids:
            return {}
        statement = (
            select(Source)
            .where(Source.id.in_(unique_ids))
            .options(selectinload(Source.departments))
        )
        scope_clause = build_document_scope_clause(self._actor)
        if scope_clause is not None:
            statement = statement.where(scope_clause)
        rows = tuple((await self._session.execute(statement)).scalars().all())
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(unique_ids):
            return None
        return by_id

    async def _updated_fields(
        self,
        draft: WikiPageDraft,
        patch: dict[str, Any],
    ) -> tuple[
        str | None,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        content_md: str | None = None
        suggested_metadata: dict[str, Any] | None = None
        source_metadata: dict[str, Any] | None = None

        if "content" in patch:
            content_md = _required_string(
                patch["content"],
                label="patch.content",
                max_length=50_000,
            )
        if "title" in patch:
            if draft.draft_kind != "create":
                raise ValueError("patch.title is only supported for create drafts")
            title = _required_string(
                patch["title"], label="patch.title", max_length=500
            )
            suggested_metadata = dict(draft.suggested_metadata or {})
            suggested_metadata["title"] = title
            suggested_metadata["slug"] = slugify(title)
        if "audience_variants" in patch:
            source_metadata = dict(draft.source_metadata or {})
            source_metadata["audience_variants"] = _normalize_audience_variants(
                patch["audience_variants"]
            )
        if "linked_evidence_refs" in patch:
            normalized_evidence_refs = _normalize_evidence_refs(
                patch["linked_evidence_refs"]
            )
            existing_source_refs = _stored_source_refs(draft.source_metadata)
            source_ids = _linked_source_ids(
                existing_source_refs, normalized_evidence_refs
            )
            source_rows = await self._visible_sources(source_ids)
            if source_rows is None:
                raise _ScopedResourceNotFound()
            _resolve_proposal_scope(
                actor=self._actor,
                requested_scope=_scope_from_draft(draft),
                source_rows=source_rows.values(),
            )
            if source_metadata is None:
                source_metadata = dict(draft.source_metadata or {})
            source_metadata["evidence_refs"] = normalized_evidence_refs
            source_metadata["source_ids"] = [str(source_id) for source_id in source_ids]

        return content_md, suggested_metadata, source_metadata

    def _can_read_feedback(self, draft: WikiPageDraft) -> bool:
        if self._actor.role == "admin":
            return True
        if draft.author_id == self._actor.id:
            return True
        return "wiki:write:all" in get_effective_permissions(self._actor)


def _draft_scope_source_ids(
    metadata: dict[str, Any] | None,
) -> tuple[uuid.UUID, ...] | None:
    if metadata is None:
        return ()
    if not isinstance(metadata, dict):
        return None

    raw_source_ids = metadata.get("source_ids", [])
    if raw_source_ids is None:
        raw_source_ids = []
    if not isinstance(raw_source_ids, list):
        return None
    raw_source_ids = list(raw_source_ids)
    for key in ("source_refs", "evidence_refs"):
        entries = metadata.get(key, [])
        if entries is None:
            continue
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict) or "source_id" not in entry:
                return None
            raw_source_ids.append(entry["source_id"])

    source_ids: list[uuid.UUID] = []
    for raw_source_id in raw_source_ids:
        if isinstance(raw_source_id, uuid.UUID):
            source_id = raw_source_id
        else:
            try:
                source_id = _parse_uuid(raw_source_id, label="draft.source_ids")
            except ValueError:
                return None
        if source_id not in source_ids:
            source_ids.append(source_id)
    return tuple(source_ids)


class _ScopedResourceNotFound(Exception):
    pass


def draft_review_tool_definitions() -> tuple[ToolDefinition, ...]:
    return _DRAFT_REVIEW_TOOL_DEFINITIONS


def draft_review_tool_bindings(
    tools: GovernedDraftReviewTools,
) -> tuple[tuple[ToolDefinition, Any], ...]:
    return tuple(
        zip(
            draft_review_tool_definitions(),
            (
                tools.propose_knowledge_object,
                tools.update_draft_object,
                tools.request_review,
                tools.read_review_feedback,
            ),
            strict=True,
        )
    )


def _normalize_object_type(value: object) -> tuple[str, bool]:
    normalized = _required_string(value, label="proposed_object_type", max_length=64)
    if normalized == "auto":
        return KnowledgeObjectType.ANSWER_CARD.value, True
    if normalized not in _OBJECT_TYPE_VALUES:
        allowed = ", ".join(sorted((*_OBJECT_TYPE_VALUES, "auto")))
        raise ValueError(f"proposed_object_type must be one of {allowed}")
    return normalized, False


def _normalize_audience_context(value: object) -> dict[str, str | None]:
    payload = _mapping(value, label="audience_context")
    _reject_unknown(payload, allowed=_AUDIENCE_KEYS, label="audience_context")
    visibility = _enum_string(
        payload.get("visibility"),
        label="audience_context.visibility",
        allowed={item.value for item in Visibility},
    )
    normalized: dict[str, str | None] = {"visibility": visibility}
    for key in (
        "brand",
        "product_line",
        "plan_tier",
        "region",
        "language",
        "product_version",
    ):
        normalized[key] = _optional_string(
            payload.get(key),
            label=f"audience_context.{key}",
            max_length=200,
        )
    _ = AudienceContext(
        visibility=Visibility(visibility),
        brand=normalized["brand"],
        product_line=normalized["product_line"],
        plan=normalized["plan_tier"],
        region=normalized["region"],
        language=normalized["language"],
        product_version=normalized["product_version"],
    )
    return normalized


def _normalize_source_refs(value: object) -> list[dict[str, str]]:
    values = _list(value, label="source_refs", max_length=100)
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(values):
        payload = _mapping(item, label=f"source_refs[{index}]")
        _reject_unknown(
            payload,
            allowed={"source_id", "source_type", "locator"},
            label=f"source_refs[{index}]",
        )
        source_id = _parse_uuid(
            payload.get("source_id"), label=f"source_refs[{index}].source_id"
        )
        normalized.append(
            {
                "source_id": str(source_id),
                "source_type": _enum_string(
                    payload.get("source_type"),
                    label=f"source_refs[{index}].source_type",
                    allowed=_SOURCE_TYPE_VALUES,
                ),
                "locator": _required_string(
                    payload.get("locator"),
                    label=f"source_refs[{index}].locator",
                    max_length=2_000,
                ),
            }
        )
    return normalized


def _normalize_evidence_refs(value: object) -> list[dict[str, object]]:
    values = _list(value, label="evidence_refs", max_length=100)
    normalized: list[dict[str, object]] = []
    for index, item in enumerate(values):
        payload = _mapping(item, label=f"evidence_refs[{index}]")
        _reject_unknown(
            payload,
            allowed={
                "evidence_id",
                "source_id",
                "excerpt_ref",
                "confidence",
                "freshness",
            },
            label=f"evidence_refs[{index}]",
        )
        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError(f"evidence_refs[{index}].confidence must be a number")
        normalized.append(
            {
                "evidence_id": _required_string(
                    payload.get("evidence_id"),
                    label=f"evidence_refs[{index}].evidence_id",
                    max_length=320,
                ),
                "source_id": str(
                    _parse_uuid(
                        payload.get("source_id"),
                        label=f"evidence_refs[{index}].source_id",
                    )
                ),
                "excerpt_ref": _required_string(
                    payload.get("excerpt_ref"),
                    label=f"evidence_refs[{index}].excerpt_ref",
                    max_length=2_000,
                ),
                "confidence": float(confidence),
                "freshness": _enum_string(
                    payload.get("freshness"),
                    label=f"evidence_refs[{index}].freshness",
                    allowed=_FRESHNESS_VALUES,
                ),
            }
        )
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(
                f"evidence_refs[{index}].confidence must be between 0 and 1"
            )
    return normalized


def _normalize_patch(value: object) -> dict[str, Any]:
    payload = _mapping(value, label="patch")
    allowed = {"title", "content", "audience_variants", "linked_evidence_refs"}
    _reject_unknown(payload, allowed=allowed, label="patch")
    if not payload:
        raise ValueError("patch must include at least one supported field")
    return dict(payload)


def _normalize_audience_variants(value: object) -> list[dict[str, Any]]:
    values = _list(value, label="patch.audience_variants", max_length=50)
    return [
        dict(_mapping(item, label=f"patch.audience_variants[{index}]"))
        for index, item in enumerate(values)
    ]


def _stored_source_refs(
    metadata: dict[str, Any] | None,
) -> list[dict[str, str]]:
    raw_refs = (metadata or {}).get("source_refs", [])
    if not isinstance(raw_refs, list):
        return []
    return [
        {"source_id": source_id}
        for item in raw_refs
        if isinstance(item, dict)
        and isinstance((source_id := item.get("source_id")), str)
    ]


_ProposalScope = tuple[str, str | None]


def _normalize_requested_scope(
    scope_type: object,
    scope_id: object,
) -> _ProposalScope | None:
    """Normalize one explicit proposal target, or ``None`` when omitted."""
    if scope_type is None and scope_id is None:
        return None
    if not isinstance(scope_type, str):
        raise ValueError("scope_type is required when scope_id is provided")
    normalized_type = scope_type.strip()
    if normalized_type == "global":
        if scope_id is not None:
            raise ValueError("global scope must not include scope_id")
        return ("global", None)
    if normalized_type != "department":
        raise ValueError("scope_type must be global or department")
    if isinstance(scope_id, uuid.UUID):
        parsed_scope_id = scope_id
    else:
        parsed_scope_id = _parse_uuid(scope_id, label="scope_id")
    return ("department", str(parsed_scope_id))


def _scope_from_source(source: Source) -> _ProposalScope:
    """Return source scope only when explicit scope and department links agree."""
    scope_type = getattr(source, "scope_type", None)
    scope_id = getattr(source, "scope_id", None)
    if scope_type == "global":
        if scope_id is not None or tuple(getattr(source, "departments", ())):
            raise ValueError("referenced source has inconsistent global scope")
        return ("global", None)
    if scope_type != "department":
        raise ValueError("referenced source has unsupported scope")
    if isinstance(scope_id, uuid.UUID):
        parsed_scope_id = scope_id
    else:
        parsed_scope_id = _parse_uuid(scope_id, label="referenced source scope_id")
    declared_department_id = str(parsed_scope_id)
    department_links = tuple(getattr(source, "departments", ()))
    if not any(
        str(getattr(link, "department_id", "")) == declared_department_id
        for link in department_links
    ):
        raise ValueError("referenced source has malformed department scope")
    return ("department", declared_department_id)


def _resolve_proposal_scope(
    *,
    actor: Employee,
    requested_scope: _ProposalScope | None,
    source_rows: Iterable[Source],
) -> _ProposalScope:
    """Resolve one target scope from explicit request and current source truth."""
    source_scopes = {_scope_from_source(source) for source in source_rows}
    if len(source_scopes) > 1:
        raise ValueError("referenced sources do not share one governed scope")
    derived_scope = next(iter(source_scopes), None)
    if (
        requested_scope is not None
        and derived_scope is not None
        and requested_scope != derived_scope
    ):
        raise ValueError("requested scope conflicts with referenced source scope")
    target_scope = requested_scope or derived_scope or ("global", None)

    permissions = get_effective_permissions(actor)
    can_write_all = actor.role == "admin" or "wiki:write:all" in permissions
    if can_write_all:
        return target_scope

    actor_department_ids = {
        str(department_id) for department_id in actor.department_ids
    }
    if target_scope[0] != "department" or target_scope[1] not in actor_department_ids:
        raise ValueError(
            "current actor may create governed drafts only in one of their departments"
        )
    return target_scope


def _scope_from_draft(draft: WikiPageDraft) -> _ProposalScope | None:
    page = getattr(draft, "page", None)
    if page is not None:
        return _normalize_requested_scope(
            getattr(page, "scope_type", None),
            getattr(page, "scope_id", None),
        )
    metadata = getattr(draft, "suggested_metadata", None)
    if not isinstance(metadata, dict):
        return None
    return _normalize_requested_scope(
        metadata.get("scope_type"), metadata.get("scope_id")
    )


def _linked_source_ids(
    source_refs: Iterable[Mapping[str, object]],
    evidence_refs: Iterable[Mapping[str, object]],
) -> tuple[uuid.UUID, ...]:
    source_ids: list[uuid.UUID] = []
    for item in (*source_refs, *evidence_refs):
        source_id = _parse_uuid(item.get("source_id"), label="source_id")
        if source_id not in source_ids:
            source_ids.append(source_id)
    return tuple(source_ids)


def _draft_completeness(
    *,
    source_refs: list[dict[str, str]],
    evidence_refs: list[dict[str, object]],
    source_rows: Iterable[Source],
) -> tuple[list[str], dict[str, object]]:
    warnings: list[str] = []
    score = 60
    if source_refs:
        score += 20
    else:
        warnings.append("missing_source_refs")
    if evidence_refs:
        score += 20
    else:
        warnings.append("missing_evidence_refs")
    if any(source.status != "ready" for source in source_rows):
        warnings.append("referenced_source_not_ready")
    return warnings, {
        "score": score,
        "missing": [warning for warning in warnings if warning.startswith("missing_")],
    }


def _draft_projection(draft: WikiPageDraft) -> dict[str, object]:
    suggested_metadata = draft.suggested_metadata or {}
    source_metadata = draft.source_metadata or {}
    return {
        "draft_id": str(draft.id),
        "draft_version": draft.version,
        "draft_kind": draft.draft_kind,
        "draft_status": draft.status,
        "object_type": source_metadata.get("object_type"),
        "title": suggested_metadata.get("title"),
        "audience_context": source_metadata.get("audience_context"),
        "revision_round": draft.revision_round,
    }


def _draft_warnings(draft: WikiPageDraft) -> list[str]:
    warnings: list[str] = []
    if draft.status == "draft":
        warnings.append("review_not_requested")
    elif draft.status == "pending":
        warnings.append("review_pending")
    if draft.ai_check_status in {"pending", "queued", "running"}:
        warnings.append("ai_pre_review_pending")
    elif draft.ai_check_status == "failed":
        warnings.append("ai_pre_review_failed")
    return warnings


def _parse_uuid(value: object, *, label: str) -> uuid.UUID:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a UUID")
    try:
        return uuid.UUID(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _required_string(value: object, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    return normalized


def _optional_string(value: object, *, label: str, max_length: int) -> str | None:
    if value is None:
        return None
    return _required_string(value, label=label, max_length=max_length)


def _enum_string(value: object, *, label: str, allowed: Iterable[str]) -> str:
    normalized = _required_string(value, label=label, max_length=100)
    allowed_values = frozenset(allowed)
    if normalized not in allowed_values:
        raise ValueError(f"{label} must be one of {', '.join(sorted(allowed_values))}")
    return normalized


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value: object, *, label: str, max_length: int) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    if len(value) > max_length:
        raise ValueError(f"{label} must contain at most {max_length} items")
    return value


def _reject_unknown(
    payload: dict[str, Any], *, allowed: Iterable[str], label: str
) -> None:
    unsupported = sorted(set(payload) - set(allowed))
    if unsupported:
        raise ValueError(
            f"{label} contains unsupported fields: {', '.join(unsupported)}"
        )


def _error(
    status: str,
    summary: str,
    code: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "data": data or {},
        "warnings": [],
        "errors": [code],
    }


def _unavailable_resource() -> dict[str, Any]:
    return _error(
        "not_found",
        "Draft or referenced source not found in the current scope.",
        "not_found",
    )


def _receipt_conflict() -> dict[str, Any]:
    return _error(
        "conflict",
        "Command ID is already bound to different actor-bound input.",
        "idempotency_conflict",
    )


def _replayed_result(
    replay: ToolCommandReceiptWrite,
) -> dict[str, Any]:
    """Return the stored result verbatim with replay identity fields."""
    payload = dict(replay.receipt.result_payload)
    payload["replayed"] = True
    payload["receipt_ref"] = replay.receipt_ref
    return payload


_DRAFT_REVIEW_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="propose_knowledge_object",
        description="Create a durable typed knowledge-object draft without submitting it for review.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 220,
                },
                "proposed_object_type": {
                    "type": "string",
                    "enum": [*sorted(_OBJECT_TYPE_VALUES), "auto"],
                },
                "title": {"type": "string", "minLength": 1, "maxLength": 500},
                "input_summary": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50_000,
                },
                "audience_context": {"type": "object"},
                "scope_type": {"type": "string", "enum": ["global", "department"]},
                "scope_id": {"type": "string", "format": "uuid"},
                "source_refs": {"type": "array", "items": {"type": "object"}},
                "evidence_refs": {"type": "array", "items": {"type": "object"}},
                "ticket_cluster_ref": {"type": "string", "maxLength": 500},
            },
            "required": [
                "command_id",
                "proposed_object_type",
                "title",
                "input_summary",
                "audience_context",
            ],
        },
        risk_level="R1",
    ),
    ToolDefinition(
        name="update_draft_object",
        description="Apply an optimistic-version-checked update to an authored durable draft.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 220,
                },
                "draft_id": {"type": "string", "format": "uuid"},
                "expected_version": {"type": "integer", "minimum": 1},
                "patch": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 50_000,
                        },
                        "audience_variants": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "linked_evidence_refs": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                    "minProperties": 1,
                },
            },
            "required": ["command_id", "draft_id", "expected_version", "patch"],
        },
        risk_level="R1",
    ),
    ToolDefinition(
        name="request_review",
        description="Submit a current-version durable draft into Cygnus review with an idempotent ledger transition.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "draft_id": {"type": "string", "format": "uuid"},
                "review_type": {"type": "string", "enum": sorted(_REVIEW_TYPE_VALUES)},
                "expected_version": {"type": "integer", "minimum": 1},
                "notes": {"type": "string", "maxLength": 2_000},
            },
            "required": ["draft_id", "review_type", "expected_version"],
        },
        risk_level="R1",
    ),
    ToolDefinition(
        name="read_review_feedback",
        description="Read durable review feedback, approval state, and ledger history inside draft scope.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"draft_id": {"type": "string", "format": "uuid"}},
            "required": ["draft_id"],
        },
        risk_level="R0",
    ),
)
