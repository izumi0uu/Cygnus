from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.evidence import EvidenceSourceType, FreshnessState
from cygnus.governance.feedback_execution import (
    FeedbackRouteClaim,
    FeedbackRouteLeaseLost,
    claim_feedback_routes,
    execute_feedback_route,
    record_feedback_route_failure,
)
from cygnus.governance.feedback_routing import project_feedback_route
from cygnus.review import PressureSignalType
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceFeedbackRoute,
    GovernanceFeedbackSignal,
    GovernanceSignal,
    WikiPage,
    WikiPageDraft,
)


_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
_OBSERVED_AT = datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, values: object | tuple[object, ...] | list[object] | None):
        if values is None:
            self._values: list[object] = []
        elif isinstance(values, tuple | list):
            self._values = list(values)
        else:
            self._values = [values]

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return list(self._values)

    def scalar_one_or_none(self) -> object | None:
        if len(self._values) > 1:
            raise AssertionError("scalar_one_or_none received multiple rows")
        return self._values[0] if self._values else None


def _entity(statement: object) -> object | None:
    descriptions = getattr(statement, "column_descriptions", ())
    if not descriptions:
        return None
    return descriptions[0].get("entity")


def _route(
    *,
    route_id: uuid.UUID | None = None,
    feedback_signal_id: uuid.UUID | None = None,
    route_kind: str = "review",
    lifecycle_state: str = "queued",
    attempt_count: int = 0,
    next_attempt_at: datetime | None = None,
    lease_token: str | None = None,
    lease_expires_at: datetime | None = None,
) -> Any:
    return SimpleNamespace(
        id=route_id or uuid.uuid4(),
        feedback_signal_id=feedback_signal_id or uuid.uuid4(),
        route_kind=route_kind,
        lifecycle_state=lifecycle_state,
        attempt_count=attempt_count,
        next_attempt_at=next_attempt_at,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        outcome_signal_id=None,
        terminal_reason=None,
        last_error=None,
        completed_at=None,
        created_at=_NOW - timedelta(minutes=5),
    )


def _feedback(
    *,
    feedback_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    signal_type: str = "low_rating",
    object_id: str | None = "ko-billing-answer",
    page_id: uuid.UUID | None = None,
    draft_id: uuid.UUID | None = None,
    source_context_ref: str | None = "private://session-context",
) -> Any:
    return SimpleNamespace(
        id=feedback_id or uuid.uuid4(),
        actor_id=actor_id or uuid.uuid4(),
        signal_type=signal_type,
        audience_context={
            "visibility": "internal",
            "brand": None,
            "product_line": "billing",
            "plan_tier": None,
            "region": None,
            "language": None,
            "product_version": None,
        },
        object_id=object_id,
        page_id=page_id,
        draft_id=draft_id,
        notes="Customer feedback requires governed review.",
        source_context_ref=source_context_ref,
        created_at=_OBSERVED_AT,
    )


def _page(
    *,
    page_id: uuid.UUID | None = None,
    slug: str = "billing-answer",
    knowledge_type_slugs: list[str] | None = None,
    orphaned: bool = False,
) -> Any:
    return SimpleNamespace(
        id=page_id or uuid.uuid4(),
        slug=slug,
        title="Billing answer",
        summary="Governed billing support guidance.",
        content_md="# Billing answer\n\nUse the governed support workflow.",
        status="mature",
        knowledge_type_slugs=(
            ["answer_card"] if knowledge_type_slugs is None else knowledge_type_slugs
        ),
        orphaned=orphaned,
    )


def _draft(
    *,
    draft_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
    draft_kind: str = "create",
) -> Any:
    return SimpleNamespace(
        id=draft_id or uuid.uuid4(),
        page_id=page_id,
        draft_kind=draft_kind,
        suggested_metadata={"slug": "unmaterialized-answer"},
    )


