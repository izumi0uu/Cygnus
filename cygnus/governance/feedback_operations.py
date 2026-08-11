"""Operational read and event contracts for durable feedback routes.

This module owns the operator-facing projection of ``GovernanceFeedbackRoute``
and the worker event envelope. Route rows remain the only queue truth; this
module never creates, retries, or mutates route state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from enum import Enum
from typing import cast
import uuid

from loguru import logger
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from cygnus.governance.feedback import feedback_signal_ref
from cygnus.governance.feedback_routing import FeedbackRouteKind, FeedbackRouteState
from cygnus.review.surface import ObservationState, SurfaceObservation
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceFeedbackRoute,
    GovernanceFeedbackSignal,
    GovernanceReviewAssignment,
    GovernanceSignal,
    WikiPage,
    WikiPageDraft,
)
from cygnus.runtime.services.permission_engine import (
    build_wiki_draft_scope_clause,
    build_wiki_scope_clause,
)


_ROUTE_OPERATION_COVERAGE = (
    "feedback_route_lifecycle",
    "feedback_route_scope",
    "feedback_route_outcome_linkage",
)


class FeedbackRouteWorkerEvent(str, Enum):
    """Stable event names emitted by the feedback-route worker path."""

    CLAIMED = "claimed"
    LEASE_RECOVERED = "lease_recovered"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"
    EXECUTION_ERROR = "execution_error"
    FAILURE_RECORDING_ERROR = "failure_recording_error"


_EVENT_WARNING_LEVELS = frozenset(
    {
        FeedbackRouteWorkerEvent.BLOCKED,
        FeedbackRouteWorkerEvent.RETRY_SCHEDULED,
        FeedbackRouteWorkerEvent.FAILED,
        FeedbackRouteWorkerEvent.LEASE_LOST,
        FeedbackRouteWorkerEvent.EXECUTION_ERROR,
        FeedbackRouteWorkerEvent.FAILURE_RECORDING_ERROR,
    }
)


def _normalize_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return current


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _uuid_value(value: uuid.UUID | str | None, *, label: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start).total_seconds()), 3)


def _age_seconds(instant: datetime | None, *, now: datetime) -> int | None:
    if instant is None:
        return None
    return max(0, int((now - instant).total_seconds()))


def _optional_signal_ref(value: uuid.UUID | str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return (
        text if text.startswith("governance-signal:") else f"governance-signal:{text}"
    )


def _required_text(value: object, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    return normalized


def feedback_route_worker_event_fields(
    *,
    event: FeedbackRouteWorkerEvent | str,
    route_id: uuid.UUID | str,
    route_kind: FeedbackRouteKind | str,
    transition: str,
    attempt_count: int,
    duration_ms: int | None = None,
    outcome_signal_id: uuid.UUID | str | None = None,
    terminal_reason: str | None = None,
    exception_class: str | None = None,
) -> dict[str, object]:
    """Build the payload-free worker-event allowlist frozen by CYG-120."""

    try:
        event_value = FeedbackRouteWorkerEvent(event).value
    except ValueError as exc:
        raise ValueError(
            "event is not a supported feedback-route worker event"
        ) from exc
    try:
        kind_value = FeedbackRouteKind(route_kind).value
    except ValueError as exc:
        raise ValueError("route_kind is not supported") from exc
    normalized_route_id = _uuid_value(route_id, label="route_id")
    if normalized_route_id is None:
        raise ValueError("route_id is required")
    transition_value = _required_text(transition, label="transition", max_length=80)
    if attempt_count < 0:
        raise ValueError("attempt_count must not be negative")
    if duration_ms is not None and duration_ms < 0:
        raise ValueError("duration_ms must not be negative")
    normalized_reason = (
        _required_text(terminal_reason, label="terminal_reason", max_length=80)
        if terminal_reason is not None
        else None
    )
    normalized_exception = (
        _required_text(exception_class, label="exception_class", max_length=120)
        if exception_class is not None
        else None
    )
    return {
        "event": event_value,
        "route_id": str(normalized_route_id),
        "route_kind": kind_value,
        "transition": transition_value,
        "attempt_count": attempt_count,
        "duration_ms": duration_ms,
        "outcome_signal_ref": _optional_signal_ref(outcome_signal_id),
        "terminal_reason": normalized_reason,
        "exception_class": normalized_exception,
    }


def emit_feedback_route_worker_event(
    *,
    event: FeedbackRouteWorkerEvent | str,
    route_id: uuid.UUID | str,
    route_kind: FeedbackRouteKind | str,
    transition: str,
    attempt_count: int,
    duration_ms: int | None = None,
    outcome_signal_id: uuid.UUID | str | None = None,
    terminal_reason: str | None = None,
    exception_class: str | None = None,
) -> dict[str, object]:
    """Emit one structured worker event and return its normalized fields."""

    fields = feedback_route_worker_event_fields(
        event=event,
        route_id=route_id,
        route_kind=route_kind,
        transition=transition,
        attempt_count=attempt_count,
        duration_ms=duration_ms,
        outcome_signal_id=outcome_signal_id,
        terminal_reason=terminal_reason,
        exception_class=exception_class,
    )
    normalized_event = FeedbackRouteWorkerEvent(cast(str, fields["event"]))
    level = "WARNING" if normalized_event in _EVENT_WARNING_LEVELS else "INFO"
    logger.bind(**fields).log(level, "feedback_route_worker_event")
    return fields


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackRouteOperationsQuery:
    """Validated filters for the durable feedback-route operations read."""

    route_state: FeedbackRouteState | None = None
    route_kind: FeedbackRouteKind | None = None
    page: int = 1
    page_size: int = 50

    def __post_init__(self) -> None:
        if self.route_state is not None:
            object.__setattr__(
                self, "route_state", FeedbackRouteState(self.route_state)
            )
        if self.route_kind is not None:
            object.__setattr__(self, "route_kind", FeedbackRouteKind(self.route_kind))
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackRouteOperationsItem:
    """One permission-scoped route projection with no raw error payload."""

    route_id: uuid.UUID
    route_kind: FeedbackRouteKind
    route_state: FeedbackRouteState
    attempt_count: int
    next_attempt_at: datetime | None
    lease_expires_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    terminal_reason: str | None
    feedback_ref: str
    outcome_signal_ref: str | None
    review_assignment_ref: str | None
    is_due: bool
    lease_expired: bool
    due_age_seconds: int | None
    completion_latency_seconds: float | None
    now: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": str(self.route_id),
            "route_ref": f"feedback-route:{self.route_id}",
            "route_kind": self.route_kind.value,
            "route_state": self.route_state.value,
            "attempt_count": self.attempt_count,
            "next_attempt_at": _datetime_value(self.next_attempt_at),
            "lease_expires_at": _datetime_value(self.lease_expires_at),
            "completed_at": _datetime_value(self.completed_at),
            "created_at": _datetime_value(self.created_at),
            "updated_at": _datetime_value(self.updated_at),
            "terminal_reason": self.terminal_reason,
            "feedback_ref": self.feedback_ref,
            "outcome_signal_ref": self.outcome_signal_ref,
            "review_assignment_ref": (
                f"review-assignment:{self.review_assignment_ref}"
                if self.review_assignment_ref is not None
                else None
            ),
            "is_due": self.is_due,
            "lease_expired": self.lease_expired,
            "due_age_seconds": self.due_age_seconds,
            "completion_latency_seconds": self.completion_latency_seconds,
            "persisted": True,
            "rehearsal": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class _StateKindCount:
    route_state: FeedbackRouteState
    route_kind: FeedbackRouteKind
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _RetryCount:
    attempt_count: int
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _TerminalReasonCount:
    route_state: FeedbackRouteState
    terminal_reason: str
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackRouteOperationsSummary:
    """Bounded aggregate operational truth for one visible route scope."""

    total: int
    state_kind_counts: tuple[_StateKindCount, ...]
    oldest_due_at: datetime | None
    expired_running_leases: int
    retry_distribution: tuple[_RetryCount, ...]
    completed_latency_observed_count: int
    completed_latency_average_seconds: float | None
    completed_latency_max_seconds: float | None
    terminal_reason_counts: tuple[_TerminalReasonCount, ...]
    now: datetime

    def to_dict(self) -> dict[str, object]:
        states = {state.value: 0 for state in FeedbackRouteState}
        kinds = {kind.value: 0 for kind in FeedbackRouteKind}
        by_kind = {
            kind.value: {state.value: 0 for state in FeedbackRouteState}
            for kind in FeedbackRouteKind
        }
        for entry in self.state_kind_counts:
            states[entry.route_state.value] += entry.count
            kinds[entry.route_kind.value] += entry.count
            by_kind[entry.route_kind.value][entry.route_state.value] += entry.count
        reason_counts: dict[str, dict[str, int]] = {
            state.value: {} for state in FeedbackRouteState
        }
        for entry in self.terminal_reason_counts:
            reason_counts[entry.route_state.value][entry.terminal_reason] = entry.count
        oldest_age = _age_seconds(self.oldest_due_at, now=self.now)
        return {
            "total": self.total,
            "counts_by_state": states,
            "counts_by_kind": kinds,
            "counts_by_kind_and_state": by_kind,
            "oldest_due_queued_at": _datetime_value(self.oldest_due_at),
            "oldest_due_queued_age_seconds": oldest_age,
            "expired_running_leases": self.expired_running_leases,
            "retry_distribution": {
                str(entry.attempt_count): entry.count
                for entry in self.retry_distribution
            },
            "completed_latency_seconds": {
                "observed_count": self.completed_latency_observed_count,
                "average": self.completed_latency_average_seconds,
                "maximum": self.completed_latency_max_seconds,
            },
            "terminal_reason_counts": reason_counts,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class _FeedbackLink:
    feedback_ref: str
    signal_type: str
    object_id: str | None
    page_id: uuid.UUID | None
    draft_id: uuid.UUID | None
    created_at: datetime | None

    def to_dict(self) -> dict[str, object]:
        return {
            "feedback_ref": self.feedback_ref,
            "signal_type": self.signal_type,
            "object_id": self.object_id,
            "page_id": str(self.page_id) if self.page_id is not None else None,
            "draft_id": str(self.draft_id) if self.draft_id is not None else None,
            "created_at": _datetime_value(self.created_at),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class _OutcomeLink:
    signal_ref: str
    signal_type: str
    status: str
    object_ref: str
    page_id: uuid.UUID | None
    observed_at: datetime | None
    resolved_at: datetime | None

    def to_dict(self) -> dict[str, object]:
        return {
            "signal_ref": self.signal_ref,
            "signal_type": self.signal_type,
            "status": self.status,
            "object_ref": self.object_ref,
            "page_id": str(self.page_id) if self.page_id is not None else None,
            "observed_at": _datetime_value(self.observed_at),
            "resolved_at": _datetime_value(self.resolved_at),
            "persisted": True,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class _AssignmentLink:
    trace_ref: str
    lifecycle_state: str
    owner_ref: str | None
    version: int
    updated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "trace_ref": self.trace_ref,
            "lifecycle_state": self.lifecycle_state,
            "owner_ref": self.owner_ref,
            "version": self.version,
            "updated_at": _datetime_value(self.updated_at),
            "persisted": True,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class _AuditTrace:
    trace_ref: str
    action: str
    decision: str
    occurred_at: datetime | None

    def to_dict(self) -> dict[str, object]:
        return {
            "trace_ref": self.trace_ref,
            "action": self.action,
            "decision": self.decision,
            "occurred_at": _datetime_value(self.occurred_at),
            "persisted": True,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackRouteOperationsPage:
    items: tuple[FeedbackRouteOperationsItem, ...]
    summary: FeedbackRouteOperationsSummary
    page: int
    page_size: int

    def to_dict(self) -> dict[str, object]:
        observation = SurfaceObservation(
            state=ObservationState.READY,
            observed_count=self.summary.total,
            reason="durable_feedback_route_operations",
            covered_signals=_ROUTE_OPERATION_COVERAGE,
        )
        return {
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary.to_dict(),
            "total": self.summary.total,
            "page": self.page,
            "page_size": self.page_size,
            "observation": observation.to_dict(),
            "persisted": True,
            "rehearsal": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackRouteOperationsDetail:
    item: FeedbackRouteOperationsItem
    feedback: _FeedbackLink
    outcome: _OutcomeLink | None
    assignment: _AssignmentLink | None
    audit_traces: tuple[_AuditTrace, ...]

    def to_dict(self) -> dict[str, object]:
        observation = SurfaceObservation(
            state=ObservationState.READY,
            observed_count=1,
            reason="durable_feedback_route_operation_detail",
            covered_signals=_ROUTE_OPERATION_COVERAGE,
        )
        return {
            "route": self.item.to_dict(),
            "feedback": self.feedback.to_dict(),
            "outcome": self.outcome.to_dict() if self.outcome is not None else None,
            "review_assignment": (
                self.assignment.to_dict() if self.assignment is not None else None
            ),
            "audit_traces": [trace.to_dict() for trace in self.audit_traces],
            "observation": observation.to_dict(),
            "persisted": True,
            "rehearsal": False,
        }


def feedback_route_scope_clause(
    current_user: Employee,
) -> ColumnElement[bool] | None:
    """Return the SQL predicate for routes tied to visible Wiki truth."""

    page_scope = build_wiki_scope_clause(current_user)
    draft_scope = build_wiki_draft_scope_clause(current_user)
    if page_scope is None and draft_scope is None:
        return None

    if page_scope is None:
        visible_page = GovernanceFeedbackSignal.page_id.is_not(None)
    else:
        visible_page = exists(
            select(WikiPage.id)
            .where(
                WikiPage.id == GovernanceFeedbackSignal.page_id,
                page_scope,
            )
            .correlate(GovernanceFeedbackSignal)
        )
    if draft_scope is None:
        visible_draft = GovernanceFeedbackSignal.draft_id.is_not(None)
    else:
        visible_draft = exists(
            select(WikiPageDraft.id)
            .where(
                WikiPageDraft.id == GovernanceFeedbackSignal.draft_id,
                draft_scope,
            )
            .correlate(GovernanceFeedbackSignal)
        )

    visible_feedback = (
        select(GovernanceFeedbackSignal.id)
        .where(
            GovernanceFeedbackSignal.id == GovernanceFeedbackRoute.feedback_signal_id,
            or_(visible_page, visible_draft),
        )
        .correlate(GovernanceFeedbackRoute)
    )
    return exists(visible_feedback)


def _route_filters(
    *,
    current_user: Employee,
    query: FeedbackRouteOperationsQuery,
    route_id: uuid.UUID | None = None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    scope_clause = feedback_route_scope_clause(current_user)
    if scope_clause is not None:
        filters.append(scope_clause)
    if query.route_state is not None:
        filters.append(
            GovernanceFeedbackRoute.lifecycle_state == query.route_state.value
        )
    if query.route_kind is not None:
        filters.append(GovernanceFeedbackRoute.route_kind == query.route_kind.value)
    if route_id is not None:
        filters.append(GovernanceFeedbackRoute.id == route_id)
    return filters


def _route_rows_statement(
    filters: list[ColumnElement[bool]],
):
    return (
        select(
            GovernanceFeedbackRoute,
            GovernanceFeedbackSignal,
            GovernanceSignal,
            GovernanceReviewAssignment,
        )
        .join(
            GovernanceFeedbackSignal,
            GovernanceFeedbackSignal.id == GovernanceFeedbackRoute.feedback_signal_id,
        )
        .outerjoin(
            GovernanceSignal,
            GovernanceSignal.id == GovernanceFeedbackRoute.outcome_signal_id,
        )
        .outerjoin(
            GovernanceReviewAssignment,
            GovernanceReviewAssignment.signal_id == GovernanceSignal.id,
        )
        .where(*filters)
    )


def _item(
    *,
    route: GovernanceFeedbackRoute,
    feedback: GovernanceFeedbackSignal,
    outcome: GovernanceSignal | None,
    assignment: GovernanceReviewAssignment | None,
    now: datetime,
) -> FeedbackRouteOperationsItem:
    state = FeedbackRouteState(route.lifecycle_state)
    kind = FeedbackRouteKind(route.route_kind)
    due_at = (
        route.next_attempt_at or route.created_at
        if state is FeedbackRouteState.QUEUED
        else None
    )
    is_due = due_at is not None and due_at <= now
    lease_expired = (
        state is FeedbackRouteState.RUNNING
        and route.lease_expires_at is not None
        and route.lease_expires_at <= now
    )
    return FeedbackRouteOperationsItem(
        route_id=route.id,
        route_kind=kind,
        route_state=state,
        attempt_count=route.attempt_count,
        next_attempt_at=route.next_attempt_at,
        lease_expires_at=route.lease_expires_at,
        completed_at=route.completed_at,
        created_at=route.created_at,
        updated_at=route.updated_at,
        terminal_reason=route.terminal_reason,
        feedback_ref=feedback_signal_ref(feedback),
        outcome_signal_ref=outcome.signal_ref if outcome is not None else None,
        review_assignment_ref=(str(assignment.id) if assignment is not None else None),
        is_due=is_due,
        lease_expired=lease_expired,
        due_age_seconds=_age_seconds(due_at, now=now) if is_due else None,
        completion_latency_seconds=(
            _duration_seconds(route.created_at, route.completed_at)
            if state is FeedbackRouteState.COMPLETED
            else None
        ),
        now=now,
    )


def _summary_from_rows(
    *,
    grouped: list[tuple[str, str, int]],
    metrics: tuple[datetime | None, int, int, float | None, float | None],
    retries: list[tuple[int, int]],
    reasons: list[tuple[str, str, int]],
    now: datetime,
) -> FeedbackRouteOperationsSummary:
    state_kind_counts = tuple(
        _StateKindCount(
            route_state=FeedbackRouteState(route_state),
            route_kind=FeedbackRouteKind(route_kind),
            count=count,
        )
        for route_state, route_kind, count in grouped
    )
    total = sum(entry.count for entry in state_kind_counts)
    oldest_due_at, expired_running_leases, completed_count, average, maximum = metrics
    retry_distribution = tuple(
        _RetryCount(attempt_count=attempt_count, count=count)
        for attempt_count, count in retries
    )
    terminal_reason_counts = tuple(
        _TerminalReasonCount(
            route_state=FeedbackRouteState(route_state),
            terminal_reason=terminal_reason,
            count=count,
        )
        for route_state, terminal_reason, count in reasons
    )
    return FeedbackRouteOperationsSummary(
        total=total,
        state_kind_counts=state_kind_counts,
        oldest_due_at=oldest_due_at,
        expired_running_leases=expired_running_leases,
        retry_distribution=retry_distribution,
        completed_latency_observed_count=completed_count,
        completed_latency_average_seconds=average,
        completed_latency_max_seconds=maximum,
        terminal_reason_counts=terminal_reason_counts,
        now=now,
    )


async def list_feedback_route_operations(
    session: AsyncSession,
    *,
    current_user: Employee,
    query: FeedbackRouteOperationsQuery,
    now: datetime | None = None,
) -> FeedbackRouteOperationsPage:
    """List visible durable route truth and its operational aggregates."""

    current_time = _normalize_now(now)
    filters = _route_filters(current_user=current_user, query=query)
    grouped_result = await session.execute(
        select(
            GovernanceFeedbackRoute.lifecycle_state,
            GovernanceFeedbackRoute.route_kind,
            func.count(GovernanceFeedbackRoute.id),
        )
        .where(*filters)
        .group_by(
            GovernanceFeedbackRoute.lifecycle_state,
            GovernanceFeedbackRoute.route_kind,
        )
        .order_by(
            GovernanceFeedbackRoute.lifecycle_state,
            GovernanceFeedbackRoute.route_kind,
        )
    )
    grouped = cast(
        list[tuple[str, str, int]], cast(object, grouped_result.tuples().all())
    )

    due_at = func.coalesce(
        GovernanceFeedbackRoute.next_attempt_at,
        GovernanceFeedbackRoute.created_at,
    )
    completion_duration = func.extract(
        "epoch",
        GovernanceFeedbackRoute.completed_at - GovernanceFeedbackRoute.created_at,
    )
    metrics_result = await session.execute(
        select(
            func.min(due_at).filter(
                and_(
                    GovernanceFeedbackRoute.lifecycle_state
                    == FeedbackRouteState.QUEUED.value,
                    due_at <= current_time,
                )
            ),
            func.count(GovernanceFeedbackRoute.id).filter(
                and_(
                    GovernanceFeedbackRoute.lifecycle_state
                    == FeedbackRouteState.RUNNING.value,
                    GovernanceFeedbackRoute.lease_expires_at <= current_time,
                )
            ),
            func.count(GovernanceFeedbackRoute.id).filter(
                GovernanceFeedbackRoute.lifecycle_state
                == FeedbackRouteState.COMPLETED.value
            ),
            func.avg(completion_duration).filter(
                GovernanceFeedbackRoute.lifecycle_state
                == FeedbackRouteState.COMPLETED.value
            ),
            func.max(completion_duration).filter(
                GovernanceFeedbackRoute.lifecycle_state
                == FeedbackRouteState.COMPLETED.value
            ),
        ).where(*filters)
    )
    metrics_row = cast(
        tuple[
            datetime | None,
            int,
            int,
            Decimal | float | int | None,
            Decimal | float | int | None,
        ],
        cast(object, metrics_result.one()),
    )
    metrics = (
        metrics_row[0],
        metrics_row[1],
        metrics_row[2],
        float(metrics_row[3]) if metrics_row[3] is not None else None,
        float(metrics_row[4]) if metrics_row[4] is not None else None,
    )

    retries_result = await session.execute(
        select(
            GovernanceFeedbackRoute.attempt_count,
            func.count(GovernanceFeedbackRoute.id),
        )
        .where(*filters)
        .group_by(GovernanceFeedbackRoute.attempt_count)
        .order_by(GovernanceFeedbackRoute.attempt_count)
    )
    retries = cast(list[tuple[int, int]], cast(object, retries_result.tuples().all()))

    reasons_result = await session.execute(
        select(
            GovernanceFeedbackRoute.lifecycle_state,
            GovernanceFeedbackRoute.terminal_reason,
            func.count(GovernanceFeedbackRoute.id),
        )
        .where(
            *filters,
            GovernanceFeedbackRoute.lifecycle_state.in_(
                (
                    FeedbackRouteState.BLOCKED.value,
                    FeedbackRouteState.FAILED.value,
                )
            ),
            GovernanceFeedbackRoute.terminal_reason.is_not(None),
        )
        .group_by(
            GovernanceFeedbackRoute.lifecycle_state,
            GovernanceFeedbackRoute.terminal_reason,
        )
        .order_by(
            GovernanceFeedbackRoute.lifecycle_state,
            GovernanceFeedbackRoute.terminal_reason,
        )
    )
    reason_rows = cast(
        list[tuple[str, str | None, int]],
        cast(object, reasons_result.tuples().all()),
    )
    reasons = [
        (route_state, terminal_reason, count)
        for route_state, terminal_reason, count in reason_rows
        if terminal_reason is not None
    ]
    summary = _summary_from_rows(
        grouped=grouped,
        metrics=metrics,
        retries=retries,
        reasons=reasons,
        now=current_time,
    )

    rows_result = await session.execute(
        _route_rows_statement(filters)
        .order_by(
            GovernanceFeedbackRoute.updated_at.desc(),
            GovernanceFeedbackRoute.id.desc(),
        )
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    rows = cast(
        list[
            tuple[
                GovernanceFeedbackRoute,
                GovernanceFeedbackSignal,
                GovernanceSignal | None,
                GovernanceReviewAssignment | None,
            ]
        ],
        cast(object, rows_result.all()),
    )
    items = tuple(
        _item(
            route=route,
            feedback=feedback,
            outcome=outcome,
            assignment=assignment,
            now=current_time,
        )
        for route, feedback, outcome, assignment in rows
    )
    return FeedbackRouteOperationsPage(
        items=items,
        summary=summary,
        page=query.page,
        page_size=query.page_size,
    )


async def get_feedback_route_operation(
    session: AsyncSession,
    *,
    current_user: Employee,
    route_id: uuid.UUID | str,
    now: datetime | None = None,
) -> FeedbackRouteOperationsDetail | None:
    """Read one scoped route with safe feedback, outcome, assignment, and audit links."""

    normalized_id = _uuid_value(route_id, label="route_id")
    if normalized_id is None:
        raise ValueError("route_id is required")
    current_time = _normalize_now(now)
    query = FeedbackRouteOperationsQuery(page=1, page_size=1)
    filters = _route_filters(
        current_user=current_user,
        query=query,
        route_id=normalized_id,
    )
    row_result = await session.execute(_route_rows_statement(filters).limit(1))
    row = cast(
        tuple[
            GovernanceFeedbackRoute,
            GovernanceFeedbackSignal,
            GovernanceSignal | None,
            GovernanceReviewAssignment | None,
        ]
        | None,
        cast(object, row_result.one_or_none()),
    )
    if row is None:
        return None
    route, feedback, outcome, assignment = row
    item = _item(
        route=route,
        feedback=feedback,
        outcome=outcome,
        assignment=assignment,
        now=current_time,
    )
    audit_result = await session.execute(
        select(AuditLog)
        .where(
            or_(
                and_(
                    AuditLog.action == "record_feedback_signal",
                    AuditLog.resource_type == "governance_feedback_signal",
                    AuditLog.resource_id == str(feedback.id),
                ),
                and_(
                    AuditLog.action == "execute_feedback_route",
                    AuditLog.resource_type == "governance_feedback_route",
                    AuditLog.resource_id == str(route.id),
                ),
            )
        )
        .order_by(AuditLog.timestamp, AuditLog.id)
    )
    audit_rows = cast(list[AuditLog], cast(object, audit_result.scalars().all()))
    feedback_link = _FeedbackLink(
        feedback_ref=feedback_signal_ref(feedback),
        signal_type=feedback.signal_type,
        object_id=feedback.object_id,
        page_id=feedback.page_id,
        draft_id=feedback.draft_id,
        created_at=feedback.created_at,
    )
    outcome_link = (
        _OutcomeLink(
            signal_ref=outcome.signal_ref,
            signal_type=outcome.signal_type,
            status=outcome.status,
            object_ref=outcome.object_ref,
            page_id=outcome.page_id,
            observed_at=outcome.observed_at,
            resolved_at=outcome.resolved_at,
        )
        if outcome is not None
        else None
    )
    assignment_link = (
        _AssignmentLink(
            trace_ref=f"review-assignment:{assignment.id}",
            lifecycle_state=assignment.lifecycle_state,
            owner_ref=assignment.owner_ref,
            version=assignment.version,
            updated_at=assignment.updated_at,
        )
        if assignment is not None
        else None
    )
    audit_traces = tuple(
        _AuditTrace(
            trace_ref=f"audit-log:{audit.id}",
            action=audit.action,
            decision=audit.decision,
            occurred_at=audit.timestamp,
        )
        for audit in audit_rows
    )
    return FeedbackRouteOperationsDetail(
        item=item,
        feedback=feedback_link,
        outcome=outcome_link,
        assignment=assignment_link,
        audit_traces=audit_traces,
    )


__all__ = [
    "FeedbackRouteOperationsDetail",
    "FeedbackRouteOperationsItem",
    "FeedbackRouteOperationsPage",
    "FeedbackRouteOperationsQuery",
    "FeedbackRouteOperationsSummary",
    "FeedbackRouteWorkerEvent",
    "emit_feedback_route_worker_event",
    "feedback_route_scope_clause",
    "feedback_route_worker_event_fields",
    "get_feedback_route_operation",
    "list_feedback_route_operations",
]
