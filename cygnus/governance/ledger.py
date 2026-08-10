from __future__ import annotations

from collections.abc import Iterable
import hashlib
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import GovernanceLedgerEvent, WikiPageDraft


class GovernanceEventType(str, Enum):
    PROPOSAL_CREATED = "proposal_created"
    DRAFT_UPDATED = "draft_updated"
    REVIEW_REQUESTED = "review_requested"
    CHANGES_REQUESTED = "changes_requested"
    REVIEW_RESUBMITTED = "review_resubmitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    PUBLISHED = "published"
    PROPAGATION_UPDATED = "propagation_updated"
    STATE_IMPORTED = "state_imported"


class GovernanceLedgerConflict(ValueError):
    """An idempotency key was reused for a different governed transition."""


def governance_state_for_draft_status(status: str) -> str:
    normalized = status.strip()
    if normalized == "pending":
        return "in_review"
    return normalized


def transition_key(
    draft_id: uuid.UUID,
    event_type: GovernanceEventType,
    *,
    revision_round: int | None = None,
) -> str:
    suffix = f":{revision_round}" if revision_round is not None else ""
    return f"wiki-draft:{draft_id}:{event_type.value}{suffix}"


def draft_update_key(draft_id: uuid.UUID, draft_version: int) -> str:
    if draft_version < 1:
        raise ValueError("draft_version must be positive")
    return f"wiki-draft:{draft_id}:{GovernanceEventType.DRAFT_UPDATED.value}:{draft_version}"


async def record_draft_update(
    session: AsyncSession,
    draft: WikiPageDraft,
    *,
    previous_draft_version: int,
    from_state: str,
    to_state: str,
    actor_id: uuid.UUID | None,
    action: str,
    reason: str | None = None,
    extra_payload: dict[str, object] | None = None,
    lock: bool = True,
) -> GovernanceLedgerEvent:
    """Append one versioned draft mutation with a content-integrity trace."""
    if previous_draft_version < 1:
        raise ValueError("previous_draft_version must be positive")
    if draft.version != previous_draft_version + 1:
        raise ValueError("draft.version must advance exactly once per draft update")

    normalized_action = action.strip()
    if not normalized_action:
        raise ValueError("action must not be blank")

    payload = {
        "action": normalized_action,
        "previous_draft_version": previous_draft_version,
        "draft_version": draft.version,
        "base_version": draft.base_version,
        "revision_round": draft.revision_round,
        "content_sha256": hashlib.sha256(draft.content_md.encode("utf-8")).hexdigest(),
    }
    details = dict(extra_payload or {})
    overlapping_keys = set(payload).intersection(details)
    if overlapping_keys:
        names = ", ".join(sorted(overlapping_keys))
        raise ValueError(f"extra_payload may not override ledger fields: {names}")
    payload.update(details)

    return await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.DRAFT_UPDATED,
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        idempotency_key=draft_update_key(draft.id, draft.version),
        reason=reason,
        payload=payload,
        lock=lock,
    )


