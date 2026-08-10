"""Bounded execution of durable governed consumption-feedback routes.

Routes are the durable queue truth. This module leases only committed route rows,
revalidates their persisted target at execution time, and materializes review work
through the existing governance-signal service. Every mutation flushes only; the
worker wrapper owns transaction boundaries and commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObject
from cygnus.evidence.records import EvidenceSourceType, FreshnessState
from cygnus.governance.feedback import (
    FeedbackSignalType,
    feedback_signal_ref,
    normalize_audience_context,
)
from cygnus.governance.feedback_routing import (
    FeedbackRouteKind,
    FeedbackRouteState,
    feedback_route_kind,
)
from cygnus.governance.signals import GovernanceSignalInput, create_governance_signal
from cygnus.review.intake import PressureSignalType
from cygnus.retrieval.substrate_provider import wiki_page_to_knowledge_object
from cygnus.runtime.database.models import (
    Employee,
    GovernanceFeedbackRoute,
    GovernanceFeedbackSignal,
    GovernanceSignal,
    WikiPage,
    WikiPageDraft,
)
from cygnus.runtime.services.audit_service import log_audit


MAX_FEEDBACK_ROUTE_ATTEMPTS = 3
FEEDBACK_ROUTE_LEASE_SECONDS = 60
FEEDBACK_ROUTE_RETRY_BASE_SECONDS = 30

_TARGET_REQUIRED = "target_required"
_TARGET_NOT_MATERIALIZED = "target_not_materialized"
_TARGET_INELIGIBLE = "target_ineligible"
_TARGET_IDENTITY_CHANGED = "target_identity_changed"
_ROUTE_POLICY_CHANGED = "route_policy_changed"
_RETRY_EXHAUSTED = "retry_exhausted"

_TERMINAL_ROUTE_STATES = frozenset(
    {
        FeedbackRouteState.COMPLETED,
        FeedbackRouteState.BLOCKED,
        FeedbackRouteState.FAILED,
    }
)


class FeedbackRouteLeaseLost(RuntimeError):
    """A worker no longer owns the route lease it is trying to mutate."""


@dataclass(frozen=True, slots=True)
class FeedbackRouteClaim:
    """A fencing lease returned from one durable route claim sweep."""

    route_id: uuid.UUID
    lease_token: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class _FeedbackTarget:
    page: WikiPage
    knowledge_object: KnowledgeObject


def _route_ref(route_id: uuid.UUID) -> str:
    return f"feedback-route:{route_id}"


def _outcome_signal_ref(signal_id: uuid.UUID) -> str:
    return f"governance-signal:{signal_id}"


def _now(value: object) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None:
        raise ValueError("now must include a timezone")
    return value


def _claim_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("limit must be a positive integer")
    return value


def _route_state(route: GovernanceFeedbackRoute) -> FeedbackRouteState:
    try:
        return FeedbackRouteState(route.lifecycle_state)
    except ValueError as exc:
        raise RuntimeError(
            f"feedback route {route.id} has an invalid lifecycle state"
        ) from exc


def _terminal(route: GovernanceFeedbackRoute) -> bool:
    return _route_state(route) in _TERMINAL_ROUTE_STATES


def _new_lease_token() -> str:
    """Return an opaque, cryptographically random token within the DB bound."""
    return secrets.token_urlsafe(32)


async def claim_feedback_routes(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> tuple[FeedbackRouteClaim, ...]:
    """Lease due queued routes and recover expired running leases.

    Rows are claimed under ``FOR UPDATE SKIP LOCKED``. The expiration sweep also
    terminalizes any route whose third lease expired, rather than leaving it in a
    permanently unclaimable running state.
    """

    current_time = _now(now)
    claim_limit = _claim_limit(limit)
    due = or_(
        and_(
            GovernanceFeedbackRoute.lifecycle_state == FeedbackRouteState.QUEUED.value,
            or_(
                GovernanceFeedbackRoute.next_attempt_at.is_(None),
                GovernanceFeedbackRoute.next_attempt_at <= current_time,
            ),
        ),
        and_(
            GovernanceFeedbackRoute.lifecycle_state == FeedbackRouteState.RUNNING.value,
            GovernanceFeedbackRoute.lease_expires_at <= current_time,
        ),
    )
    statement = (
        select(GovernanceFeedbackRoute)
        .where(due)
        .order_by(
            func.coalesce(
                GovernanceFeedbackRoute.next_attempt_at,
                GovernanceFeedbackRoute.lease_expires_at,
                GovernanceFeedbackRoute.created_at,
            ),
            GovernanceFeedbackRoute.created_at,
            GovernanceFeedbackRoute.id,
        )
        .limit(claim_limit)
        .with_for_update(skip_locked=True)
    )
    routes = tuple((await session.execute(statement)).scalars().all())

    claims: list[FeedbackRouteClaim] = []
    changed = False
    for route in routes:
        state = _route_state(route)
        if state not in {
            FeedbackRouteState.QUEUED,
            FeedbackRouteState.RUNNING,
        }:
            continue

        attempts = route.attempt_count
        if attempts >= MAX_FEEDBACK_ROUTE_ATTEMPTS:
            feedback, actor = await _feedback_and_actor(session, route)
            _mark_failed(
                route,
                now=current_time,
                error=(
                    "feedback route lease expired before execution completed"
                    if state is FeedbackRouteState.RUNNING
                    else "feedback route retry budget was exhausted before claim"
                ),
            )
            await _append_terminal_audit(
                session,
                route=route,
                feedback=feedback,
                actor=actor,
                outcome="failed",
                terminal_reason=_RETRY_EXHAUSTED,
            )
            changed = True
            continue

        lease_token = _new_lease_token()
        route.lifecycle_state = FeedbackRouteState.RUNNING.value
        route.attempt_count = attempts + 1
        route.next_attempt_at = None
        route.lease_token = lease_token
        route.lease_expires_at = current_time + timedelta(
            seconds=FEEDBACK_ROUTE_LEASE_SECONDS
        )
        route.outcome_signal_id = None
        route.terminal_reason = None
        route.last_error = None
        route.completed_at = None
        claims.append(
            FeedbackRouteClaim(
                route_id=route.id,
                lease_token=lease_token,
                attempt_count=route.attempt_count,
            )
        )
        changed = True

    if changed:
        await session.flush()
    return tuple(claims)


async def execute_feedback_route(
    session: AsyncSession,
    claim: FeedbackRouteClaim,
    *,
    now: datetime | None = None,
) -> GovernanceFeedbackRoute:
    """Complete or block one still-owned route without committing.

    Terminal routes replay their durable truth before fencing. Every nonterminal
    path checks both the random lease token and an unexpired lease so an expired
    worker cannot finalize a route before a recovery sweep reclaims it.
    """

    current_time = _now(now)
    route = await _locked_route(session, claim.route_id)
    if route is None:
        raise FeedbackRouteLeaseLost(
            f"feedback route {claim.route_id} no longer exists"
        )
    if _terminal(route):
        return route
    _require_active_lease(route, claim, now=current_time)

    feedback, actor = await _feedback_and_actor(session, route)
    if not _matches_route_policy(route, feedback):
        return await _block_feedback_route(
            session,
            route=route,
            feedback=feedback,
            actor=actor,
            reason=_ROUTE_POLICY_CHANGED,
            now=current_time,
        )

    target, block_reason = await _resolve_target(session, feedback)
    if block_reason is not None:
        return await _block_feedback_route(
            session,
            route=route,
            feedback=feedback,
            actor=actor,
            reason=block_reason,
            now=current_time,
        )
    if target is None:
        raise AssertionError("target resolution returned neither target nor reason")

    signal_input = _governance_signal_input(route, feedback, target)
    outcome_signal = await create_governance_signal(
        session,
        signal_input,
        created_by_id=actor.id,
    )
    _mark_completed(route, outcome_signal, now=current_time)
    await _append_terminal_audit(
        session,
        route=route,
        feedback=feedback,
        actor=actor,
        outcome="completed",
        outcome_signal=outcome_signal,
    )
    await session.flush()
    return route


async def record_feedback_route_failure(
    session: AsyncSession,
    claim: FeedbackRouteClaim,
    *,
    error: object,
    now: datetime | None = None,
) -> GovernanceFeedbackRoute:
    """Requeue a still-owned failed execution or terminalize its final attempt."""

    current_time = _now(now)
    route = await _locked_route(session, claim.route_id)
    if route is None:
        raise FeedbackRouteLeaseLost(
            f"feedback route {claim.route_id} no longer exists"
        )
    if _terminal(route):
        return route
    _require_active_lease(route, claim, now=current_time)

    error_text = _failure_text(error)
    if route.attempt_count >= MAX_FEEDBACK_ROUTE_ATTEMPTS:
        feedback, actor = await _feedback_and_actor(session, route)
        _mark_failed(route, now=current_time, error=error_text)
        await _append_terminal_audit(
            session,
            route=route,
            feedback=feedback,
            actor=actor,
            outcome="failed",
            terminal_reason=_RETRY_EXHAUSTED,
        )
    else:
        _requeue_after_failure(route, now=current_time, error=error_text)
    await session.flush()
    return route


async def _locked_route(
    session: AsyncSession,
    route_id: uuid.UUID,
) -> GovernanceFeedbackRoute | None:
    statement = (
        select(GovernanceFeedbackRoute)
        .where(GovernanceFeedbackRoute.id == route_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def _feedback_and_actor(
    session: AsyncSession,
    route: GovernanceFeedbackRoute,
) -> tuple[GovernanceFeedbackSignal, Employee]:
    feedback = (
        await session.execute(
            select(GovernanceFeedbackSignal).where(
                GovernanceFeedbackSignal.id == route.feedback_signal_id
            )
        )
    ).scalar_one_or_none()
    if feedback is None:
        raise RuntimeError(f"feedback route {route.id} has no feedback signal")

    actor = (
        await session.execute(select(Employee).where(Employee.id == feedback.actor_id))
    ).scalar_one_or_none()
    if actor is None:
        raise RuntimeError(f"feedback route {route.id} has no originating actor")
    return feedback, actor


def _matches_route_policy(
    route: GovernanceFeedbackRoute,
    feedback: GovernanceFeedbackSignal,
) -> bool:
    try:
        route_kind = FeedbackRouteKind(route.route_kind)
        expected_kind = feedback_route_kind(feedback.signal_type)
    except ValueError as exc:
        raise RuntimeError(
            f"feedback route {route.id} has invalid routing data"
        ) from exc
    return expected_kind is route_kind


async def _resolve_target(
    session: AsyncSession,
    feedback: GovernanceFeedbackSignal,
) -> tuple[_FeedbackTarget | None, str | None]:
    page_id = feedback.page_id
    if feedback.draft_id is not None:
        draft = (
            await session.execute(
                select(WikiPageDraft)
                .where(WikiPageDraft.id == feedback.draft_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            return None, _TARGET_REQUIRED
        if draft.page_id is None:
            return None, _TARGET_NOT_MATERIALIZED
        if page_id is None:
            page_id = draft.page_id
        elif page_id != draft.page_id:
            return None, _TARGET_IDENTITY_CHANGED

    if page_id is None:
        return None, _TARGET_REQUIRED

    page = (
        await session.execute(
            select(WikiPage).where(WikiPage.id == page_id).with_for_update()
        )
    ).scalar_one_or_none()
    if page is None:
        return None, _TARGET_REQUIRED

    knowledge_object = wiki_page_to_knowledge_object(page)
    if knowledge_object is None:
        return None, _TARGET_INELIGIBLE
    if feedback.object_id != knowledge_object.object_id:
        return None, _TARGET_IDENTITY_CHANGED
    return _FeedbackTarget(page=page, knowledge_object=knowledge_object), None


def _governance_signal_input(
    route: GovernanceFeedbackRoute,
    feedback: GovernanceFeedbackSignal,
    target: _FeedbackTarget,
) -> GovernanceSignalInput:
    feedback_type = FeedbackSignalType(feedback.signal_type)
    if feedback_type is FeedbackSignalType.LOW_RATING:
        signal_type = PressureSignalType.LOW_RATING
        freshness = FreshnessState.UNKNOWN
        reason = (
            "Low rating requires governed quality review before any knowledge change."
        )
        summary = "Low-rating consumption feedback requires governed review."
    elif feedback_type is FeedbackSignalType.STALE_ANSWER:
        signal_type = PressureSignalType.STALE_ANSWER
        freshness = FreshnessState.STALE
        reason = (
            "Stale answer indicates suspected freshness risk requiring evidence "
            "verification."
        )
        summary = "Stale-answer consumption feedback requires freshness review."
    else:
        raise RuntimeError(f"feedback route {route.id} has an unmapped feedback type")

    route_ref = _route_ref(route.id)
    feedback_ref = feedback_signal_ref(feedback)
    observed_at = getattr(feedback, "created_at", None)
    return GovernanceSignalInput(
        signal_ref=route_ref,
        signal_type=signal_type,
        object_ref=target.knowledge_object.object_id,
        title=target.knowledge_object.title,
        object_type=target.knowledge_object.object_type,
        audience_filter=_audience_filter(feedback.audience_context),
        affected_surfaces=("feedback", "review_queue"),
        summary=summary,
        reason=reason,
        evidence_excerpt=f"feedback_ref={feedback_ref}; route_ref={route_ref}",
        freshness=freshness,
        page_id=target.page.id,
        trigger_signals=(feedback_type.value, feedback_ref, route_ref),
        evidence_source_type=EvidenceSourceType.CONSUMPTION_FEEDBACK,
        observed_at=(
            observed_at
            if isinstance(observed_at, datetime) and observed_at.tzinfo is not None
            else None
        ),
    )


def _audience_filter(payload: object) -> AudienceFilter:
    audience = normalize_audience_context(payload)

    def dimension(value: str | None) -> tuple[str, ...]:
        return (value,) if value is not None else ()

    return AudienceFilter(
        visibility=Visibility(audience["visibility"]),
        brands=dimension(audience["brand"]),
        product_lines=dimension(audience["product_line"]),
        plans=dimension(audience["plan_tier"]),
        regions=dimension(audience["region"]),
        languages=dimension(audience["language"]),
        product_versions=dimension(audience["product_version"]),
    )


def _require_active_lease(
    route: GovernanceFeedbackRoute,
    claim: FeedbackRouteClaim,
    *,
    now: datetime,
) -> None:
    if _route_state(route) is not FeedbackRouteState.RUNNING:
        raise FeedbackRouteLeaseLost(
            f"feedback route {claim.route_id} is not running under this claim"
        )
    if route.lease_token != claim.lease_token:
        raise FeedbackRouteLeaseLost(
            f"feedback route {claim.route_id} is owned by a different claim"
        )
    lease_expires_at = route.lease_expires_at
    if lease_expires_at is None or lease_expires_at <= now:
        raise FeedbackRouteLeaseLost(
            f"feedback route {claim.route_id} lease has expired"
        )


def _mark_completed(
    route: GovernanceFeedbackRoute,
    outcome_signal: GovernanceSignal,
    *,
    now: datetime,
) -> None:
    route.lifecycle_state = FeedbackRouteState.COMPLETED.value
    route.next_attempt_at = None
    route.lease_token = None
    route.lease_expires_at = None
    route.outcome_signal_id = outcome_signal.id
    route.terminal_reason = None
    route.last_error = None
    route.completed_at = now


def _mark_blocked(
    route: GovernanceFeedbackRoute,
    *,
    reason: str,
    now: datetime,
) -> None:
    route.lifecycle_state = FeedbackRouteState.BLOCKED.value
    route.next_attempt_at = None
    route.lease_token = None
    route.lease_expires_at = None
    route.outcome_signal_id = None
    route.terminal_reason = reason
    route.last_error = None
    route.completed_at = now


def _mark_failed(
    route: GovernanceFeedbackRoute,
    *,
    error: str,
    now: datetime,
) -> None:
    route.lifecycle_state = FeedbackRouteState.FAILED.value
    route.next_attempt_at = None
    route.lease_token = None
    route.lease_expires_at = None
    route.outcome_signal_id = None
    route.terminal_reason = _RETRY_EXHAUSTED
    route.last_error = error
    route.completed_at = now


def _requeue_after_failure(
    route: GovernanceFeedbackRoute,
    *,
    error: str,
    now: datetime,
) -> None:
    delay = FEEDBACK_ROUTE_RETRY_BASE_SECONDS
    for _ in range(route.attempt_count - 1):
        delay *= 2
    route.lifecycle_state = FeedbackRouteState.QUEUED.value
    route.next_attempt_at = now + timedelta(seconds=delay)
    route.lease_token = None
    route.lease_expires_at = None
    route.outcome_signal_id = None
    route.terminal_reason = None
    route.last_error = error
    route.completed_at = None


def _failure_text(error: object) -> str:
    return (str(error).strip() or type(error).__name__)[:1000]


async def _block_feedback_route(
    session: AsyncSession,
    *,
    route: GovernanceFeedbackRoute,
    feedback: GovernanceFeedbackSignal,
    actor: Employee,
    reason: str,
    now: datetime,
) -> GovernanceFeedbackRoute:
    _mark_blocked(route, reason=reason, now=now)
    await _append_terminal_audit(
        session,
        route=route,
        feedback=feedback,
        actor=actor,
        outcome="blocked",
        terminal_reason=reason,
    )
    await session.flush()
    return route


async def _append_terminal_audit(
    session: AsyncSession,
    *,
    route: GovernanceFeedbackRoute,
    feedback: GovernanceFeedbackSignal,
    actor: Employee,
    outcome: str,
    terminal_reason: str | None = None,
    outcome_signal: GovernanceSignal | None = None,
) -> None:
    """Append the one nonsensitive audit row for an initial terminal outcome."""

    reason_parts = (
        f"route_ref={_route_ref(route.id)}",
        f"feedback_ref={feedback_signal_ref(feedback)}",
        f"outcome={outcome}",
        (
            f"outcome_signal_ref={_outcome_signal_ref(outcome_signal.id)}"
            if outcome_signal is not None
            else None
        ),
        f"terminal_reason={terminal_reason}" if terminal_reason is not None else None,
    )
    await log_audit(
        session,
        actor,
        "execute_feedback_route",
        "governance_feedback_route",
        str(route.id),
        reason="; ".join(part for part in reason_parts if part is not None),
    )


__all__ = [
    "FeedbackRouteClaim",
    "FeedbackRouteLeaseLost",
    "claim_feedback_routes",
    "execute_feedback_route",
    "record_feedback_route_failure",
]
