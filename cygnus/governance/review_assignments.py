from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.ledger import lock_governance_command
from cygnus.review.briefing import OwnerState
from cygnus.runtime.database.models import (
    GovernanceReviewAssignment,
    GovernanceReviewAssignmentEvent,
    GovernanceSignal,
)

REVIEW_ASSIGNMENT_REF_MAX_LENGTH = 220
REVIEW_ASSIGNMENT_REASON_MAX_LENGTH = 2_000


class ReviewAssignmentAction(str, Enum):
    ASSIGN = "assign"
    ESCALATE = "escalate"
    RELEASE = "release"


class ReviewAssignmentConflict(ValueError):
    """A command conflicts with the current assignment or idempotency record."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewAssignmentCommand:
    command_id: str
    action: ReviewAssignmentAction
    owner_ref: str | None
    reason: str
    expected_version: int

    def __post_init__(self) -> None:
        command_id = self.command_id.strip()
        reason = self.reason.strip()
        owner_ref = self.owner_ref.strip() if self.owner_ref is not None else None
        if not command_id:
            raise ValueError("command_id must not be blank")
        if len(command_id) > REVIEW_ASSIGNMENT_REF_MAX_LENGTH:
            raise ValueError(
                "command_id must be at most "
                f"{REVIEW_ASSIGNMENT_REF_MAX_LENGTH} characters"
            )
        if not reason:
            raise ValueError("reason must not be blank")
        if len(reason) > REVIEW_ASSIGNMENT_REASON_MAX_LENGTH:
            raise ValueError(
                "reason must be at most "
                f"{REVIEW_ASSIGNMENT_REASON_MAX_LENGTH} characters"
            )
        if self.expected_version < 1:
            raise ValueError("expected_version must be at least 1")
        if self.action in {
            ReviewAssignmentAction.ASSIGN,
            ReviewAssignmentAction.ESCALATE,
        }:
            if not owner_ref:
                raise ValueError(f"{self.action.value} requires owner_ref")
            if len(owner_ref) > REVIEW_ASSIGNMENT_REF_MAX_LENGTH:
                raise ValueError(
                    "owner_ref must be at most "
                    f"{REVIEW_ASSIGNMENT_REF_MAX_LENGTH} characters"
                )
        elif owner_ref is not None:
            raise ValueError("release does not accept owner_ref")
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "owner_ref", owner_ref)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class ReviewAssignmentMutationResult:
    assignment: GovernanceReviewAssignment
    event: GovernanceReviewAssignmentEvent
    signal_ref: str
    replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        assignment_payload = review_assignment_to_dict(
            self.assignment,
            signal_ref=self.signal_ref,
        )
        if self.replayed:
            assignment_payload.update(
                lifecycle_state=self.event.to_state,
                owner_ref=self.event.owner_ref,
                escalation_reason=(
                    self.event.reason
                    if self.event.to_state == OwnerState.ESCALATED.value
                    else None
                ),
                version=self.event.sequence,
                updated_at=self.event.occurred_at.isoformat(),
            )
        return {
            "assignment": assignment_payload,
            "event": review_assignment_event_to_dict(self.event),
            "replayed": self.replayed,
        }


async def initialize_review_assignment(
    session: AsyncSession,
    signal: GovernanceSignal,
    *,
    actor_id: uuid.UUID,
) -> GovernanceReviewAssignment:
    """Create the explicit unassigned baseline for a new governance signal."""
    assignment = GovernanceReviewAssignment(
        signal_id=signal.id,
        lifecycle_state=OwnerState.UNASSIGNED.value,
        owner_ref=None,
        escalation_reason=None,
        version=1,
    )
    session.add(assignment)
    await session.flush()
    event = GovernanceReviewAssignmentEvent(
        assignment_id=assignment.id,
        sequence=1,
        command_id=f"review-assignment:init:{signal.id}",
        request_fingerprint=_fingerprint(
            {
                "action": "initialize",
                "signal_ref": signal.signal_ref,
                "owner_ref": None,
            }
        ),
        event_type="initialized",
        from_state=None,
        to_state=OwnerState.UNASSIGNED.value,
        actor_id=actor_id,
        owner_ref=None,
        reason="Review assignment initialized without an owner.",
    )
    session.add(event)
    await session.flush()
    return assignment


async def load_review_assignments(
    session: AsyncSession,
    signal_ids: tuple[uuid.UUID, ...],
) -> dict[uuid.UUID, GovernanceReviewAssignment]:
    if not signal_ids:
        return {}
    assignments = tuple(
        (
            await session.execute(
                select(GovernanceReviewAssignment).where(
                    GovernanceReviewAssignment.signal_id.in_(signal_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    return {assignment.signal_id: assignment for assignment in assignments}


async def list_review_assignment_events(
    session: AsyncSession,
    assignment_id: uuid.UUID,
) -> tuple[GovernanceReviewAssignmentEvent, ...]:
    return tuple(
        (
            await session.execute(
                select(GovernanceReviewAssignmentEvent)
                .where(GovernanceReviewAssignmentEvent.assignment_id == assignment_id)
                .order_by(GovernanceReviewAssignmentEvent.sequence)
            )
        )
        .scalars()
        .all()
    )


async def apply_review_assignment_command(
    session: AsyncSession,
    *,
    signal_ref: str,
    command: ReviewAssignmentCommand,
    actor_id: uuid.UUID,
) -> ReviewAssignmentMutationResult | None:
    normalized_ref = signal_ref.strip()
    if not normalized_ref:
        raise ValueError("signal_ref must not be blank")
    await lock_governance_command(
        session,
        f"review-assignment-command:{command.command_id}",
    )
    await lock_governance_command(session, f"review-assignment:{normalized_ref}")

    row = cast(
        tuple[GovernanceSignal, GovernanceReviewAssignment] | None,
        (
            await session.execute(
                select(GovernanceSignal, GovernanceReviewAssignment)
                .join(
                    GovernanceReviewAssignment,
                    GovernanceReviewAssignment.signal_id == GovernanceSignal.id,
                )
                .where(GovernanceSignal.signal_ref == normalized_ref)
                .with_for_update()
            )
        ).one_or_none(),
    )
    if row is None:
        return None
    signal, assignment = row
    fingerprint = _command_fingerprint(normalized_ref, command)
    existing_event = (
        await session.execute(
            select(GovernanceReviewAssignmentEvent).where(
                GovernanceReviewAssignmentEvent.command_id == command.command_id
            )
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        if (
            existing_event.assignment_id != assignment.id
            or existing_event.request_fingerprint != fingerprint
        ):
            raise ReviewAssignmentConflict(
                f"command_id={command.command_id} is already bound to another review assignment command"
            )
        return ReviewAssignmentMutationResult(
            assignment=assignment,
            event=existing_event,
            signal_ref=signal.signal_ref,
            replayed=True,
        )

    if signal.status != "active":
        raise ReviewAssignmentConflict(
            f"signal_ref={normalized_ref} cannot be assigned from status={signal.status}"
        )
    if assignment.version != command.expected_version:
        raise ReviewAssignmentConflict(
            f"expected_version={command.expected_version} does not match current version={assignment.version}"
        )

    from_state = OwnerState(assignment.lifecycle_state)
    to_state, event_type, owner_ref, escalation_reason = _transition(
        assignment,
        command,
    )
    now = datetime.now(timezone.utc)
    assignment.lifecycle_state = to_state.value
    assignment.owner_ref = owner_ref
    assignment.escalation_reason = escalation_reason
    assignment.version += 1
    assignment.updated_at = now

    event = GovernanceReviewAssignmentEvent(
        assignment_id=assignment.id,
        sequence=assignment.version,
        command_id=command.command_id,
        request_fingerprint=fingerprint,
        event_type=event_type,
        from_state=from_state.value,
        to_state=to_state.value,
        actor_id=actor_id,
        owner_ref=owner_ref,
        reason=command.reason,
        occurred_at=now,
    )
    session.add(event)
    await session.flush()
    return ReviewAssignmentMutationResult(
        assignment=assignment,
        event=event,
        signal_ref=signal.signal_ref,
    )


def review_assignment_to_dict(
    assignment: GovernanceReviewAssignment,
    *,
    signal_ref: str,
) -> dict[str, object]:
    return {
        "id": str(assignment.id),
        "signal_ref": signal_ref,
        "owner_ref": assignment.owner_ref,
        "lifecycle_state": assignment.lifecycle_state,
        "escalation_reason": assignment.escalation_reason,
        "version": assignment.version,
        "trace_ref": f"review-assignment:{assignment.id}",
        "persisted": True,
        "created_at": assignment.created_at.isoformat(),
        "updated_at": assignment.updated_at.isoformat(),
    }


def review_assignment_event_to_dict(
    event: GovernanceReviewAssignmentEvent,
) -> dict[str, object]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "actor_id": str(event.actor_id),
        "owner_ref": event.owner_ref,
        "reason": event.reason,
        "sequence": event.sequence,
        "trace_ref": f"review-assignment-event:{event.id}",
        "persisted": True,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _transition(
    assignment: GovernanceReviewAssignment,
    command: ReviewAssignmentCommand,
) -> tuple[OwnerState, str, str | None, str | None]:
    current_state = OwnerState(assignment.lifecycle_state)
    if command.action is ReviewAssignmentAction.ASSIGN:
        if (
            current_state is OwnerState.ASSIGNED
            and assignment.owner_ref == command.owner_ref
        ):
            raise ReviewAssignmentConflict(
                f"review assignment is already assigned to owner_ref={command.owner_ref}"
            )
        event_type = (
            "assigned" if current_state is OwnerState.UNASSIGNED else "reassigned"
        )
        return OwnerState.ASSIGNED, event_type, command.owner_ref, None
    if command.action is ReviewAssignmentAction.ESCALATE:
        if (
            current_state is OwnerState.ESCALATED
            and assignment.owner_ref == command.owner_ref
        ):
            raise ReviewAssignmentConflict(
                f"review assignment is already escalated to owner_ref={command.owner_ref}"
            )
        return (
            OwnerState.ESCALATED,
            "escalated",
            command.owner_ref,
            command.reason,
        )
    if current_state is OwnerState.UNASSIGNED:
        raise ReviewAssignmentConflict("review assignment is already unassigned")
    return OwnerState.UNASSIGNED, "released", None, None


def _command_fingerprint(
    signal_ref: str,
    command: ReviewAssignmentCommand,
) -> str:
    return _fingerprint(
        {
            "signal_ref": signal_ref,
            "action": command.action.value,
            "owner_ref": command.owner_ref,
            "reason": command.reason,
            "expected_version": command.expected_version,
        }
    )


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
