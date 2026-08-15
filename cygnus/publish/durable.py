from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.evidence.freshness import freshness_gate
from cygnus.governance.approval_guards import (
    approval_digest,
    publish_scope_digest,
)
from cygnus.governance.audience_bindings import (
    AudienceBindingLifecycle,
    list_audience_bindings,
    publish_binding_from_record,
    publish_conflicts_from_records,
)
from cygnus.governance.ledger import (
    GovernanceEventType,
    append_draft_event,
    dedupe_strings,
    get_approval_event,
    get_latest_draft_event,
    lock_draft_aggregate,
    lock_governance_command,
)
from cygnus.publish.actions import PublishGovernanceResult
from cygnus.publish.delivery import (
    DeliveryStatus,
    binding_version_refs,
    build_canonical_delivery_payload,
    canonical_delivery_digest,
    delivery_to_dict,
    list_propagation_deliveries,
)
from cygnus.publish.preview import (
    PublishActionType,
    PublishBinding,
    PublishConflict,
    PublishPreviewCandidate,
    build_publish_blast_radius_preview,
)
from cygnus.publish.propagation import PropagationStatus
from cygnus.observability import current_request_id, current_traceparent
from cygnus.retrieval.substrate_provider import wiki_page_to_knowledge_object
from cygnus.runtime.config import get_settings
from cygnus.runtime.database.models import (
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
    GovernanceSignal,
    Source,
    WikiPage,
    WikiPageDraft,
)


def _source_scope_state(source: Source) -> tuple[uuid.UUID, str]:
    """Canonical source status/freshness snapshot signed into publish scope."""
    from cygnus.evidence.freshness import resolve_source_freshness

    def _iso(value: object) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else ""

    state = "|".join(
        (
            str(getattr(source, "status", "")),
            resolve_source_freshness(source).value,
            str(getattr(source, "freshness_state", "")),
            str(getattr(source, "freshness_actor_id", "")),
            str(getattr(source, "freshness_reason", "")),
            _iso(getattr(source, "freshness_attested_at", None)),
            _iso(getattr(source, "freshness_expires_at", None)),
            _iso(getattr(source, "updated_at", None)),
        )
    )
    return source.id, state


def _ordered_source_scope_state(
    sources: tuple[Source, ...],
) -> tuple[tuple[uuid.UUID, str], ...]:
    """Return deterministic source snapshots for preview/apply locking."""
    return tuple(
        _source_scope_state(source)
        for source in sorted(sources, key=lambda item: str(item.id))
    )


class DurablePublishNotFound(LookupError):
    pass


class DurablePublishDenied(ValueError):
    pass


class DurablePublishConflict(ValueError):
    pass


_FRESHNESS_ATTESTATIONS = frozenset({"fresh", "stale", "unknown"})


