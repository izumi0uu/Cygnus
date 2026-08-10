"""Durable consumption-feedback facts for the governed session seam.

This module owns the feedback write contract.  It deliberately does not route
signals into review or refresh queues; those transitions need a separate
durable owner and remain outside this slice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import GovernanceFeedbackSignal


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
_MAX_OBJECT_ID_LENGTH = 320
_MAX_SOURCE_CONTEXT_REF_LENGTH = 500
_MAX_NOTES_LENGTH = 10_000


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackSignalInput:
    """Normalized input for one durable feedback fact."""

    signal_type: FeedbackSignalType | str
    audience_context: Mapping[str, object]
    object_id: str | None = None
    page_id: uuid.UUID | str | None = None
    draft_id: uuid.UUID | str | None = None
    notes: str | None = None
    source_context_ref: str | None = None

    def __post_init__(self) -> None:
        try:
            if isinstance(self.signal_type, FeedbackSignalType):
                normalized_type = self.signal_type
            elif isinstance(self.signal_type, str):
                normalized_type = FeedbackSignalType(self.signal_type.strip())
            else:
                raise ValueError("signal_type must be a string")
        except ValueError as exc:
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


def normalize_audience_context(
    payload: object,
) -> dict[str, str | None]:
    """Return the canonical audience payload stored with a feedback fact.

    The adapter normally constructs this through the existing audience
    payload owner. Persistence keeps the same small canonical shape so direct
    callers cannot write an unscoped or ambiguous context.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("audience_context must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("audience_context keys must be strings")
    unknown = set(payload).difference(_AUDIENCE_KEYS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"audience_context has unknown keys: {names}")

    visibility_value = _optional_text(
        payload.get("visibility"),
        label="audience_context.visibility",
        max_length=_MAX_AUDIENCE_VALUE_LENGTH,
    )
    if visibility_value is None:
        raise ValueError("audience_context.visibility is required")
    if visibility_value not in {"internal", "external"}:
        raise ValueError("audience_context.visibility is invalid")

    plan = _optional_text(
        payload.get("plan"),
        label="audience_context.plan",
        max_length=_MAX_AUDIENCE_VALUE_LENGTH,
    )
    plan_tier = _optional_text(
        payload.get("plan_tier"),
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
                payload.get(key),
                label=f"audience_context.{key}",
                max_length=_MAX_AUDIENCE_VALUE_LENGTH,
            )
        )
    return normalized


async def create_feedback_signal(
    session: AsyncSession,
    signal_input: FeedbackSignalInput,
    *,
    actor_id: uuid.UUID | str,
) -> GovernanceFeedbackSignal:
    """Flush one durable feedback fact without committing the caller session."""
    if not isinstance(signal_input, FeedbackSignalInput):
        raise TypeError("signal_input must be a FeedbackSignalInput")
    # Frozen dataclasses do not deep-freeze their mapping members. Rebuild the
    # input at the write boundary so a caller cannot mutate normalized input
    # after construction and bypass the persistence contract.
    normalized_input = FeedbackSignalInput(
        signal_type=signal_input.signal_type,
        audience_context=signal_input.audience_context,
        object_id=signal_input.object_id,
        page_id=signal_input.page_id,
        draft_id=signal_input.draft_id,
        notes=signal_input.notes,
        source_context_ref=signal_input.source_context_ref,
    )
    normalized_actor_id = _required_uuid(actor_id, "actor_id")
    signal = GovernanceFeedbackSignal(
        id=uuid.uuid4(),
        signal_type=normalized_input.signal_type.value,
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
    return signal


def feedback_signal_to_dict(signal: GovernanceFeedbackSignal) -> dict[str, object]:
    """Project a durable feedback row without exposing ORM internals."""

    created_at = getattr(signal, "created_at", None)
    updated_at = getattr(signal, "updated_at", None)
    return {
        "signal_id": str(signal.id),
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
    "FeedbackSignalInput",
    "FeedbackSignalType",
    "GovernanceFeedbackSignal",
    "create_feedback_signal",
    "feedback_signal_to_dict",
    "normalize_audience_context",
]