class _RouteSession:
    """Small stateful session double for route lifecycle contracts."""

    def __init__(
        self,
        *,
        routes: tuple[object, ...],
        feedback_signals: tuple[object, ...] = (),
        pages: tuple[object, ...] = (),
        drafts: tuple[object, ...] = (),
        actor: object | None = None,
        now: datetime = _NOW,
        flush_error_at: int | None = None,
    ) -> None:
        self.routes = {getattr(route, "id"): route for route in routes}
        self.feedback_signals = {
            getattr(signal, "id"): signal for signal in feedback_signals
        }
        self.pages = {getattr(page, "id"): page for page in pages}
        self.drafts = {getattr(draft, "id"): draft for draft in drafts}
        self.actor = actor or SimpleNamespace(id=uuid.uuid4())
        self.now = now
        self.added: list[object] = []
        self.downstream_signals: list[object] = []
        self.assignments: list[object] = []
        self._flush_error_at = flush_error_at
        self._flush_calls = 0
        self._route_snapshots = {
            route_id: dict(vars(route)) for route_id, route in self.routes.items()
        }
        self.execute = AsyncMock(side_effect=self._execute)
        self.get = AsyncMock(side_effect=self._get)
        self.flush = AsyncMock(side_effect=self._flush)
        self.commit = AsyncMock()
        self.rollback = AsyncMock(side_effect=self._rollback)

    async def _execute(self, statement: object) -> _Rows:
        entity = _entity(statement)
        if entity is GovernanceFeedbackRoute:
            rendered = str(getattr(statement, "whereclause", ""))
            if "next_attempt_at" in rendered or "lease_expires_at" in rendered:
                return _Rows(
                    tuple(
                        route
                        for route in self.routes.values()
                        if _is_due(route, now=self.now)
                    )
                )
            return _Rows(tuple(self.routes.values()))
        if entity is GovernanceFeedbackSignal:
            return _Rows(tuple(self.feedback_signals.values()))
        if entity is WikiPage:
            return _Rows(tuple(self.pages.values()))
        if entity is WikiPageDraft:
            return _Rows(tuple(self.drafts.values()))
        if entity is Employee:
            return _Rows(self.actor)
        if entity is GovernanceSignal:
            return _Rows(tuple(self.downstream_signals))
        return _Rows(None)

    async def _get(
        self, model: object, identifier: object, **_kwargs: object
    ) -> object | None:
        if model is GovernanceFeedbackRoute:
            return self.routes.get(identifier)
        if model is GovernanceFeedbackSignal:
            return self.feedback_signals.get(identifier)
        if model is WikiPage:
            return self.pages.get(identifier)
        if model is WikiPageDraft:
            return self.drafts.get(identifier)
        if model is Employee:
            return self.actor if getattr(self.actor, "id", None) == identifier else None
        if model is GovernanceSignal:
            return next(
                (
                    signal
                    for signal in self.downstream_signals
                    if getattr(signal, "id", None) == identifier
                ),
                None,
            )
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def _flush(self) -> None:
        self._flush_calls += 1
        if self._flush_error_at == self._flush_calls:
            raise RuntimeError("simulated transaction flush failure")

    async def _rollback(self) -> None:
        for route_id, snapshot in self._route_snapshots.items():
            route = self.routes[route_id]
            vars(route).clear()
            vars(route).update(snapshot)
        self.added.clear()
        self.downstream_signals.clear()
        self.assignments.clear()


def _is_due(route: object, *, now: datetime) -> bool:
    state = getattr(route, "lifecycle_state")
    if state == "queued":
        next_attempt_at = getattr(route, "next_attempt_at")
        return next_attempt_at is None or next_attempt_at <= now
    if state == "running":
        lease_expires_at = getattr(route, "lease_expires_at")
        return lease_expires_at is None or lease_expires_at <= now
    return False


def _audit_rows(session: _RouteSession) -> list[AuditLog]:
    return [item for item in session.added if isinstance(item, AuditLog)]


def _claim(route: object) -> FeedbackRouteClaim:
    return FeedbackRouteClaim(
        route_id=getattr(route, "id"),
        lease_token=getattr(route, "lease_token"),
        attempt_count=getattr(route, "attempt_count"),
    )


