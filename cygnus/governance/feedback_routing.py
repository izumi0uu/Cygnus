"""Typed, durable routing ownership for governed consumption feedback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.feedback import FeedbackSignalType
from cygnus.governance.ledger import lock_governance_command
from cygnus.observability import current_request_id, current_traceparent
from cygnus.runtime.database.models import (
    GovernanceFeedbackRoute,
    GovernanceFeedbackSignal,
)


class FeedbackRouteConflict(ValueError):
    """Persisted feedback routing truth conflicts with the frozen policy."""


class FeedbackRouteKind(str, Enum):
    """Durable work queue selected by the frozen routing policy."""

    REVIEW = "review"
    REFRESH = "refresh"


class FeedbackRouteState(str, Enum):
    """Durable feedback-route lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


_ROUTING_POLICY: dict[FeedbackSignalType, FeedbackRouteKind] = {
    FeedbackSignalType.LOW_RATING: FeedbackRouteKind.REVIEW,
    FeedbackSignalType.STALE_ANSWER: FeedbackRouteKind.REFRESH,
}


@dataclass(frozen=True, slots=True)
class FeedbackRoutingProjection:
    """Public routing truth projected from a persisted route row."""

    route_id: str | None
    route_ref: str | None
    route_kind: str | None
    route_state: str | None
    outcome_signal_id: str | None
    outcome_signal_ref: str | None
    terminal_reason: str | None
    routing_state: str
    review_queued: bool
    refresh_queued: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "route_ref": self.route_ref,
            "route_kind": self.route_kind,
            "route_state": self.route_state,
            "outcome_signal_id": self.outcome_signal_id,
            "outcome_signal_ref": self.outcome_signal_ref,
            "terminal_reason": self.terminal_reason,
            "routing_state": self.routing_state,
            "review_queued": self.review_queued,
            "refresh_queued": self.refresh_queued,
        }


def feedback_route_kind(
    signal_type: FeedbackSignalType | str,
) -> FeedbackRouteKind | None:
    """Apply the explicit routing policy without model or prompt inference."""

    try:
        normalized_type = (
            signal_type
            if isinstance(signal_type, FeedbackSignalType)
            else FeedbackSignalType(signal_type.strip())
        )
    except (AttributeError, ValueError) as exc:
        raise ValueError("signal_type is not supported") from exc
    return _ROUTING_POLICY.get(normalized_type)


async def route_feedback_signal(
    session: AsyncSession,
    signal: GovernanceFeedbackSignal,
    *,
    replayed: bool = False,
) -> GovernanceFeedbackRoute | None:
    """Create a mapped route or replay the signal's existing durable route.

    The aggregate lock and database uniqueness constraint jointly prevent
    duplicate queue truth. A replay may only return an already persisted route;
    it never repairs a missing route outside the original mutation audit.
    """

    await lock_governance_command(session, f"feedback-route:{signal.id}")
    existing_routes = tuple(
        (
            await session.execute(
                select(GovernanceFeedbackRoute)
                .where(GovernanceFeedbackRoute.feedback_signal_id == signal.id)
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(existing_routes) > 1:
        raise FeedbackRouteConflict(
            f"feedback_signal_id={signal.id} has multiple durable routes"
        )

    route_kind = feedback_route_kind(signal.signal_type)
    if existing_routes:
        existing = existing_routes[0]
        existing_kind = FeedbackRouteKind(existing.route_kind)
        _ = FeedbackRouteState(existing.lifecycle_state)
        if route_kind is None or existing_kind is not route_kind:
            raise FeedbackRouteConflict(
                f"feedback_signal_id={signal.id} route conflicts with frozen policy"
            )
        return existing

    if route_kind is None:
        return None
    if replayed:
        raise FeedbackRouteConflict(
            f"feedback_signal_id={signal.id} replay is missing its durable route"
        )
    effective_correlation = current_request_id()
    correlation_uuid = None
    if effective_correlation:
        try:
            correlation_uuid = uuid.UUID(effective_correlation)
        except (TypeError, ValueError):
            correlation_uuid = None
    route = GovernanceFeedbackRoute(
        id=uuid.uuid4(),
        feedback_signal_id=signal.id,
        correlation_id=correlation_uuid,
        traceparent=current_traceparent(),
        route_kind=route_kind.value,
        lifecycle_state=FeedbackRouteState.QUEUED.value,
    )
    session.add(route)
    await session.flush()
    return route


def project_feedback_route(
    route: GovernanceFeedbackRoute | None,
) -> FeedbackRoutingProjection:
    """Project queue flags only from a durable route row and its state."""

    if route is None:
        return FeedbackRoutingProjection(
            route_id=None,
            route_ref=None,
            route_kind=None,
            route_state=None,
            outcome_signal_id=None,
            outcome_signal_ref=None,
            terminal_reason=None,
            routing_state="recorded_only",
            review_queued=False,
            refresh_queued=False,
        )

    route_kind = FeedbackRouteKind(route.route_kind)
    route_state = FeedbackRouteState(route.lifecycle_state)
    queued = route_state is FeedbackRouteState.QUEUED
    route_id = str(route.id)
    return FeedbackRoutingProjection(
        route_id=route_id,
        route_ref=f"feedback-route:{route_id}",
        route_kind=route_kind.value,
        route_state=route_state.value,
        outcome_signal_id=(
            str(route.outcome_signal_id)
            if route.outcome_signal_id is not None
            else None
        ),
        outcome_signal_ref=(
            f"governance-signal:{route.outcome_signal_id}"
            if route.outcome_signal_id is not None
            else None
        ),
        terminal_reason=route.terminal_reason,
        routing_state=f"{route_kind.value}_{route_state.value}",
        review_queued=queued and route_kind is FeedbackRouteKind.REVIEW,
        refresh_queued=queued and route_kind is FeedbackRouteKind.REFRESH,
    )


__all__ = [
    "FeedbackRouteConflict",
    "FeedbackRouteKind",
    "FeedbackRouteState",
    "FeedbackRoutingProjection",
    "feedback_route_kind",
    "project_feedback_route",
    "route_feedback_signal",
]
