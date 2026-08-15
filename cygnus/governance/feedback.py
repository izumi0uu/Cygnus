"""Durable, replay-safe consumption feedback for the governed session seam.

This module owns feedback fact persistence and command idempotency. Routing is
delegated to :mod:`cygnus.governance.feedback_routing`, while the caller owns
the transaction spanning the signal, route, and mutation audit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.ledger import lock_governance_command
from cygnus.observability import current_request_id, current_traceparent
from cygnus.runtime.database.models import GovernanceFeedbackSignal


class FeedbackCommandConflict(ValueError):
    """A command ID was reused for a different normalized feedback request."""


class FeedbackSignalType(str, Enum):
    """Accepted consumption-feedback facts."""

    ANSWER_ACCEPTED = "answer_accepted"
    HUMAN_REWRITE = "human_rewrite"
    ESCALATED = "escalated"
    LOW_RATING = "low_rating"
    UNSUPPORTED_ANSWER = "unsupported_answer"
    STALE_ANSWER = "stale_answer"


_AUDIENCE_KEYS = frozenset(
    {
        "visibility",
        "brand",
        "product_line",
        "plan",
        "plan_tier",
        "region",
        "language",
        "product_version",
    }
)
_AUDIENCE_DIMENSION_KEYS = (
    "brand",
    "product_line",
    "plan_tier",
    "region",
    "language",
    "product_version",
)
_MAX_AUDIENCE_VALUE_LENGTH = 200
_MAX_COMMAND_ID_LENGTH = 220
_MAX_OBJECT_ID_LENGTH = 320
_MAX_SOURCE_CONTEXT_REF_LENGTH = 500
_MAX_NOTES_LENGTH = 10_000


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackSignalInput:
    """Normalized input for one durable feedback command."""

    command_id: str
    signal_type: FeedbackSignalType | str
    audience_context: Mapping[str, object]
    object_id: str | None = None
    page_id: uuid.UUID | str | None = None
    draft_id: uuid.UUID | str | None = None
    notes: str | None = None
    source_context_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command_id",
            _required_text(
                self.command_id,
                label="command_id",
                max_length=_MAX_COMMAND_ID_LENGTH,
            ),
        )
        try:
            normalized_type = FeedbackSignalType(self.signal_type.strip())
        except (AttributeError, ValueError) as exc:
            raise ValueError("signal_type is not supported") from exc
        object.__setattr__(self, "signal_type", normalized_type)
        object.__setattr__(
            self,
            "audience_context",
            normalize_audience_context(self.audience_context),
        )
        object.__setattr__(
            self,
            "object_id",
            _optional_text(
                self.object_id,
                label="object_id",
                max_length=_MAX_OBJECT_ID_LENGTH,
            ),
        )
        object.__setattr__(self, "page_id", _optional_uuid(self.page_id, "page_id"))
        object.__setattr__(
            self,
            "draft_id",
            _optional_uuid(self.draft_id, "draft_id"),
        )
        object.__setattr__(
            self,
            "notes",
            _optional_text(self.notes, label="notes", max_length=_MAX_NOTES_LENGTH),
        )
        object.__setattr__(
            self,
            "source_context_ref",
            _optional_text(
                self.source_context_ref,
                label="source_context_ref",
                max_length=_MAX_SOURCE_CONTEXT_REF_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class FeedbackSignalWrite:
    """Persisted feedback signal plus whether this call replayed it."""

    signal: GovernanceFeedbackSignal
    replayed: bool


def normalize_audience_context(payload: object) -> dict[str, str | None]:
    """Return the canonical audience payload stored with a feedback fact."""

    if not isinstance(payload, Mapping):
        raise ValueError("audience_context must be an object")
    raw_payload = cast(Mapping[object, object], payload)
    if any(not isinstance(key, str) for key in raw_payload):
        raise ValueError("audience_context keys must be strings")
    normalized_payload = cast(Mapping[str, object], raw_payload)
    unknown = set(normalized_payload).difference(_AUDIENCE_KEYS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"audience_context has unknown keys: {names}")

    visibility_value = _optional_text(
        normalized_payload.get("visibility"),
        label="audience_context.visibility",
        max_length=_MAX_AUDIENCE_VALUE_LENGTH,
    )
    if visibility_value is None:
        raise ValueError("audience_context.visibility is required")
    if visibility_value not in {"internal", "external"}:
        raise ValueError("audience_context.visibility is invalid")

    plan = _optional_text(
        normalized_payload.get("plan"),
        label="audience_context.plan",
        max_length=_MAX_AUDIENCE_VALUE_LENGTH,
    )
    plan_tier = _optional_text(
        normalized_payload.get("plan_tier"),
        label="audience_context.plan_tier",
        max_length=_MAX_AUDIENCE_VALUE_LENGTH,
    )
    if plan is not None and plan_tier is not None and plan != plan_tier:
        raise ValueError("audience_context.plan and plan_tier conflict")

    normalized: dict[str, str | None] = {"visibility": visibility_value}
    for key in _AUDIENCE_DIMENSION_KEYS:
        normalized[key] = (
            plan_tier or plan
            if key == "plan_tier"
            else _optional_text(
                normalized_payload.get(key),
                label=f"audience_context.{key}",
                max_length=_MAX_AUDIENCE_VALUE_LENGTH,
            )
        )
    return normalized


def _normalize_feedback_input(signal_input: object) -> FeedbackSignalInput:
    if not isinstance(signal_input, FeedbackSignalInput):
        raise TypeError("signal_input must be a FeedbackSignalInput")
    return FeedbackSignalInput(
        command_id=signal_input.command_id,
        signal_type=signal_input.signal_type,
        audience_context=signal_input.audience_context,
        object_id=signal_input.object_id,
        page_id=signal_input.page_id,
        draft_id=signal_input.draft_id,
        notes=signal_input.notes,
        source_context_ref=signal_input.source_context_ref,
    )


def _replay_candidate_input(
    existing: GovernanceFeedbackSignal,
    signal_input: FeedbackSignalInput,
) -> FeedbackSignalInput:
    object_id = signal_input.object_id
    if object_id is None and signal_input.draft_id is not None:
        object_id = existing.object_id

    page_id = signal_input.page_id
    if (
        page_id is None
        and object_id == existing.object_id
        and signal_input.draft_id == existing.draft_id
    ):
        page_id = existing.page_id

    return FeedbackSignalInput(
        command_id=signal_input.command_id,
        signal_type=signal_input.signal_type,
        audience_context=signal_input.audience_context,
        object_id=object_id,
        page_id=page_id,
        draft_id=signal_input.draft_id,
        notes=signal_input.notes,
        source_context_ref=signal_input.source_context_ref,
    )


async def replay_feedback_signal(
    session: AsyncSession,
    signal_input: FeedbackSignalInput,
    *,
    actor_id: uuid.UUID | str,
) -> FeedbackSignalWrite | None:
    """Replay or reject an existing command before governed ref resolution.

    The transaction-level command lock makes the preflight authoritative for
    the remainder of the caller-owned transaction. A missing binding returns
    ``None`` so the adapter can resolve scoped refs and create new truth.
    """

    normalized_input = _normalize_feedback_input(signal_input)
    normalized_actor_id = _required_uuid(actor_id, "actor_id")
    await lock_governance_command(
        session,
        f"feedback-signal:{normalized_input.command_id}",
    )
    existing = (
        await session.execute(
            select(GovernanceFeedbackSignal).where(
                GovernanceFeedbackSignal.command_id == normalized_input.command_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None

    replay_input = _replay_candidate_input(existing, normalized_input)
    request_fingerprint = _feedback_request_fingerprint(
        replay_input,
        actor_id=normalized_actor_id,
    )
    if existing.request_fingerprint != request_fingerprint:
        message = (
            f"command_id={normalized_input.command_id} is already bound to "
            "different feedback"
        )
        raise FeedbackCommandConflict(message)
    return FeedbackSignalWrite(signal=existing, replayed=True)


async def create_feedback_signal(
    session: AsyncSession,
    signal_input: FeedbackSignalInput,
    *,
    actor_id: uuid.UUID | str,
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> FeedbackSignalWrite:
    """Create or replay one feedback fact with request trace metadata."""
    normalized_input = _normalize_feedback_input(signal_input)
    normalized_actor_id = _required_uuid(actor_id, "actor_id")
    request_fingerprint = _feedback_request_fingerprint(
        normalized_input,
        actor_id=normalized_actor_id,
    )
    await lock_governance_command(
        session,
        f"feedback-signal:{normalized_input.command_id}",
    )
    existing = (
        await session.execute(
            select(GovernanceFeedbackSignal).where(
                GovernanceFeedbackSignal.command_id == normalized_input.command_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            message = f"command_id={normalized_input.command_id} is already bound to different feedback"
            raise FeedbackCommandConflict(message)
        return FeedbackSignalWrite(signal=existing, replayed=True)
    effective_correlation = correlation_id or current_request_id()
    correlation_uuid = None
    if effective_correlation:
        try:
            correlation_uuid = uuid.UUID(str(effective_correlation))
        except (TypeError, ValueError):
            correlation_uuid = None
    signal = GovernanceFeedbackSignal(
        id=uuid.uuid4(),
        command_id=normalized_input.command_id,
        request_fingerprint=request_fingerprint,
        correlation_id=correlation_uuid,
        traceparent=traceparent or current_traceparent(),
        signal_type=FeedbackSignalType(normalized_input.signal_type).value,
        actor_id=normalized_actor_id,
        audience_context=dict(normalized_input.audience_context),
        object_id=normalized_input.object_id,
        page_id=normalized_input.page_id,
        draft_id=normalized_input.draft_id,
        notes=normalized_input.notes,
        source_context_ref=normalized_input.source_context_ref,
    )
    session.add(signal)
    await session.flush()
    return FeedbackSignalWrite(signal=signal, replayed=False)


def feedback_signal_ref(signal: GovernanceFeedbackSignal) -> str:
    """Return the stable external reference for one persisted feedback fact."""
    return f"feedback-signal:{signal.id}"


def feedback_signal_to_dict(signal: GovernanceFeedbackSignal) -> dict[str, object]:
    """Project a durable feedback row without exposing fingerprints or notes payloads."""
    created_at = getattr(signal, "created_at", None)
    updated_at = getattr(signal, "updated_at", None)
    return {
        "feedback_ref": feedback_signal_ref(signal),
        "signal_id": str(signal.id),
        "command_id": signal.command_id,
        "correlation_id": (
            str(signal.correlation_id) if signal.correlation_id is not None else None
        ),
        "traceparent": signal.traceparent,
        "signal_type": signal.signal_type,
        "actor_id": str(signal.actor_id),
        "audience_context": dict(signal.audience_context or {}),
        "object_id": signal.object_id,
        "page_id": str(signal.page_id) if signal.page_id is not None else None,
        "draft_id": str(signal.draft_id) if signal.draft_id is not None else None,
        "source_context_ref": signal.source_context_ref,
        "notes": signal.notes,
        "created_at": _datetime_value(created_at),
        "updated_at": _datetime_value(updated_at),
    }


def _feedback_request_fingerprint(
    signal_input: FeedbackSignalInput,
    *,
    actor_id: uuid.UUID,
) -> str:
    payload: dict[str, object] = {
        "actor_id": str(actor_id),
        "signal_type": FeedbackSignalType(signal_input.signal_type).value,
        "audience_context": dict(signal_input.audience_context),
        "object_id": signal_input.object_id,
        "page_id": (
            str(signal_input.page_id) if signal_input.page_id is not None else None
        ),
        "draft_id": (
            str(signal_input.draft_id) if signal_input.draft_id is not None else None
        ),
        "notes": signal_input.notes,
        "source_context_ref": signal_input.source_context_ref,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: object, *, label: str, max_length: int) -> str:
    normalized = _optional_text(value, label=label, max_length=max_length)
    if normalized is None:
        raise ValueError(f"{label} is required")
    return normalized


def _optional_text(
    value: object | None,
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


def _optional_uuid(value: object | None, label: str) -> uuid.UUID | None:
    if value is None:
        return None
    return _required_uuid(value, label)


def _required_uuid(value: object, label: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a UUID")
    try:
        return uuid.UUID(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _datetime_value(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


__all__ = [
    "FeedbackCommandConflict",
    "FeedbackSignalInput",
    "FeedbackSignalType",
    "FeedbackSignalWrite",
    "GovernanceFeedbackSignal",
    "create_feedback_signal",
    "feedback_signal_to_dict",
    "feedback_signal_ref",
    "replay_feedback_signal",
    "normalize_audience_context",
]