async def _lock_governance_key(
    session: AsyncSession,
    key_material: bytes,
) -> None:
    lock_key = int.from_bytes(
        hashlib.blake2b(key_material, digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    _ = await session.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def lock_draft_aggregate(session: AsyncSession, draft_id: uuid.UUID) -> None:
    """Serialize ledger/publication writes for one draft inside the DB transaction."""
    await _lock_governance_key(session, b"draft:" + draft_id.bytes)


async def lock_governance_command(session: AsyncSession, command_key: str) -> None:
    """Serialize globally unique idempotent commands across draft aggregates."""
    normalized = command_key.strip()
    if not normalized:
        raise ValueError("command_key must not be blank")
    await _lock_governance_key(session, b"command:" + normalized.encode("utf-8"))


async def get_latest_draft_event(
    session: AsyncSession,
    draft_id: uuid.UUID,
) -> GovernanceLedgerEvent | None:
    return (
        await session.execute(
            select(GovernanceLedgerEvent)
            .where(GovernanceLedgerEvent.draft_id == draft_id)
            .order_by(GovernanceLedgerEvent.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def append_draft_event(
    session: AsyncSession,
    *,
    draft_id: uuid.UUID,
    event_type: GovernanceEventType,
    from_state: str | None,
    to_state: str,
    actor_id: uuid.UUID | None,
    idempotency_key: str,
    reason: str | None = None,
    payload: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
    lock: bool = True,
) -> GovernanceLedgerEvent:
    """Append one ordered event or return its exact idempotent replay."""
    normalized_key = idempotency_key.strip()
    normalized_to_state = to_state.strip()
    normalized_from_state = from_state.strip() if from_state is not None else None
    normalized_reason = reason.strip() if reason is not None else None
    normalized_payload = dict(payload or {})
    if not normalized_key:
        raise ValueError("idempotency_key must not be blank")
    if not normalized_to_state:
        raise ValueError("to_state must not be blank")
    if normalized_from_state == "":
        raise ValueError("from_state must not be blank when provided")
    if normalized_reason == "":
        raise ValueError("reason must not be blank when provided")

    if lock:
        await lock_draft_aggregate(session, draft_id)

    existing = (
        await session.execute(
            select(GovernanceLedgerEvent).where(
                GovernanceLedgerEvent.idempotency_key == normalized_key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        expected_identity = (
            draft_id,
            event_type.value,
            normalized_from_state,
            normalized_to_state,
            actor_id,
            normalized_reason,
            normalized_payload,
        )
        existing_identity = (
            existing.draft_id,
            existing.event_type,
            existing.from_state,
            existing.to_state,
            existing.actor_id,
            existing.reason,
            existing.payload,
        )
        if existing_identity != expected_identity:
            raise GovernanceLedgerConflict(
                f"idempotency_key={normalized_key} is already bound to a different transition"
            )
        return existing

    current = await get_latest_draft_event(session, draft_id)
    if current is None:
        if normalized_from_state is not None:
            raise GovernanceLedgerConflict(
                f"draft_id={draft_id} has no current state; expected from_state=None"
            )
        next_sequence = 1
    else:
        if current.to_state != normalized_from_state:
            expected_state = current.to_state
            raise GovernanceLedgerConflict(
                f"draft_id={draft_id} state conflict: expected {expected_state}, got {normalized_from_state}"
            )
        next_sequence = current.sequence + 1

    event = GovernanceLedgerEvent(
        draft_id=draft_id,
        sequence=next_sequence,
        event_type=event_type.value,
        from_state=normalized_from_state,
        to_state=normalized_to_state,
        actor_id=actor_id,
        idempotency_key=normalized_key,
        reason=normalized_reason,
        payload=normalized_payload,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    session.add(event)
    await session.flush()
    return event


async def record_draft_proposal(
    session: AsyncSession,
    draft: WikiPageDraft,
    *,
    lock: bool = True,
) -> GovernanceLedgerEvent:
    """Record the durable creation of a draft before it enters review."""
    content_digest = hashlib.sha256(draft.content_md.encode("utf-8")).hexdigest()
    return await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.PROPOSAL_CREATED,
        from_state=None,
        to_state="draft",
        actor_id=draft.author_id,
        idempotency_key=transition_key(
            draft.id,
            GovernanceEventType.PROPOSAL_CREATED,
        ),
        payload={
            "draft_kind": draft.draft_kind,
            "page_id": str(draft.page_id) if draft.page_id is not None else None,
            "base_version": draft.base_version,
            "draft_version": draft.version,
            "revision_round": draft.revision_round,
            "source": draft.source,
            "content_sha256": content_digest,
        },
        lock=lock,
    )


async def record_draft_review_request(
    session: AsyncSession,
    draft: WikiPageDraft,
    *,
    actor_id: uuid.UUID | None,
    reason: str | None,
    review_type: str | None = None,
    expected_version: int | None = None,
    lock: bool = True,
) -> GovernanceLedgerEvent:
    """Append or replay the review-queue transition for one draft revision."""
    payload: dict[str, object] = {
        "draft_version": draft.version,
        "revision_round": draft.revision_round,
        "source": draft.source,
    }
    if review_type is not None:
        payload["review_type"] = review_type
    if expected_version is not None:
        payload["expected_version"] = expected_version
    return await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.REVIEW_REQUESTED,
        from_state="draft",
        to_state="in_review",
        actor_id=actor_id,
        idempotency_key=transition_key(
            draft.id,
            GovernanceEventType.REVIEW_REQUESTED,
            revision_round=draft.revision_round,
        ),
        reason=reason,
        payload=payload,
        lock=lock,
    )


async def record_created_draft(
    session: AsyncSession,
    draft: WikiPageDraft,
) -> tuple[GovernanceLedgerEvent, GovernanceLedgerEvent]:
    """Record that legacy create callers both proposed and submitted a draft."""
    proposal_event = await record_draft_proposal(session, draft)
    review_event = await record_draft_review_request(
        session,
        draft,
        actor_id=draft.author_id,
        reason=draft.note,
    )
    return proposal_event, review_event


async def list_draft_events(
    session: AsyncSession,
    draft_id: uuid.UUID,
) -> tuple[GovernanceLedgerEvent, ...]:
    events = (
        (
            await session.execute(
                select(GovernanceLedgerEvent)
                .where(GovernanceLedgerEvent.draft_id == draft_id)
                .order_by(GovernanceLedgerEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    return tuple(events)


async def get_approval_event(
    session: AsyncSession,
    *,
    draft_id: uuid.UUID,
    approval_ref: uuid.UUID,
) -> GovernanceLedgerEvent | None:
    return (
        await session.execute(
            select(GovernanceLedgerEvent).where(
                GovernanceLedgerEvent.id == approval_ref,
                GovernanceLedgerEvent.draft_id == draft_id,
                GovernanceLedgerEvent.to_state == "approved",
                GovernanceLedgerEvent.event_type.in_(
                    (
                        GovernanceEventType.APPROVED.value,
                        GovernanceEventType.STATE_IMPORTED.value,
                    )
                ),
            )
        )
    ).scalar_one_or_none()


def event_to_dict(event: GovernanceLedgerEvent) -> dict[str, object]:
    return {
        "event_id": str(event.id),
        "draft_id": str(event.draft_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "actor_id": str(event.actor_id) if event.actor_id is not None else None,
        "idempotency_key": event.idempotency_key,
        "reason": event.reason,
        "payload": event.payload,
        "occurred_at": event.occurred_at.isoformat(),
        "recorded_at": event.recorded_at.isoformat(),
    }


def dedupe_strings(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)
