from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from typing import cast
import unittest
import uuid

from sqlalchemy import delete, null, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from cygnus.domain import governed_object_ref
from cygnus.runtime.services import wiki_service

from cygnus.governance.feedback_execution import claim_feedback_routes
from cygnus.governance.feedback_operations import (
    FeedbackRouteOperationsQuery,
    get_feedback_route_operation,
    list_feedback_route_operations,
)
from cygnus.governance.feedback_routing import FeedbackRouteKind, FeedbackRouteState
from cygnus.runtime.database.models import (
    AuditLog,
    Department,
    Employee,
    EmployeeDepartment,
    GovernanceFeedbackRoute,
    GovernanceFeedbackSignal,
    GovernanceReviewAssignment,
    GovernanceReviewAssignmentEvent,
    GovernanceSignal,
    WikiPage,
)


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")


def _page(
    *,
    page_id: uuid.UUID,
    slug: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    now: datetime,
) -> WikiPage:
    return WikiPage(
        id=page_id,
        slug=slug,
        title=f"CYG-120 {slug}",
        status="mature",
        content_md=f"# CYG-120 {slug}\n\nGoverned support guidance.",
        summary="Governed support guidance.",
        scope_type=scope_type,
        scope_id=scope_id,
        language="en",
        normalized_path=wiki_service.normalize_page_path(slug),
        knowledge_type_slugs=["answer_card"],
        source_ids=[],
        version=1,
        orphaned=False,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )


def _feedback(
    *,
    feedback_id: uuid.UUID,
    actor_id: uuid.UUID,
    command_id: str,
    page_id: uuid.UUID,
    signal_type: str,
    now: datetime,
) -> GovernanceFeedbackSignal:
    return GovernanceFeedbackSignal(
        id=feedback_id,
        command_id=command_id,
        request_fingerprint=uuid.uuid4().hex * 2,
        signal_type=signal_type,
        actor_id=actor_id,
        audience_context={
            "visibility": "internal",
            "brand": None,
            "product_line": None,
            "plan_tier": None,
            "region": None,
            "language": None,
            "product_version": None,
        },
        object_id=governed_object_ref(page_id),
        page_id=page_id,
        draft_id=None,
        source_context_ref="private://must-not-leak",
        notes="customer content must not leak",
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=3),
    )