def _materializer(session: _RouteSession) -> AsyncMock:
    async def create(
        _db: AsyncSession,
        signal_input: object,
        *,
        created_by_id: uuid.UUID,
    ) -> object:
        existing = next(
            (
                signal
                for signal in session.downstream_signals
                if getattr(signal, "signal_ref", None)
                == getattr(signal_input, "signal_ref", None)
            ),
            None,
        )
        if existing is not None:
            return existing
        signal = SimpleNamespace(
            id=uuid.uuid4(),
            signal_ref=getattr(signal_input, "signal_ref"),
            signal_type=getattr(getattr(signal_input, "signal_type"), "value", None),
            freshness=getattr(getattr(signal_input, "freshness"), "value", None),
            page_id=getattr(signal_input, "page_id"),
            object_ref=getattr(signal_input, "object_ref"),
            created_by_id=created_by_id,
        )
        session.downstream_signals.append(signal)
        session.assignments.append(SimpleNamespace(signal_id=signal.id))
        return signal

    return AsyncMock(side_effect=create)


class FeedbackRouteClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_claims_a_due_queued_route_with_a_fencing_lease(self) -> None:
        feedback = _feedback()
        route = _route(feedback_signal_id=feedback.id)
        session = _RouteSession(routes=(route,), feedback_signals=(feedback,))

        claims = await claim_feedback_routes(
            cast(AsyncSession, cast(object, session)), now=_NOW
        )

        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim.route_id, route.id)
        self.assertEqual(claim.attempt_count, 1)
        self.assertEqual(route.lifecycle_state, "running")
        self.assertEqual(route.attempt_count, 1)
        self.assertEqual(route.lease_token, claim.lease_token)
        self.assertTrue(route.lease_token)
        self.assertEqual(route.lease_expires_at, _NOW + timedelta(seconds=60))
        self.assertIsNone(route.next_attempt_at)
        self.assertIsNone(route.terminal_reason)
        self.assertIsNone(route.completed_at)
        self.assertGreaterEqual(session.flush.await_count, 1)
        session.commit.assert_not_awaited()

    async def test_delayed_queued_route_is_not_claimed(self) -> None:
        feedback = _feedback()
        route = _route(
            feedback_signal_id=feedback.id,
            next_attempt_at=_NOW + timedelta(seconds=1),
        )
        session = _RouteSession(routes=(route,), feedback_signals=(feedback,))

        claims = await claim_feedback_routes(
            cast(AsyncSession, cast(object, session)), now=_NOW
        )

        self.assertEqual(claims, ())
        self.assertEqual(route.lifecycle_state, "queued")
        self.assertEqual(route.attempt_count, 0)
        self.assertEqual(route.next_attempt_at, _NOW + timedelta(seconds=1))
        self.assertIsNone(route.lease_token)
        session.flush.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_expired_running_lease_is_recovered_with_a_new_token(self) -> None:
        feedback = _feedback()
        route = _route(
            feedback_signal_id=feedback.id,
            lifecycle_state="running",
            attempt_count=1,
            lease_token="expired-worker-token",
            lease_expires_at=_NOW - timedelta(seconds=1),
        )
        session = _RouteSession(routes=(route,), feedback_signals=(feedback,))

        claims = await claim_feedback_routes(
            cast(AsyncSession, cast(object, session)), now=_NOW
        )

        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim.route_id, route.id)
        self.assertEqual(claim.attempt_count, 2)
        self.assertNotEqual(claim.lease_token, "expired-worker-token")
        self.assertEqual(route.lifecycle_state, "running")
        self.assertEqual(route.attempt_count, 2)
        self.assertEqual(route.lease_token, claim.lease_token)
        self.assertEqual(route.lease_expires_at, _NOW + timedelta(seconds=60))
        session.commit.assert_not_awaited()

    async def test_expired_max_attempt_lease_terminally_fails_once(self) -> None:
        actor_id = uuid.uuid4()
        feedback = _feedback(actor_id=actor_id)
        route = _route(
            feedback_signal_id=feedback.id,
            lifecycle_state="running",
            attempt_count=3,
            lease_token="expired-worker-token",
            lease_expires_at=_NOW - timedelta(seconds=1),
        )
        session = _RouteSession(
            routes=(route,),
            feedback_signals=(feedback,),
            actor=SimpleNamespace(id=actor_id),
        )

        claims = await claim_feedback_routes(
            cast(AsyncSession, cast(object, session)), now=_NOW
        )

        self.assertEqual(claims, ())
        self.assertEqual(route.lifecycle_state, "failed")
        self.assertEqual(route.terminal_reason, "retry_exhausted")
        self.assertTrue(route.last_error)
        self.assertEqual(route.completed_at, _NOW)
        self.assertIsNone(route.next_attempt_at)
        self.assertIsNone(route.lease_token)
        self.assertIsNone(route.lease_expires_at)
        self.assertIsNone(route.outcome_signal_id)
        audits = _audit_rows(session)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].principal_id, actor_id)
        session.commit.assert_not_awaited()


class FeedbackRouteExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_rating_materializes_scoped_ticket_pressure_truth(self) -> None:
        actor_id = uuid.uuid4()
        page = _page()
        feedback = _feedback(actor_id=actor_id, page_id=page.id)
        route = _route(
            feedback_signal_id=feedback.id,
            lifecycle_state="running",
            attempt_count=1,
            lease_token="current-worker-token",
            lease_expires_at=_NOW + timedelta(seconds=60),
        )
        session = _RouteSession(
            routes=(route,),
            feedback_signals=(feedback,),
            pages=(page,),
            actor=SimpleNamespace(id=actor_id),
        )
        materialize = _materializer(session)

        with patch(
            "cygnus.governance.feedback_execution.create_governance_signal",
            new=materialize,
        ):
            completed = await execute_feedback_route(
                cast(AsyncSession, cast(object, session)), _claim(route), now=_NOW
            )

        self.assertIs(completed, route)
        self.assertEqual(route.lifecycle_state, "completed")
        self.assertEqual(route.completed_at, _NOW)
        self.assertIsNotNone(route.outcome_signal_id)
        self.assertIsNone(route.terminal_reason)
        self.assertIsNone(route.last_error)
        self.assertIsNone(route.lease_token)
        self.assertIsNone(route.lease_expires_at)
        self.assertEqual(len(session.downstream_signals), 1)
        input_ = materialize.await_args.args[1]
        self.assertEqual(input_.signal_ref, f"feedback-route:{route.id}")
        self.assertIs(input_.signal_type, PressureSignalType.LOW_RATING)
        self.assertIs(
            input_.evidence_source_type, EvidenceSourceType.CONSUMPTION_FEEDBACK
        )
        self.assertIs(input_.freshness, FreshnessState.UNKNOWN)
        self.assertEqual(input_.page_id, page.id)
        self.assertEqual(input_.object_ref, "ko-billing-answer")
        self.assertEqual(input_.affected_surfaces, ("feedback", "review_queue"))
        self.assertEqual(
            input_.audience_filter.product_lines,
            ("billing",),
        )
        self.assertEqual(
            input_.trigger_signals,
            (
                "low_rating",
                f"feedback-signal:{feedback.id}",
                f"feedback-route:{route.id}",
            ),
        )
        self.assertEqual(
            input_.evidence_excerpt,
            f"feedback_ref=feedback-signal:{feedback.id}; "
            f"route_ref=feedback-route:{route.id}",
        )
        self.assertEqual(input_.observed_at, _OBSERVED_AT)
        self.assertEqual(materialize.await_args.kwargs["created_by_id"], actor_id)
        self.assertEqual(len(_audit_rows(session)), 1)
        self.assertNotIn(
            feedback.source_context_ref, _audit_rows(session)[0].reason or ""
        )
        session.commit.assert_not_awaited()

    async def test_stale_answer_materializes_stale_drift_truth(self) -> None:
        actor_id = uuid.uuid4()
        page = _page(slug="billing-stale-answer")
        feedback = _feedback(
            actor_id=actor_id,
            signal_type="stale_answer",
            object_id="ko-billing-stale-answer",
            page_id=page.id,
        )
        route = _route(
            feedback_signal_id=feedback.id,
            route_kind="refresh",
            lifecycle_state="running",
            attempt_count=1,
            lease_token="current-worker-token",
            lease_expires_at=_NOW + timedelta(seconds=60),
        )
        session = _RouteSession(
            routes=(route,),
            feedback_signals=(feedback,),
            pages=(page,),
            actor=SimpleNamespace(id=actor_id),
        )
        materialize = _materializer(session)

        with patch(
            "cygnus.governance.feedback_execution.create_governance_signal",
            new=materialize,
        ):
            await execute_feedback_route(
                cast(AsyncSession, cast(object, session)), _claim(route), now=_NOW
            )

        input_ = materialize.await_args.args[1]
        self.assertEqual(input_.signal_ref, f"feedback-route:{route.id}")
        self.assertIs(input_.signal_type, PressureSignalType.STALE_ANSWER)
        self.assertIs(
            input_.evidence_source_type, EvidenceSourceType.CONSUMPTION_FEEDBACK
        )
        self.assertIs(input_.freshness, FreshnessState.STALE)
        self.assertEqual(input_.affected_surfaces, ("feedback", "review_queue"))
        self.assertEqual(route.lifecycle_state, "completed")
        self.assertEqual(len(_audit_rows(session)), 1)
        session.commit.assert_not_awaited()

    async def test_completed_route_replays_current_truth_without_duplicate_downstream_rows(
        self,
    ) -> None:
        actor_id = uuid.uuid4()
        page = _page()
        feedback = _feedback(actor_id=actor_id, page_id=page.id)
        route = _route(
            feedback_signal_id=feedback.id,
            lifecycle_state="running",
            attempt_count=1,
            lease_token="current-worker-token",
            lease_expires_at=_NOW + timedelta(seconds=60),
        )
        session = _RouteSession(
            routes=(route,),
            feedback_signals=(feedback,),
            pages=(page,),
            actor=SimpleNamespace(id=actor_id),
        )
        materialize = _materializer(session)

        with patch(
            "cygnus.governance.feedback_execution.create_governance_signal",
            new=materialize,
        ):
            await execute_feedback_route(
                cast(AsyncSession, cast(object, session)), _claim(route), now=_NOW
            )
            replay = await execute_feedback_route(
                cast(AsyncSession, cast(object, session)),
                FeedbackRouteClaim(
                    route_id=route.id,
                    lease_token="stale-worker-token",
                    attempt_count=1,
                ),
                now=_NOW,
            )

        self.assertIs(replay, route)
        self.assertEqual(len(session.routes), 1)
        self.assertEqual(len(session.downstream_signals), 1)
        self.assertEqual(len(session.assignments), 1)
        materialize.assert_awaited_once()
        self.assertEqual(len(_audit_rows(session)), 1)
        projection = project_feedback_route(route).to_dict()
        self.assertEqual(projection["route_id"], str(route.id))
        self.assertEqual(projection["route_state"], "completed")
        self.assertEqual(projection["routing_state"], "review_completed")
        self.assertFalse(projection["review_queued"])
        self.assertFalse(projection["refresh_queued"])
        self.assertEqual(projection["outcome_signal_id"], str(route.outcome_signal_id))
        self.assertEqual(
            projection["outcome_signal_ref"],
            f"governance-signal:{route.outcome_signal_id}",
        )
        session.commit.assert_not_awaited()

    async def test_invalid_targets_block_without_guessed_downstream_truth(self) -> None:
        cases = (
            (
                "generic",
                _feedback(object_id=None, page_id=None, draft_id=None),
                (),
                (),
                "target_required",
            ),
            (
                "draft_only",
                _feedback(object_id=None, page_id=None, draft_id=uuid.uuid4()),
                (),
                (),
                "target_not_materialized",
            ),
            (
                "ineligible",
                None,
                (_page(knowledge_type_slugs=[]),),
                (),
                "target_ineligible",
            ),
            (
                "identity_drift",
                None,
                (_page(),),
                (),
                "target_identity_changed",
            ),
        )
        for name, feedback, pages, drafts, expected_reason in cases:
            with self.subTest(outcome=name):
                actor_id = uuid.uuid4()
                if feedback is None:
                    page = pages[0]
                    feedback = _feedback(
                        actor_id=actor_id,
                        page_id=page.id,
                        object_id=(
                            "ko-other-answer"
                            if name == "identity_drift"
                            else f"ko-{page.slug}"
                        ),
                    )
                else:
                    feedback.actor_id = actor_id
                    if name == "draft_only":
                        draft = _draft(draft_id=feedback.draft_id)
                        drafts = (draft,)
                route = _route(
                    feedback_signal_id=feedback.id,
                    lifecycle_state="running",
                    attempt_count=1,
                    lease_token="current-worker-token",
                    lease_expires_at=_NOW + timedelta(seconds=60),
                )
                session = _RouteSession(
                    routes=(route,),
                    feedback_signals=(feedback,),
                    pages=pages,
                    drafts=drafts,
                    actor=SimpleNamespace(id=actor_id),
                )
                materialize = _materializer(session)

                with patch(
                    "cygnus.governance.feedback_execution.create_governance_signal",
                    new=materialize,
                ):
                    blocked = await execute_feedback_route(
                        cast(AsyncSession, cast(object, session)),
                        _claim(route),
                        now=_NOW,
                    )

                self.assertIs(blocked, route)
                self.assertEqual(route.lifecycle_state, "blocked")
                self.assertEqual(route.terminal_reason, expected_reason)
                self.assertEqual(route.completed_at, _NOW)
                self.assertIsNone(route.outcome_signal_id)
                self.assertIsNone(route.lease_token)
                self.assertIsNone(route.lease_expires_at)
                self.assertEqual(session.downstream_signals, [])
                self.assertEqual(session.assignments, [])
                materialize.assert_not_awaited()
                audits = _audit_rows(session)
                self.assertEqual(len(audits), 1)
                self.assertEqual(audits[0].principal_id, actor_id)
                self.assertNotIn(feedback.source_context_ref, audits[0].reason or "")
                session.commit.assert_not_awaited()

    async def test_stale_workers_cannot_mutate_after_token_or_lease_loss(self) -> None:
        for case, lease_token, lease_expires_at, claim_token in (
            (
                "newer_claim",
                "newer-worker-token",
                _NOW + timedelta(seconds=60),
                "old-worker-token",
            ),
            (
                "expired_lease",
                "same-worker-token",
                _NOW - timedelta(seconds=1),
                "same-worker-token",
            ),
        ):
            with self.subTest(case=case):
                feedback = _feedback()
                route = _route(
                    feedback_signal_id=feedback.id,
                    lifecycle_state="running",
                    attempt_count=1,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                )
                session = _RouteSession(routes=(route,), feedback_signals=(feedback,))
                claim = FeedbackRouteClaim(
                    route_id=route.id,
                    lease_token=claim_token,
                    attempt_count=1,
                )
                before = dict(vars(route))

                with self.assertRaises(FeedbackRouteLeaseLost):
                    await execute_feedback_route(
                        cast(AsyncSession, cast(object, session)), claim, now=_NOW
                    )
                with self.assertRaises(FeedbackRouteLeaseLost):
                    await record_feedback_route_failure(
                        cast(AsyncSession, cast(object, session)),
                        claim,
                        error=RuntimeError("worker lost its lease"),
                        now=_NOW,
                    )

                self.assertEqual(dict(vars(route)), before)
                self.assertEqual(_audit_rows(session), [])
                session.flush.assert_not_awaited()
                session.commit.assert_not_awaited()

    async def test_retryable_failures_back_off_without_a_terminal_audit(self) -> None:
        for attempt_count, expected_delay in ((1, 30), (2, 60)):
            with self.subTest(attempt_count=attempt_count):
                feedback = _feedback()
                route = _route(
                    feedback_signal_id=feedback.id,
                    lifecycle_state="running",
                    attempt_count=attempt_count,
                    lease_token=f"worker-{attempt_count}",
                    lease_expires_at=_NOW + timedelta(seconds=60),
                )
                session = _RouteSession(routes=(route,), feedback_signals=(feedback,))

                retried = await record_feedback_route_failure(
                    cast(AsyncSession, cast(object, session)),
                    _claim(route),
                    error=RuntimeError("temporary downstream outage"),
                    now=_NOW,
                )

                self.assertIs(retried, route)
                self.assertEqual(route.lifecycle_state, "queued")
                self.assertEqual(route.attempt_count, attempt_count)
                self.assertEqual(
                    route.next_attempt_at,
                    _NOW + timedelta(seconds=expected_delay),
                )
                self.assertEqual(route.last_error, "temporary downstream outage")
                self.assertIsNone(route.lease_token)
                self.assertIsNone(route.lease_expires_at)
                self.assertIsNone(route.outcome_signal_id)
                self.assertIsNone(route.terminal_reason)
                self.assertIsNone(route.completed_at)
                self.assertEqual(_audit_rows(session), [])
                session.commit.assert_not_awaited()

    async def test_failure_at_the_attempt_budget_is_terminal_and_audited(self) -> None:
        actor_id = uuid.uuid4()
        feedback = _feedback(actor_id=actor_id)
        route = _route(
            feedback_signal_id=feedback.id,
            lifecycle_state="running",
            attempt_count=3,
            lease_token="last-worker-token",
            lease_expires_at=_NOW + timedelta(seconds=60),
        )
        session = _RouteSession(
            routes=(route,),
            feedback_signals=(feedback,),
            actor=SimpleNamespace(id=actor_id),
        )

        failed = await record_feedback_route_failure(
            cast(AsyncSession, cast(object, session)),
            _claim(route),
            error=RuntimeError("permanent downstream outage"),
            now=_NOW,
        )

        self.assertIs(failed, route)
        self.assertEqual(route.lifecycle_state, "failed")
        self.assertEqual(route.terminal_reason, "retry_exhausted")
        self.assertEqual(route.last_error, "permanent downstream outage")
        self.assertEqual(route.completed_at, _NOW)
        self.assertIsNone(route.next_attempt_at)
        self.assertIsNone(route.lease_token)
        self.assertIsNone(route.lease_expires_at)
        self.assertIsNone(route.outcome_signal_id)
        audits = _audit_rows(session)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].principal_id, actor_id)
        session.commit.assert_not_awaited()

    async def test_caller_rollback_removes_an_unflushed_execution_outcome(self) -> None:
        actor_id = uuid.uuid4()
        page = _page()
        feedback = _feedback(actor_id=actor_id, page_id=page.id)
        route = _route(
            feedback_signal_id=feedback.id,
            lifecycle_state="running",
            attempt_count=1,
            lease_token="current-worker-token",
            lease_expires_at=_NOW + timedelta(seconds=60),
        )
        session = _RouteSession(
            routes=(route,),
            feedback_signals=(feedback,),
            pages=(page,),
            actor=SimpleNamespace(id=actor_id),
            flush_error_at=1,
        )
        materialize = _materializer(session)

        with patch(
            "cygnus.governance.feedback_execution.create_governance_signal",
            new=materialize,
        ):
            with self.assertRaisesRegex(RuntimeError, "transaction flush failure"):
                await execute_feedback_route(
                    cast(AsyncSession, cast(object, session)), _claim(route), now=_NOW
                )

        session.commit.assert_not_awaited()
        await session.rollback()
        self.assertEqual(route.lifecycle_state, "running")
        self.assertEqual(route.lease_token, "current-worker-token")
        self.assertEqual(route.outcome_signal_id, None)
        self.assertIsNone(route.completed_at)
        self.assertEqual(session.downstream_signals, [])
        self.assertEqual(session.assignments, [])
        self.assertEqual(_audit_rows(session), [])


if __name__ == "__main__":
    unittest.main()