def _require_digest(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} must be a sha256 hex digest")
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class DurablePublishCommand:
    draft_id: uuid.UUID
    approval_ref: uuid.UUID
    approval_digest: str
    scope_digest: str
    signal_id: uuid.UUID
    signal_freshness: str
    command_id: str
    action_key: str
    target_channels: tuple[str, ...]
    expected_version: int
    reason: str | None = None

    def __post_init__(self) -> None:
        command_id = self.command_id.strip()
        action_key = self.action_key.strip()
        reason = self.reason.strip() if self.reason is not None else None
        if not command_id:
            raise ValueError("command_id must not be blank")
        if len(command_id) > 200:
            raise ValueError("command_id must not exceed 200 characters")
        if not action_key:
            raise ValueError("action_key must not be blank")
        if reason == "":
            raise ValueError("reason must not be blank when provided")
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        signal_freshness = self.signal_freshness.strip()
        if signal_freshness not in _FRESHNESS_ATTESTATIONS:
            raise ValueError("signal_freshness must be one of: fresh, stale, unknown")
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "action_key", action_key)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "signal_freshness", signal_freshness)
        object.__setattr__(
            self,
            "approval_digest",
            _require_digest(self.approval_digest, label="approval_digest"),
        )
        object.__setattr__(
            self,
            "scope_digest",
            _require_digest(self.scope_digest, label="scope_digest"),
        )
        object.__setattr__(
            self,
            "target_channels",
            dedupe_strings(self.target_channels, label="target channel"),
        )
        if not self.target_channels:
            raise ValueError("target_channels must not be empty")

    @property
    def request_fingerprint(self) -> str:
        payload: dict[str, object] = {
            "draft_id": str(self.draft_id),
            "approval_ref": str(self.approval_ref),
            "approval_digest": self.approval_digest,
            "scope_digest": self.scope_digest,
            "signal_id": str(self.signal_id),
            "signal_freshness": self.signal_freshness,
            "action_key": self.action_key,
            "target_channels": list(self.target_channels),
            "expected_version": self.expected_version,
            "reason": self.reason,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()


async def durable_publish_command_for_signal(
    session: AsyncSession,
    *,
    signal: GovernanceSignal,
    action_key: str | None = None,
) -> dict[str, object] | None:
    """Return an executable envelope only for fully qualified durable truth."""
    from cygnus.review.intake import is_feedback_derived_signal_type

    if is_feedback_derived_signal_type(getattr(signal, "signal_type", None)):
        return None
    if signal.page_id is None or signal.status != "active":
        return None
    page = await session.get(WikiPage, signal.page_id)
    if page is None:
        return None
    knowledge_object = wiki_page_to_knowledge_object(page)
    if knowledge_object is None or knowledge_object.object_id != signal.object_ref:
        return None

    source_ids = tuple(dict.fromkeys(page.source_ids or ()))
    if not source_ids:
        return None
    source_rows = (
        (
            await session.execute(
                select(Source)
                .where(Source.id.in_(source_ids))
                .order_by(Source.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    source_by_id = {source.id: source for source in source_rows}
    if any(source_id not in source_by_id for source_id in source_ids):
        return None
    sources = tuple(source_by_id[source_id] for source_id in source_ids)
    if any(source.status != "ready" for source in sources):
        return None

    draft = (
        await session.execute(
            select(WikiPageDraft)
            .where(
                WikiPageDraft.page_id == page.id,
                WikiPageDraft.status == "approved",
            )
            .order_by(
                WikiPageDraft.reviewed_at.desc().nullslast(),
                WikiPageDraft.created_at.desc(),
                WikiPageDraft.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if draft is None:
        return None
    approval = (
        await session.execute(
            select(GovernanceLedgerEvent)
            .where(
                GovernanceLedgerEvent.draft_id == draft.id,
                GovernanceLedgerEvent.to_state == "approved",
                GovernanceLedgerEvent.event_type.in_(
                    (
                        GovernanceEventType.APPROVED.value,
                        GovernanceEventType.STATE_IMPORTED.value,
                    )
                ),
            )
            .order_by(GovernanceLedgerEvent.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if approval is None:
        return None
    approval_payload = approval.payload or {}
    stored_approval_digest = approval_payload.get("approval_digest")
    if not isinstance(stored_approval_digest, str) or not stored_approval_digest:
        # No optional legacy bypass: an approval without the canonical digest
        # never compiles a durable publish command.
        return None

    binding_rows = await list_audience_bindings(
        session,
        page_id=page.id,
        object_ref=signal.object_ref,
        lifecycle_state=AudienceBindingLifecycle.ACTIVE,
    )
    if not binding_rows:
        return None
    target_channels = tuple(dict.fromkeys(row.channel for row in binding_rows))
    previous_publication = await latest_publication_for_object(
        session, signal.object_ref
    )
    selected_action = (
        action_key.strip()
        if action_key is not None
        else "republish"
        if previous_publication is not None
        else "publish"
    )
    if selected_action not in {
        "publish",
        "republish",
        "restrict_publish",
        "hold_external",
        "republish_internal_only",
    }:
        return None
    if previous_publication is None and selected_action != "publish":
        return None

    source_state = _ordered_source_scope_state(sources)
    scope_digest = publish_scope_digest(
        approval_ref=approval.id,
        approval_digest_value=stored_approval_digest,
        object_version=page.version,
        binding_rows=binding_rows,
        source_state=source_state,
        signal_freshness=signal.freshness,
        action_key=selected_action,
        target_channels=target_channels,
        signal_id=signal.id,
        signal_status=signal.status,
    )

    identity = {
        "signal_id": str(signal.id),
        "draft_id": str(draft.id),
        "approval_ref": str(approval.id),
        "approval_digest": stored_approval_digest,
        "scope_digest": scope_digest,
        "object_version": page.version,
        "signal_freshness": signal.freshness,
        "signal_status": signal.status,
        "action_key": selected_action,
        "bindings": [
            {"binding_key": row.binding_key, "version": row.version}
            for row in binding_rows
        ],
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "draft_id": str(draft.id),
        "approval_ref": str(approval.id),
        "approval_digest": stored_approval_digest,
        "scope_digest": scope_digest,
        "signal_id": str(signal.id),
        "signal_freshness": signal.freshness,
        "command_id": f"publish-preview:{digest}",
        "action_key": selected_action,
        "target_channels": list(target_channels),
        "reason": signal.reason,
        "expected_version": page.version,
    }


async def persisted_publish_candidate_for_signal(
    session: AsyncSession,
    *,
    signal: GovernanceSignal,
) -> PublishPreviewCandidate | None:
    """Project a preview candidate only from persisted page, binding, and publication truth."""
    from cygnus.review.intake import is_feedback_derived_signal_type

    if is_feedback_derived_signal_type(getattr(signal, "signal_type", None)):
        return None
    if signal.page_id is None or signal.status != "active":
        return None
    page = await session.get(WikiPage, signal.page_id)
    if page is None:
        return None
    knowledge_object = wiki_page_to_knowledge_object(page)
    if knowledge_object is None or knowledge_object.object_id != signal.object_ref:
        return None

    binding_rows = await list_audience_bindings(
        session,
        page_id=page.id,
        object_ref=signal.object_ref,
        lifecycle_state=AudienceBindingLifecycle.ACTIVE,
    )
    target_bindings = tuple(
        dict.fromkeys(publish_binding_from_record(binding) for binding in binding_rows)
    )
    if not target_bindings:
        return None

    previous_publication = await latest_publication_for_object(
        session,
        signal.object_ref,
    )
    current_bindings = (
        _bindings_from_candidate(previous_publication.candidate)
        if previous_publication is not None
        else ()
    )
    return PublishPreviewCandidate(
        object_id=knowledge_object.object_id,
        object_type=knowledge_object.object_type,
        title=knowledge_object.title,
        action_type=(
            PublishActionType.REPUBLISH
            if previous_publication is not None
            else PublishActionType.PUBLISH
        ),
        target_audiences=tuple(
            dict.fromkeys(binding.audience_filter for binding in target_bindings)
        ),
        target_channels=tuple(
            dict.fromkeys(binding.channel for binding in target_bindings)
        ),
        target_bindings=target_bindings,
        current_bindings=current_bindings,
        blocked_bindings=publish_conflicts_from_records(binding_rows),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PropagationUpdateCommand:
    publication_id: uuid.UUID
    surface_id: str
    status: PropagationStatus
    expected_version: int
    command_id: str
    reason: str
    follow_up_commands: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        surface_id = self.surface_id.strip()
        command_id = self.command_id.strip()
        reason = self.reason.strip()
        if not surface_id:
            raise ValueError("surface_id must not be blank")
        if not command_id:
            raise ValueError("command_id must not be blank")
        if len(command_id) > 200:
            raise ValueError("command_id must not exceed 200 characters")
        if not reason:
            raise ValueError("reason must not be blank")
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        object.__setattr__(self, "surface_id", surface_id)
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "follow_up_commands",
            dedupe_strings(self.follow_up_commands, label="follow-up command"),
        )

    @property
    def request_fingerprint(self) -> str:
        payload = {
            "publication_id": str(self.publication_id),
            "surface_id": self.surface_id,
            "status": self.status.value,
            "expected_version": self.expected_version,
            "reason": self.reason,
            "follow_up_commands": list(self.follow_up_commands),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()


async def apply_durable_publish(
    session: AsyncSession,
    *,
    command: DurablePublishCommand,
    actor_id: uuid.UUID,
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> dict[str, object]:
    """Execute and atomically stage one qualified durable publication."""
    effective_correlation = correlation_id or current_request_id()
    effective_traceparent = traceparent or current_traceparent()
    correlation_uuid = None
    if effective_correlation:
        try:
            correlation_uuid = uuid.UUID(str(effective_correlation))
        except (TypeError, ValueError):
            correlation_uuid = None
    await lock_draft_aggregate(session, command.draft_id)
    await lock_governance_command(session, f"publish:{command.command_id}")

    existing = (
        await session.execute(
            select(GovernancePublication).where(
                GovernancePublication.command_id == command.command_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.draft_id != command.draft_id
            or existing.request_fingerprint != command.request_fingerprint
        ):
            raise DurablePublishConflict(
                f"command_id={command.command_id} is already bound to a different publish request"
            )
        existing_propagations = await list_publication_propagations(
            session, existing.id
        )
        existing_deliveries = await list_propagation_deliveries(
            session, tuple(item.id for item in existing_propagations)
        )
        return durable_publication_result(
            existing,
            propagations=existing_propagations,
            deliveries=existing_deliveries,
            replayed=True,
        )

    draft = (
        await session.execute(
            select(WikiPageDraft).where(WikiPageDraft.id == command.draft_id)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise DurablePublishNotFound(f"draft_id={command.draft_id} was not found")
    if draft.status != "approved":
        raise DurablePublishDenied(
            f"draft_id={command.draft_id} is not approved (status={draft.status})"
        )
    approval_event = await get_approval_event(
        session,
        draft_id=draft.id,
        approval_ref=command.approval_ref,
    )
    if approval_event is None:
        raise DurablePublishDenied(
            f"approval_ref={command.approval_ref} is not an approval for draft_id={draft.id}"
        )
    if draft.page_id is None:
        raise DurablePublishDenied("approved draft has no materialized WikiPage")
    page = (
        await session.execute(
            select(WikiPage).where(WikiPage.id == draft.page_id).with_for_update()
        )
    ).scalar_one_or_none()
    if page is None:
        raise DurablePublishDenied("approved draft has no materialized WikiPage")
    if page.version != command.expected_version:
        raise DurablePublishConflict(
            "object version conflict: "
            f"expected {command.expected_version}, current {page.version}"
        )

    approval_payload = approval_event.payload or {}
    stored_approval_digest = approval_payload.get("approval_digest")
    if not isinstance(stored_approval_digest, str) or not stored_approval_digest:
        raise DurablePublishDenied(
            f"approval_ref={command.approval_ref} has no canonical approval digest; "
            "legacy approvals cannot publish"
        )
    current_approval_digest = approval_digest(
        draft=draft,
        page=page,
        final_content=page.content_md,
        reviewer_id=draft.reviewed_by_id,
        reviewed_at=draft.reviewed_at,
        reviewer_note=draft.reviewer_note,
    )
    if (
        current_approval_digest != stored_approval_digest
        or current_approval_digest != command.approval_digest
    ):
        raise DurablePublishConflict(
            "approval content drift: the reviewed draft/page revision no longer "
            "matches the approved content, sources, or review metadata"
        )

    source_ids = tuple(dict.fromkeys(page.source_ids or ()))
    if not source_ids:
        raise DurablePublishDenied(
            "published objects must reference at least one source"
        )
    sources = tuple(
        (
            await session.execute(
                select(Source)
                .where(Source.id.in_(source_ids))
                .order_by(Source.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    source_by_id = {source.id: source for source in sources}
    missing_source_ids = tuple(
        source_id for source_id in source_ids if source_id not in source_by_id
    )
    non_ready_source_ids = tuple(
        source_id
        for source_id in source_ids
        if source_id in source_by_id and source_by_id[source_id].status != "ready"
    )
    if missing_source_ids or non_ready_source_ids:
        raise DurablePublishDenied(
            "published objects require every linked source to exist and be ready"
        )
    sources = tuple(source_by_id[source_id] for source_id in source_ids)
    freshness_gate_result = freshness_gate(sources)
    if not freshness_gate_result.passed:
        raise DurablePublishDenied(
            "published objects require every linked source to carry an explicit, "
            "unexpired FRESH attestation; "
            + "; ".join(freshness_gate_result.violations)
        )

    evidence_ids = tuple(f"ev-src-{source_id}" for source_id in source_ids)
    knowledge_object = wiki_page_to_knowledge_object(
        page,
        evidence_ids=evidence_ids,
    )
    if knowledge_object is None:
        raise DurablePublishDenied(
            "approved WikiPage must declare one supported knowledge object type"
        )

    active_binding_rows = tuple(
        (
            await session.execute(
                select(GovernanceAudienceBinding)
                .where(
                    GovernanceAudienceBinding.page_id == page.id,
                    GovernanceAudienceBinding.object_ref == knowledge_object.object_id,
                    GovernanceAudienceBinding.lifecycle_state
                    == AudienceBindingLifecycle.ACTIVE.value,
                )
                .order_by(GovernanceAudienceBinding.binding_key)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not active_binding_rows:
        raise DurablePublishDenied(
            "durable publish requires at least one explicit active audience binding"
        )

    signal = (
        (
            await session.execute(
                select(GovernanceSignal)
                .where(GovernanceSignal.id == command.signal_id)
                .with_for_update()
            )
        )
        .scalars()
        .one_or_none()
    )
    if signal is None:
        raise DurablePublishDenied(
            f"signal_id={command.signal_id} freshness attestation was not found"
        )
    if signal.page_id != page.id or signal.object_ref != knowledge_object.object_id:
        raise DurablePublishDenied(
            f"signal_id={command.signal_id} does not attest the requested publish object"
        )
    if signal.status != "active":
        raise DurablePublishConflict(
            "signal lifecycle drift: "
            f"signal_id={command.signal_id} is no longer active (status={signal.status})"
        )
    if signal.freshness != command.signal_freshness:
        raise DurablePublishConflict(
            "freshness attestation drift: "
            f"signal_id={command.signal_id} freshness changed from "
            f"{command.signal_freshness} to {signal.freshness}"
        )

    source_state = _ordered_source_scope_state(sources)
    current_scope_digest = publish_scope_digest(
        approval_ref=approval_event.id,
        approval_digest_value=stored_approval_digest,
        object_version=page.version,
        binding_rows=active_binding_rows,
        source_state=source_state,
        signal_freshness=signal.freshness,
        action_key=command.action_key,
        target_channels=command.target_channels,
        signal_id=signal.id,
        signal_status=signal.status,
    )
    if current_scope_digest != command.scope_digest:
        raise DurablePublishConflict(
            "publish scope drift: the previewed approval, object version, "
            "bindings, freshness attestations, or action/targets no longer match "
            "current persisted truth"
        )

    active_channels = {binding.channel for binding in active_binding_rows}
    missing_channels = tuple(
        channel for channel in command.target_channels if channel not in active_channels
    )
    if missing_channels:
        raise DurablePublishDenied(
            "durable publish target channels have no active audience binding: "
            + ", ".join(missing_channels)
        )
    requested_binding_rows = tuple(
        binding
        for binding in active_binding_rows
        if binding.channel in command.target_channels
    )
    target_bindings = tuple(
        dict.fromkeys(
            publish_binding_from_record(binding) for binding in requested_binding_rows
        )
    )
    if not target_bindings:
        raise DurablePublishDenied(
            "durable publish has no explicit binding for the requested channels"
        )

    previous_publication = await latest_publication_for_object(
        session,
        knowledge_object.object_id,
    )
    if previous_publication is None and command.action_key != "publish":
        raise DurablePublishDenied(
            "the first durable command for an object must use action_key=publish"
        )
    current_bindings = (
        _bindings_from_candidate(previous_publication.candidate)
        if previous_publication is not None
        else ()
    )
    action_type = (
        PublishActionType.PUBLISH
        if previous_publication is None
        else PublishActionType.REPUBLISH
    )
    target_audiences = tuple(
        dict.fromkeys(binding.audience_filter for binding in target_bindings)
    )
    candidate = PublishPreviewCandidate(
        object_id=knowledge_object.object_id,
        object_type=knowledge_object.object_type,
        title=knowledge_object.title,
        action_type=action_type,
        target_audiences=target_audiences,
        target_channels=command.target_channels,
        target_bindings=target_bindings,
        current_bindings=current_bindings,
        blocked_bindings=publish_conflicts_from_records(requested_binding_rows),
    )
    result = execute_durable_publish_action(
        candidate,
        command.action_key,
        reason=command.reason,
    )

    publication_id = uuid.uuid4()
    delivery_payload = build_canonical_delivery_payload(
        publication_id=publication_id,
        command_id=command.command_id,
        approval_ref=approval_event.id,
        approval_sequence=approval_event.sequence,
        object_ref=knowledge_object.object_id,
        object_type=knowledge_object.object_type.value,
        object_version=page.version,
        action_key=command.action_key,
        target_channels=command.target_channels,
        binding_rows=requested_binding_rows,
        source_ids=source_ids,
        content_md=page.content_md,
    )
    desired_digest = canonical_delivery_digest(delivery_payload)
    effective_bindings = result.updated_candidate.target_bindings
    previous_object_status = page.status
    effective_object_status = (
        previous_object_status
        if previous_object_status == "evergreen"
        else "mature"
        if effective_bindings
        else "developing"
    )
    publish_event = await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.PUBLISHED,
        from_state="published" if current_bindings else "approved",
        to_state="published" if effective_bindings else "approved",
        actor_id=actor_id,
        idempotency_key=f"publish:{command.command_id}",
        reason=command.reason or f"durable publish action {command.action_key}",
        payload={
            "publication_id": str(publication_id),
            "approval_ref": str(command.approval_ref),
            "approval_digest": command.approval_digest,
            "scope_digest": command.scope_digest,
            "command_id": command.command_id,
            "request_fingerprint": command.request_fingerprint,
            "object_ref": knowledge_object.object_id,
            "object_version": page.version,
            "action_key": command.action_key,
            "target_channels": list(command.target_channels),
            "reason": command.reason,
            "initial_propagation_status": PropagationStatus.PENDING.value,
            "desired_digest": desired_digest,
        },
        lock=False,
        correlation_id=effective_correlation,
        traceparent=effective_traceparent,
    )
    page.status = effective_object_status
    publication = GovernancePublication(
        id=publication_id,
        draft_id=draft.id,
        page_id=page.id,
        approval_event_id=approval_event.id,
        publish_event_id=publish_event.id,
        command_id=command.command_id,
        request_fingerprint=command.request_fingerprint,
        approval_digest=command.approval_digest,
        correlation_id=correlation_uuid,
        traceparent=effective_traceparent,
        scope_digest=command.scope_digest,
        object_ref=knowledge_object.object_id,
        object_type=knowledge_object.object_type.value,
        object_version=page.version,
        action_key=command.action_key,
        target_channels=list(command.target_channels),
        previous_object_status=previous_object_status,
        effective_object_status=effective_object_status,
        candidate=result.updated_candidate.to_dict(),
        preview=result.preview.to_dict(),
        opened_bindings=[binding.to_dict() for binding in result.opened_bindings],
        removed_bindings=[binding.to_dict() for binding in result.removed_bindings],
        held_bindings=[
            binding.to_dict() for binding in result.updated_candidate.blocked_bindings
        ],
        action_log=list(result.action_log),
        published_by_id=actor_id,
    )
    session.add(publication)
    await session.flush()

    affected_channels = command.target_channels
    max_attempts = get_settings().delivery_max_attempts
    new_propagations: list[GovernancePropagation] = []
    new_deliveries: list[GovernancePropagationDelivery] = []
    for channel in affected_channels:
        binding_refs = _binding_dicts_for_channel(result, channel)
        propagation_id = uuid.uuid4()
        propagation = GovernancePropagation(
            id=propagation_id,
            publication_id=publication.id,
            surface_id=channel,
            desired_digest=desired_digest,
            status=PropagationStatus.PENDING.value,
            reason="awaiting_downstream_confirmation",
            channel_refs=[channel],
            binding_refs=binding_refs,
            follow_up_commands=[f"confirm_propagation:{publication.id}:{channel}"],
            version=1,
            last_event_id=publish_event.id,
            updated_by_id=actor_id,
        )
        session.add(propagation)
        new_propagations.append(propagation)
        delivery_command_id = f"delivery:{publication.id}:{channel}"
        delivery = GovernancePropagationDelivery(
            propagation_id=propagation_id,
            publication_id=publication.id,
            surface_id=channel,
            status=DeliveryStatus.PENDING.value,
            command_id=delivery_command_id,
            idempotency_key=delivery_command_id,
            desired_digest=desired_digest,
            canonical_payload=delivery_payload,
            expected_page_version=page.version,
            expected_approval_version=approval_event.sequence,
            expected_binding_versions=binding_version_refs(requested_binding_rows),
            attempts=0,
            max_attempts=max_attempts,
            actor_id=actor_id,
            correlation_id=effective_correlation,
            traceparent=effective_traceparent,
        )
        session.add(delivery)
        new_deliveries.append(delivery)

    await session.flush()
    return durable_publication_result(
        publication,
        propagations=tuple(new_propagations),
        deliveries=tuple(new_deliveries),
        replayed=False,
    )


def execute_durable_publish_action(
    candidate: PublishPreviewCandidate,
    action_key: str,
    *,
    reason: str | None = None,
) -> PublishGovernanceResult:
    """Apply a durable action without expanding the persisted binding matrix."""
    normalized = action_key.strip()
    reason_by_action = {
        "publish": "open the approved governed publish path",
        "republish": "refresh the approved governed publish path",
        "restrict_publish": "withdraw the selected governed publish path",
        "hold_external": "hold external exposure pending explicit confirmation",
        "republish_internal_only": "keep internal support truth live while external exposure stops",
    }
    if normalized not in reason_by_action:
        raise DurablePublishDenied(f"unsupported durable action_key={normalized}")

    original_bindings = tuple(candidate.target_bindings or ())
    blocked_by_key = {blocked.key: blocked for blocked in candidate.blocked_bindings}
    if normalized in {"publish", "republish"}:
        updated_bindings = tuple(
            binding
            for binding in original_bindings
            if binding.key not in blocked_by_key
        )
    elif normalized == "restrict_publish":
        updated_bindings = ()
        blocked_by_key = {}
    elif normalized == "hold_external":
        external_bindings = tuple(
            binding
            for binding in original_bindings
            if binding.audience_filter.visibility is Visibility.EXTERNAL
        )
        if not external_bindings:
            raise DurablePublishDenied(
                "hold_external is unavailable because persisted bindings have no external audience"
            )
        for binding in external_bindings:
            blocked_by_key[binding.key] = PublishConflict(
                audience_filter=binding.audience_filter,
                channel=binding.channel,
                reason=(
                    "Held for gated external review: "
                    + (reason or reason_by_action[normalized])
                ),
            )
        updated_bindings = tuple(
            binding
            for binding in original_bindings
            if binding.key not in blocked_by_key
        )
    else:
        updated_bindings = tuple(
            binding
            for binding in original_bindings
            if binding.audience_filter.visibility is Visibility.INTERNAL
            and binding.key not in blocked_by_key
        )
        if not updated_bindings:
            raise DurablePublishDenied(
                "republish_internal_only requires an unblocked explicit internal binding"
            )
        updated_keys = {binding.key for binding in updated_bindings}
        blocked_by_key = {
            key: blocked
            for key, blocked in blocked_by_key.items()
            if key in updated_keys
        }

    updated_candidate = PublishPreviewCandidate(
        object_id=candidate.object_id,
        object_type=candidate.object_type,
        title=candidate.title,
        action_type=candidate.action_type,
        target_audiences=candidate.target_audiences,
        target_channels=candidate.target_channels,
        target_bindings=updated_bindings,
        current_bindings=candidate.current_bindings,
        blocked_bindings=tuple(blocked_by_key.values()),
    )
    current_keys = {binding.key for binding in candidate.current_bindings}
    updated_keys = {binding.key for binding in updated_bindings}
    return PublishGovernanceResult(
        updated_candidate=updated_candidate,
        preview=build_publish_blast_radius_preview(updated_candidate),
        opened_bindings=tuple(
            binding for binding in updated_bindings if binding.key not in current_keys
        ),
        removed_bindings=tuple(
            binding
            for binding in candidate.current_bindings
            if binding.key not in updated_keys
        ),
        held_bindings=tuple(blocked_by_key.values()),
        action_log=(f"{normalized}:{reason or reason_by_action[normalized]}",),
    )


async def update_propagation(
    session: AsyncSession,
    *,
    command: PropagationUpdateCommand,
    actor_id: uuid.UUID,
    mirror_delivery: bool = True,
) -> dict[str, object]:
    publication = await get_publication(session, command.publication_id)
    if publication is None:
        raise DurablePublishNotFound(
            f"publication_id={command.publication_id} was not found"
        )
    if command.status is PropagationStatus.SYNCED:
        raise DurablePublishDenied(
            "synced propagation requires a signed downstream acknowledgment; "
            "manual mutation may record non-success operational states only"
        )
    await lock_draft_aggregate(session, publication.draft_id)
    await lock_governance_command(session, f"propagation:{command.command_id}")

    idempotency_key = f"propagation:{command.command_id}"
    existing_event = (
        await session.execute(
            select(GovernanceLedgerEvent).where(
                GovernanceLedgerEvent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        payload = existing_event.payload
        if payload.get("request_fingerprint") != command.request_fingerprint:
            raise DurablePublishConflict(
                f"command_id={command.command_id} is already bound to a different propagation update"
            )
        raw_result_payload: object = payload.get("result")
        if not isinstance(raw_result_payload, dict):
            raise DurablePublishConflict(
                f"command_id={command.command_id} has no replayable propagation result"
            )
        replayed_result_payload = cast(dict[str, object], raw_result_payload)
        return replayed_result_payload | {"replayed": True}

    propagation = (
        await session.execute(
            select(GovernancePropagation)
            .where(
                GovernancePropagation.publication_id == command.publication_id,
                GovernancePropagation.surface_id == command.surface_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if propagation is None:
        raise DurablePublishNotFound(
            f"surface_id={command.surface_id} is not part of publication_id={command.publication_id}"
        )
    if propagation.version != command.expected_version:
        raise DurablePublishConflict(
            f"propagation version conflict: expected {command.expected_version}, current {propagation.version}"
        )

    previous_status = propagation.status
    next_version = propagation.version + 1
    result_payload: dict[str, object] = {
        "propagation_id": str(propagation.id),
        "publication_id": str(propagation.publication_id),
        "surface_id": propagation.surface_id,
        "status": command.status.value,
        "reason": command.reason,
        "version": next_version,
        "follow_up_commands": list(command.follow_up_commands),
        "persisted": True,
        "rehearsal": False,
    }
    current_event = await get_latest_draft_event(session, publication.draft_id)
    if current_event is None:
        raise DurablePublishConflict(
            f"draft_id={publication.draft_id} has no governance state"
        )
    event = await append_draft_event(
        session,
        draft_id=publication.draft_id,
        event_type=GovernanceEventType.PROPAGATION_UPDATED,
        from_state=current_event.to_state,
        to_state=current_event.to_state,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        reason=command.reason,
        payload={
            "publication_id": str(publication.id),
            "surface_id": propagation.surface_id,
            "previous_status": previous_status,
            "status": command.status.value,
            "previous_version": propagation.version,
            "version": next_version,
            "command_id": command.command_id,
            "request_fingerprint": command.request_fingerprint,
            "result": result_payload,
        },
        lock=False,
    )
    propagation.status = command.status.value
    propagation.reason = command.reason
    propagation.follow_up_commands = list(command.follow_up_commands)
    propagation.version = next_version
    propagation.last_event_id = event.id
    propagation.updated_by_id = actor_id
    if mirror_delivery:
        delivery = (
            await session.execute(
                select(GovernancePropagationDelivery).where(
                    GovernancePropagationDelivery.propagation_id == propagation.id
                )
            )
        ).scalar_one_or_none()
        if delivery is not None and delivery.status != DeliveryStatus.SYNCED.value:
            delivery.status = (
                DeliveryStatus.PENDING.value
                if command.status is PropagationStatus.PENDING
                else DeliveryStatus.FAILED.value
            )
            delivery.last_error = (
                None
                if command.status is PropagationStatus.PENDING
                else f"ops_marked_{command.status.value}"
            )
            result_payload["delivery_status"] = delivery.status
    await session.flush()
    return result_payload | {"ledger_event_id": str(event.id), "replayed": False}


async def get_publication(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> GovernancePublication | None:
    return await session.get(GovernancePublication, publication_id)


async def list_draft_publications(
    session: AsyncSession,
    draft_id: uuid.UUID,
) -> tuple[GovernancePublication, ...]:
    records = (
        (
            await session.execute(
                select(GovernancePublication)
                .where(GovernancePublication.draft_id == draft_id)
                .order_by(
                    GovernancePublication.published_at,
                    GovernancePublication.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return tuple(records)


async def latest_publication_for_object(
    session: AsyncSession,
    object_ref: str,
) -> GovernancePublication | None:
    return (
        await session.execute(
            select(GovernancePublication)
            .where(GovernancePublication.object_ref == object_ref)
            .order_by(
                GovernancePublication.published_at.desc(),
                GovernancePublication.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_publication_propagations(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> tuple[GovernancePropagation, ...]:
    records = (
        (
            await session.execute(
                select(GovernancePropagation)
                .where(GovernancePropagation.publication_id == publication_id)
                .order_by(GovernancePropagation.surface_id)
            )
        )
        .scalars()
        .all()
    )
    return tuple(records)


def durable_publication_result(
    publication: GovernancePublication,
    *,
    propagations: tuple[GovernancePropagation, ...],
    replayed: bool,
    deliveries: tuple[GovernancePropagationDelivery, ...] = (),
) -> dict[str, object]:
    return {
        "selected_action": publication.action_key,
        "action_log": list(publication.action_log),
        "opened_bindings": list(publication.opened_bindings),
        "removed_bindings": list(publication.removed_bindings),
        "held_bindings": list(publication.held_bindings),
        "updated_candidate": dict(publication.candidate),
        "preview": dict(publication.preview),
        "rehearsal": False,
        "persisted": True,
        "replayed": replayed,
        "publication_record_id": str(publication.id),
        "ledger_event_id": str(publication.publish_event_id),
        "approval_ref": str(publication.approval_event_id),
        "approval_digest": publication.approval_digest,
        "scope_digest": publication.scope_digest,
        "command_id": publication.command_id,
        "object_ref": publication.object_ref,
        "object_version": publication.object_version,
        "published_at": publication.published_at.isoformat(),
        "propagation": propagation_summary(propagations, deliveries=deliveries),
    }


def propagation_summary(
    propagations: tuple[GovernancePropagation, ...],
    *,
    deliveries: tuple[GovernancePropagationDelivery, ...] = (),
) -> dict[str, object]:
    counts = {status.value: 0 for status in PropagationStatus}
    delivery_by_propagation = {
        delivery.propagation_id: delivery for delivery in deliveries
    }
    for propagation in propagations:
        counts[propagation.status] = counts.get(propagation.status, 0) + 1
    return {
        "summary": counts,
        "records": [
            propagation_to_dict(
                record,
                delivery=delivery_by_propagation.get(record.id),
            )
            for record in propagations
        ],
    }


def propagation_to_dict(
    record: GovernancePropagation,
    *,
    delivery: GovernancePropagationDelivery | None = None,
) -> dict[str, object]:
    return {
        "propagation_id": str(record.id),
        "publication_id": str(record.publication_id),
        "surface_id": record.surface_id,
        "desired_digest": record.desired_digest,
        "status": record.status,
        "reason": record.reason,
        "channel_refs": list(record.channel_refs),
        "binding_refs": list(record.binding_refs),
        "follow_up_commands": list(record.follow_up_commands),
        "version": record.version,
        "last_event_id": str(record.last_event_id),
        "updated_by_id": (
            str(record.updated_by_id) if record.updated_by_id is not None else None
        ),
        "delivery": delivery_to_dict(delivery) if delivery is not None else None,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def publication_to_dict(
    publication: GovernancePublication,
    *,
    propagations: tuple[GovernancePropagation, ...],
) -> dict[str, object]:
    return {
        "publication_record_id": str(publication.id),
        "draft_id": str(publication.draft_id),
        "page_id": str(publication.page_id),
        "approval_ref": str(publication.approval_event_id),
        "approval_digest": publication.approval_digest,
        "scope_digest": publication.scope_digest,
        "ledger_event_id": str(publication.publish_event_id),
        "command_id": publication.command_id,
        "object_ref": publication.object_ref,
        "object_type": publication.object_type,
        "object_version": publication.object_version,
        "action_key": publication.action_key,
        "target_channels": list(publication.target_channels),
        "previous_object_status": publication.previous_object_status,
        "effective_object_status": publication.effective_object_status,
        "published_by_id": (
            str(publication.published_by_id)
            if publication.published_by_id is not None
            else None
        ),
        "published_at": publication.published_at.isoformat(),
        "result": durable_publication_result(
            publication,
            propagations=propagations,
            replayed=False,
        ),
    }


def _bindings_from_candidate(
    candidate_payload: dict[str, object],
) -> tuple[PublishBinding, ...]:
    raw_bindings = candidate_payload.get("target_bindings")
    if not isinstance(raw_bindings, list):
        raise DurablePublishConflict(
            "stored publication candidate has invalid target_bindings"
        )
    return tuple(_binding_from_dict(item) for item in cast(list[object], raw_bindings))


def _binding_from_dict(payload: object) -> PublishBinding:
    if not isinstance(payload, dict):
        raise DurablePublishConflict("stored publish binding must be an object")
    binding_payload = cast(dict[str, object], payload)
    audience_payload = binding_payload.get("audience_filter")
    channel = binding_payload.get("channel")
    if not isinstance(audience_payload, dict) or not isinstance(channel, str):
        raise DurablePublishConflict(
            "stored publish binding is missing audience/channel"
        )
    audience_mapping = cast(dict[str, object], audience_payload)
    visibility = audience_mapping.get("visibility")
    if not isinstance(visibility, str):
        raise DurablePublishConflict("stored audience is missing visibility")

    def _dimension(name: str) -> tuple[str, ...]:
        value: object = audience_mapping.get(name, [])
        if not isinstance(value, list):
            raise DurablePublishConflict(f"stored audience dimension {name} is invalid")
        dimension_values = cast(list[object], value)
        if not all(isinstance(item, str) for item in dimension_values):
            raise DurablePublishConflict(f"stored audience dimension {name} is invalid")
        return tuple(cast(list[str], dimension_values))

    audience = AudienceFilter(
        visibility=Visibility(visibility),
        brands=_dimension("brands"),
        product_lines=_dimension("product_lines"),
        plans=_dimension("plans"),
        regions=_dimension("regions"),
        languages=_dimension("languages"),
        product_versions=_dimension("product_versions"),
    )
    return PublishBinding(audience_filter=audience, channel=channel)


def _binding_dicts_for_channel(
    result: PublishGovernanceResult,
    channel: str,
) -> list[dict[str, object]]:
    by_key: dict[tuple[AudienceFilter, str], dict[str, object]] = {}
    for binding in (
        *result.updated_candidate.target_bindings,
        *result.removed_bindings,
    ):
        if binding.channel == channel:
            by_key[binding.key] = binding.to_dict()
    return list(by_key.values())