def _route(
    *,
    route_id: uuid.UUID,
    feedback_signal_id: uuid.UUID,
    route_kind: FeedbackRouteKind,
    state: FeedbackRouteState,
    attempt_count: int,
    created_at: datetime,
    updated_at: datetime,
    next_attempt_at: datetime | None = None,
    lease_expires_at: datetime | None = None,
    outcome_signal_id: uuid.UUID | None = None,
    terminal_reason: str | None = None,
    last_error: str | None = None,
    completed_at: datetime | None = None,
) -> GovernanceFeedbackRoute:
    return GovernanceFeedbackRoute(
        id=route_id,
        feedback_signal_id=feedback_signal_id,
        route_kind=route_kind.value,
        lifecycle_state=state.value,
        attempt_count=attempt_count,
        next_attempt_at=(
            next_attempt_at
            if state is FeedbackRouteState.QUEUED
            else cast(datetime | None, null())
        ),
        lease_token=(uuid.uuid4().hex if state is FeedbackRouteState.RUNNING else None),
        lease_expires_at=lease_expires_at,
        outcome_signal_id=outcome_signal_id,
        terminal_reason=terminal_reason,
        last_error=last_error,
        completed_at=completed_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _outcome(
    *,
    signal_id: uuid.UUID,
    route_id: uuid.UUID,
    actor_id: uuid.UUID,
    page_id: uuid.UUID,
    now: datetime,
) -> GovernanceSignal:
    return GovernanceSignal(
        id=signal_id,
        signal_ref=f"feedback-route:{route_id}",
        signal_type="low_rating",
        object_ref=governed_object_ref(page_id),
        title="CYG-120 completed route review pressure",
        object_type="answer_card",
        page_id=page_id,
        source_id=None,
        audience_binding_ref=None,
        audience_filter={
            "visibility": "internal",
            "brands": [],
            "product_lines": [],
            "plans": [],
            "regions": [],
            "languages": [],
            "product_versions": [],
        },
        affected_surfaces=["feedback", "review_queue"],
        trigger_signals=["low_rating"],
        evidence_source_type="consumption_feedback",
        freshness="unknown",
        summary="Consumption feedback requires governed review.",
        reason="Review is required before any knowledge change.",
        evidence_excerpt="feedback and route refs only",
        status="active",
        observed_at=now - timedelta(minutes=12),
        resolved_at=None,
        created_by_id=actor_id,
        created_at=now - timedelta(minutes=11),
        updated_at=now - timedelta(minutes=11),
        version=1,
    )


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class FeedbackRouteOperationsPostgresTests(unittest.TestCase):
    def test_mixed_scoped_operations_survive_recovery_and_restart(self) -> None:
        asyncio.run(self._exercise_mixed_scoped_operations())

    async def _exercise_mixed_scoped_operations(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        now = datetime.now(timezone.utc).replace(microsecond=0)
        admin_id = uuid.uuid4()
        scoped_user_id = uuid.uuid4()
        visible_department_id = uuid.uuid4()
        hidden_department_id = uuid.uuid4()
        page_ids = {
            "global": uuid.uuid4(),
            "visible": uuid.uuid4(),
            "hidden": uuid.uuid4(),
        }
        route_ids = {
            "due": uuid.uuid4(),
            "future": uuid.uuid4(),
            "running": uuid.uuid4(),
            "completed": uuid.uuid4(),
            "blocked": uuid.uuid4(),
            "failed": uuid.uuid4(),
            "hidden": uuid.uuid4(),
        }
        outcome_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        command_ids = {name: f"cyg120-{name}-{unique}" for name in route_ids}

        try:
            async with sessions() as session:
                visible_department = Department(
                    id=visible_department_id,
                    name=f"CYG-120 visible {unique}",
                )
                hidden_department = Department(
                    id=hidden_department_id,
                    name=f"CYG-120 hidden {unique}",
                )
                admin = Employee(
                    id=admin_id,
                    name="CYG-120 feedback actor",
                    email=f"cyg120-actor-{unique}@example.test",
                    role="admin",
                    global_role="admin",
                    is_active=True,
                )
                scoped_user = Employee(
                    id=scoped_user_id,
                    name="CYG-120 scoped operator",
                    email=f"cyg120-operator-{unique}@example.test",
                    role="employee",
                    global_role="viewer",
                    is_active=True,
                )
                membership = EmployeeDepartment(
                    employee_id=scoped_user_id,
                    department_id=visible_department_id,
                )
                pages = {
                    "global": _page(
                        page_id=page_ids["global"],
                        slug=f"cyg120-global-{unique}",
                        scope_type="global",
                        scope_id=None,
                        now=now,
                    ),
                    "visible": _page(
                        page_id=page_ids["visible"],
                        slug=f"cyg120-visible-{unique}",
                        scope_type="department",
                        scope_id=visible_department_id,
                        now=now,
                    ),
                    "hidden": _page(
                        page_id=page_ids["hidden"],
                        slug=f"cyg120-hidden-{unique}",
                        scope_type="department",
                        scope_id=hidden_department_id,
                        now=now,
                    ),
                }
                session.add_all(
                    [
                        visible_department,
                        hidden_department,
                        admin,
                        scoped_user,
                        membership,
                        *pages.values(),
                    ]
                )
                await session.flush()

                route_specs = (
                    (
                        "due",
                        "global",
                        "low_rating",
                        FeedbackRouteKind.REVIEW,
                        FeedbackRouteState.QUEUED,
                        0,
                        now - timedelta(hours=1),
                        None,
                        None,
                        None,
                        None,
                    ),
                    (
                        "future",
                        "global",
                        "stale_answer",
                        FeedbackRouteKind.REFRESH,
                        FeedbackRouteState.QUEUED,
                        0,
                        now + timedelta(hours=1),
                        None,
                        None,
                        None,
                        None,
                    ),
                    (
                        "running",
                        "visible",
                        "stale_answer",
                        FeedbackRouteKind.REFRESH,
                        FeedbackRouteState.RUNNING,
                        2,
                        None,
                        now - timedelta(minutes=1),
                        None,
                        None,
                        None,
                    ),
                    (
                        "completed",
                        "global",
                        "low_rating",
                        FeedbackRouteKind.REVIEW,
                        FeedbackRouteState.COMPLETED,
                        1,
                        None,
                        None,
                        outcome_id,
                        None,
                        now - timedelta(minutes=8, seconds=20),
                    ),
                    (
                        "blocked",
                        "visible",
                        "low_rating",
                        FeedbackRouteKind.REVIEW,
                        FeedbackRouteState.BLOCKED,
                        1,
                        None,
                        None,
                        None,
                        "target_required",
                        now - timedelta(minutes=7),
                    ),
                    (
                        "failed",
                        "global",
                        "stale_answer",
                        FeedbackRouteKind.REFRESH,
                        FeedbackRouteState.FAILED,
                        3,
                        None,
                        None,
                        None,
                        "retry_exhausted",
                        now - timedelta(minutes=6),
                    ),
                    (
                        "hidden",
                        "hidden",
                        "low_rating",
                        FeedbackRouteKind.REVIEW,
                        FeedbackRouteState.BLOCKED,
                        1,
                        None,
                        None,
                        None,
                        "target_ineligible",
                        now - timedelta(minutes=5),
                    ),
                )
                feedback_rows: dict[str, GovernanceFeedbackSignal] = {}
                route_rows: dict[str, GovernanceFeedbackRoute] = {}
                for index, spec in enumerate(route_specs):
                    (
                        name,
                        page_name,
                        signal_type,
                        route_kind,
                        state,
                        attempts,
                        next_attempt_at,
                        lease_expires_at,
                        signal_id,
                        terminal_reason,
                        completed_at,
                    ) = spec
                    feedback_id = uuid.uuid4()
                    feedback_rows[name] = _feedback(
                        feedback_id=feedback_id,
                        actor_id=admin_id,
                        command_id=command_ids[name],
                        page_id=page_ids[page_name],
                        signal_type=signal_type,
                        now=now,
                    )
                    route_rows[name] = _route(
                        route_id=route_ids[name],
                        feedback_signal_id=feedback_id,
                        route_kind=route_kind,
                        state=state,
                        attempt_count=attempts,
                        created_at=(
                            now - timedelta(minutes=10)
                            if name == "completed"
                            else now - timedelta(hours=2)
                        ),
                        updated_at=now - timedelta(minutes=index + 1),
                        next_attempt_at=next_attempt_at,
                        lease_expires_at=lease_expires_at,
                        outcome_signal_id=signal_id,
                        terminal_reason=terminal_reason,
                        last_error=(
                            "secret customer payload must not leak"
                            if state is FeedbackRouteState.FAILED
                            else None
                        ),
                        completed_at=completed_at,
                    )
                outcome = _outcome(
                    signal_id=outcome_id,
                    route_id=route_ids["completed"],
                    actor_id=admin_id,
                    page_id=page_ids["global"],
                    now=now,
                )
                assignment = GovernanceReviewAssignment(
                    id=assignment_id,
                    signal_id=outcome_id,
                    lifecycle_state="assigned",
                    owner_ref="employee:reviewer-cyg120",
                    escalation_reason=None,
                    version=2,
                    created_at=now - timedelta(minutes=10),
                    updated_at=now - timedelta(minutes=9),
                )
                session.add_all([*feedback_rows.values(), outcome])
                await session.flush()
                session.add_all(
                    [
                        *route_rows.values(),
                        assignment,
                        AuditLog(
                            id=uuid.uuid4(),
                            timestamp=now - timedelta(minutes=13),
                            principal_id=admin_id,
                            principal_type="human",
                            action="record_feedback_signal",
                            resource_type="governance_feedback_signal",
                            resource_id=str(feedback_rows["completed"].id),
                            decision="ALLOW",
                            reason="feedback ref only",
                        ),
                        AuditLog(
                            id=uuid.uuid4(),
                            timestamp=now - timedelta(minutes=8),
                            principal_id=admin_id,
                            principal_type="human",
                            action="execute_feedback_route",
                            resource_type="governance_feedback_route",
                            resource_id=str(route_ids["completed"]),
                            decision="ALLOW",
                            reason="route and outcome refs only",
                        ),
                    ]
                )
                await session.commit()

            async with sessions() as session:
                scoped_user = (
                    await session.execute(
                        select(Employee)
                        .where(Employee.id == scoped_user_id)
                        .options(selectinload(Employee.employee_departments))
                    )
                ).scalar_one()
                initial = await list_feedback_route_operations(
                    session,
                    current_user=scoped_user,
                    query=FeedbackRouteOperationsQuery(page=1, page_size=2),
                    now=now,
                )
                payload = initial.to_dict()
                self.assertEqual(payload["total"], 6)
                summary = cast(dict[str, object], payload["summary"])
                counts_by_state = cast(dict[str, int], summary["counts_by_state"])
                self.assertEqual(counts_by_state["queued"], 2)
                self.assertEqual(counts_by_state["running"], 1)
                self.assertEqual(counts_by_state["completed"], 1)
                self.assertEqual(counts_by_state["blocked"], 1)
                self.assertEqual(counts_by_state["failed"], 1)
                self.assertEqual(summary["counts_by_kind"], {"review": 3, "refresh": 3})
                self.assertEqual(summary["oldest_due_queued_age_seconds"], 3600)
                self.assertEqual(summary["expired_running_leases"], 1)
                self.assertEqual(
                    summary["retry_distribution"],
                    {"0": 2, "1": 2, "2": 1, "3": 1},
                )
                self.assertEqual(
                    summary["completed_latency_seconds"],
                    {"observed_count": 1, "average": 100.0, "maximum": 100.0},
                )
                reason_counts = cast(
                    dict[str, dict[str, int]], summary["terminal_reason_counts"]
                )
                self.assertEqual(
                    reason_counts["blocked"],
                    {"target_required": 1},
                )
                self.assertEqual(
                    reason_counts["failed"],
                    {"retry_exhausted": 1},
                )
                items = cast(list[dict[str, object]], payload["items"])
                self.assertEqual(len(items), 2)
                self.assertEqual(
                    [item["route_id"] for item in items],
                    [str(route_ids["due"]), str(route_ids["future"])],
                )
                self.assertNotIn("secret customer payload", repr(payload))
                self.assertTrue(payload["persisted"])
                self.assertFalse(payload["rehearsal"])
                observation = cast(dict[str, object], payload["observation"])
                self.assertEqual(observation["state"], "ready")

                completed = await list_feedback_route_operations(
                    session,
                    current_user=scoped_user,
                    query=FeedbackRouteOperationsQuery(
                        route_state=FeedbackRouteState.COMPLETED,
                        page=1,
                        page_size=10,
                    ),
                    now=now,
                )
                self.assertEqual(completed.summary.total, 1)
                review = await list_feedback_route_operations(
                    session,
                    current_user=scoped_user,
                    query=FeedbackRouteOperationsQuery(
                        route_kind=FeedbackRouteKind.REVIEW,
                        page=1,
                        page_size=10,
                    ),
                    now=now,
                )
                self.assertEqual(review.summary.total, 3)

                detail = await get_feedback_route_operation(
                    session,
                    current_user=scoped_user,
                    route_id=route_ids["completed"],
                    now=now,
                )
                if detail is None:
                    raise AssertionError("visible route drilldown was hidden")
                detail_payload = detail.to_dict()
                feedback_payload = cast(dict[str, object], detail_payload["feedback"])
                outcome_payload = cast(dict[str, object], detail_payload["outcome"])
                assignment_payload = cast(
                    dict[str, object], detail_payload["review_assignment"]
                )
                audit_payloads = cast(
                    list[dict[str, object]], detail_payload["audit_traces"]
                )
                self.assertEqual(
                    feedback_payload["feedback_ref"],
                    f"feedback-signal:{feedback_rows['completed'].id}",
                )
                self.assertEqual(
                    outcome_payload["signal_ref"],
                    f"feedback-route:{route_ids['completed']}",
                )
                self.assertEqual(
                    assignment_payload["trace_ref"],
                    f"review-assignment:{assignment_id}",
                )
                self.assertEqual(len(audit_payloads), 2)
                hidden = await get_feedback_route_operation(
                    session,
                    current_user=scoped_user,
                    route_id=route_ids["hidden"],
                    now=now,
                )
                missing = await get_feedback_route_operation(
                    session,
                    current_user=scoped_user,
                    route_id=uuid.uuid4(),
                    now=now,
                )
                self.assertIsNone(hidden)
                self.assertIsNone(missing)

                admin = (
                    await session.execute(
                        select(Employee).where(Employee.id == admin_id)
                    )
                ).scalar_one()
                admin_page = await list_feedback_route_operations(
                    session,
                    current_user=admin,
                    query=FeedbackRouteOperationsQuery(page=1, page_size=100),
                    now=now,
                )
                self.assertEqual(admin_page.summary.total, 7)

            async with sessions() as session:
                sweep = await claim_feedback_routes(session, now=now)
                recovered = next(
                    claim
                    for claim in sweep.claims
                    if claim.route_id == route_ids["running"]
                )
                self.assertIs(recovered.claimed_from_state, FeedbackRouteState.RUNNING)
                self.assertEqual(recovered.attempt_count, 3)
                await session.commit()

            await engine.dispose()
            engine = create_async_engine(_INTEGRATION_DATABASE_URL)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                scoped_user = (
                    await session.execute(
                        select(Employee)
                        .where(Employee.id == scoped_user_id)
                        .options(selectinload(Employee.employee_departments))
                    )
                ).scalar_one()
                restarted = await list_feedback_route_operations(
                    session,
                    current_user=scoped_user,
                    query=FeedbackRouteOperationsQuery(page=1, page_size=100),
                    now=now,
                )
                restarted_payload = restarted.to_dict()
                self.assertEqual(restarted_payload["total"], 6)
                restarted_items = cast(
                    list[dict[str, object]], restarted_payload["items"]
                )
                restarted_routes = {
                    str(item["route_id"]): item for item in restarted_items
                }
                self.assertEqual(
                    restarted_routes[str(route_ids["running"])]["route_state"],
                    "running",
                )
                self.assertEqual(
                    restarted_routes[str(route_ids["running"])]["attempt_count"],
                    3,
                )
                self.assertFalse(
                    restarted_routes[str(route_ids["running"])]["lease_expired"]
                )
        finally:
            async with sessions() as session:
                _ = await session.execute(
                    delete(GovernanceReviewAssignmentEvent).where(
                        GovernanceReviewAssignmentEvent.assignment_id == assignment_id
                    )
                )
                _ = await session.execute(
                    delete(GovernanceReviewAssignment).where(
                        GovernanceReviewAssignment.id == assignment_id
                    )
                )
                _ = await session.execute(
                    delete(GovernanceFeedbackRoute).where(
                        GovernanceFeedbackRoute.id.in_(tuple(route_ids.values()))
                    )
                )
                _ = await session.execute(
                    delete(GovernanceFeedbackSignal).where(
                        GovernanceFeedbackSignal.command_id.in_(
                            tuple(command_ids.values())
                        )
                    )
                )
                _ = await session.execute(
                    delete(GovernanceSignal).where(GovernanceSignal.id == outcome_id)
                )
                _ = await session.execute(
                    delete(WikiPage).where(WikiPage.id.in_(tuple(page_ids.values())))
                )
                _ = await session.execute(
                    delete(EmployeeDepartment).where(
                        EmployeeDepartment.employee_id.in_((admin_id, scoped_user_id))
                    )
                )
                _ = await session.execute(
                    delete(Employee).where(Employee.id.in_((admin_id, scoped_user_id)))
                )
                _ = await session.execute(
                    delete(Department).where(
                        Department.id.in_((visible_department_id, hidden_department_id))
                    )
                )
                await session.commit()
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
