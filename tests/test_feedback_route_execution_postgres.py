from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
import unittest
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cygnus.governance.feedback import FeedbackSignalInput, create_feedback_signal
from cygnus.governance.feedback_execution import (
    FeedbackRouteClaim,
    claim_feedback_routes,
    execute_feedback_route,
    record_feedback_route_failure,
)
from cygnus.governance.feedback_routing import route_feedback_signal
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceFeedbackRoute,
    GovernanceFeedbackSignal,
    GovernanceReviewAssignment,
    GovernanceSignal,
    WikiPage,
)


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")


def _page(*, page_id: uuid.UUID, slug: str) -> WikiPage:
    return WikiPage(
        id=page_id,
        slug=slug,
        title=f"Feedback route {slug}",
        status="mature",
        content_md=f"# Feedback route {slug}\n\nGoverned support guidance.",
        summary="Governed support guidance.",
        scope_type="global",
        scope_id=None,
        knowledge_type_slugs=["answer_card"],
        source_ids=[],
        version=1,
        orphaned=False,
    )


async def _create_route(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    command_id: str,
    signal_type: str = "low_rating",
    page: WikiPage | None = None,
) -> GovernanceFeedbackRoute:
    if page is not None:
        session.add(page)
        await session.flush()
    write = await create_feedback_signal(
        session,
        FeedbackSignalInput(
            command_id=command_id,
            signal_type=signal_type,
            audience_context={"visibility": "internal"},
            object_id=f"ko-{page.slug}" if page is not None else None,
            page_id=page.id if page is not None else None,
        ),
        actor_id=actor_id,
    )
    route = await route_feedback_signal(session, write.signal)
    if route is None:
        raise AssertionError("routed feedback did not create a durable route")
    return route


async def _route_audit_count(session: AsyncSession, route_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.resource_type == "governance_feedback_route",
                AuditLog.resource_id == str(route_id),
            )
        )
    ).scalar_one()


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class FeedbackRoutePostgresTests(unittest.TestCase):
    def test_claim_execute_block_recover_and_replay_survive_restart(self) -> None:
        asyncio.run(self._exercise_feedback_route_lifecycle())

    async def _exercise_feedback_route_lifecycle(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        actor_id = uuid.uuid4()
        unique = uuid.uuid4().hex
        command_ids = (
            f"cyg119-complete-{unique}",
            f"cyg119-blocked-{unique}",
            f"cyg119-retry-{unique}",
        )
        page_ids = (uuid.uuid4(), uuid.uuid4())
        now = datetime.now(timezone.utc) + timedelta(seconds=1)

        try:
            async with sessions() as session:
                session.add(
                    Employee(
                        id=actor_id,
                        name="CYG-119 integration actor",
                        email=f"cyg119-{unique}@example.test",
                        role="admin",
                        global_role="admin",
                        is_active=True,
                    )
                )
                await session.flush()
                completed_route = await _create_route(
                    session,
                    actor_id=actor_id,
                    command_id=command_ids[0],
                    page=_page(page_id=page_ids[0], slug=f"cyg119-complete-{unique}"),
                )
                completed_route_id = completed_route.id
                await session.commit()

            async with (
                sessions() as first_claim_session,
                sessions() as concurrent_session,
            ):
                first_sweep = await claim_feedback_routes(
                    first_claim_session,
                    now=now,
                    limit=1,
                )
                first_claims = first_sweep.claims
                self.assertEqual(len(first_claims), 1)
                self.assertEqual(first_claims[0].route_id, completed_route_id)
                skipped_sweep = await claim_feedback_routes(
                    concurrent_session,
                    now=now,
                    limit=1,
                )
                skipped_claims = skipped_sweep.claims
                self.assertEqual(skipped_claims, ())
                await first_claim_session.commit()
                completed_claim = first_claims[0]

            async with sessions() as session:
                completed = await execute_feedback_route(
                    session,
                    completed_claim,
                    now=now + timedelta(seconds=1),
                )
                self.assertEqual(completed.lifecycle_state, "completed")
                self.assertIsNotNone(completed.outcome_signal_id)
                completed_outcome_id = completed.outcome_signal_id
                await session.commit()

            async with sessions() as session:
                signal_count = (
                    await session.execute(
                        select(func.count(GovernanceSignal.id)).where(
                            GovernanceSignal.signal_ref
                            == f"feedback-route:{completed_route_id}"
                        )
                    )
                ).scalar_one()
                assignment_count = (
                    await session.execute(
                        select(func.count(GovernanceReviewAssignment.id)).where(
                            GovernanceReviewAssignment.signal_id == completed_outcome_id
                        )
                    )
                ).scalar_one()
                self.assertEqual(signal_count, 1)
                self.assertEqual(assignment_count, 1)
                self.assertEqual(
                    await _route_audit_count(session, completed_route_id),
                    1,
                )

            await engine.dispose()
            engine = create_async_engine(_INTEGRATION_DATABASE_URL)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async with sessions() as session:
                replayed = await execute_feedback_route(
                    session,
                    completed_claim,
                    now=now + timedelta(minutes=10),
                )
                self.assertEqual(replayed.lifecycle_state, "completed")
                self.assertEqual(replayed.outcome_signal_id, completed_outcome_id)
                await session.commit()
            async with sessions() as session:
                self.assertEqual(
                    await _route_audit_count(session, completed_route_id),
                    1,
                )

            async with sessions() as session:
                blocked_route = await _create_route(
                    session,
                    actor_id=actor_id,
                    command_id=command_ids[1],
                )
                blocked_route_id = blocked_route.id
                await session.commit()
            async with sessions() as session:
                blocked_sweep = await claim_feedback_routes(
                    session,
                    now=now + timedelta(minutes=11),
                )
                blocked_claims = blocked_sweep.claims
                self.assertEqual(len(blocked_claims), 1)
                self.assertEqual(blocked_claims[0].route_id, blocked_route_id)
                await session.commit()
            async with sessions() as session:
                blocked = await execute_feedback_route(
                    session,
                    blocked_claims[0],
                    now=now + timedelta(minutes=11, seconds=1),
                )
                self.assertEqual(blocked.lifecycle_state, "blocked")
                self.assertEqual(blocked.terminal_reason, "target_required")
                self.assertIsNone(blocked.outcome_signal_id)
                await session.commit()

            async with sessions() as session:
                retry_route = await _create_route(
                    session,
                    actor_id=actor_id,
                    command_id=command_ids[2],
                    page=_page(page_id=page_ids[1], slug=f"cyg119-retry-{unique}"),
                )
                retry_route_id = retry_route.id
                await session.commit()

            retry_start = now + timedelta(minutes=12)
            async with sessions() as session:
                retry_sweep = await claim_feedback_routes(session, now=retry_start)
                retry_claims = retry_sweep.claims
                self.assertEqual(len(retry_claims), 1)
                retry_claim = retry_claims[0]
                self.assertEqual(retry_claim.route_id, retry_route_id)
                self.assertEqual(retry_claim.attempt_count, 1)
                await session.commit()
            async with sessions() as session:
                requeued = await record_feedback_route_failure(
                    session,
                    retry_claim,
                    error=RuntimeError("temporary route failure"),
                    now=retry_start + timedelta(seconds=1),
                )
                self.assertEqual(requeued.lifecycle_state, "queued")
                self.assertEqual(
                    requeued.next_attempt_at,
                    retry_start + timedelta(seconds=31),
                )
                await session.commit()
            async with sessions() as session:
                early_sweep = await claim_feedback_routes(
                    session,
                    now=retry_start + timedelta(seconds=30),
                )
                early_claims = early_sweep.claims
                self.assertEqual(early_claims, ())
                await session.rollback()
            async with sessions() as session:
                second_sweep = await claim_feedback_routes(
                    session,
                    now=retry_start + timedelta(seconds=31),
                )
                second_claims = second_sweep.claims
                self.assertEqual(len(second_claims), 1)
                self.assertEqual(second_claims[0].attempt_count, 2)
                await session.commit()
            async with sessions() as session:
                recovered_sweep = await claim_feedback_routes(
                    session,
                    now=retry_start + timedelta(seconds=91),
                )
                recovered_claims = recovered_sweep.claims
                self.assertEqual(len(recovered_claims), 1)
                recovered_claim: FeedbackRouteClaim = recovered_claims[0]
                self.assertEqual(recovered_claim.route_id, retry_route_id)
                self.assertEqual(recovered_claim.attempt_count, 3)
                await session.commit()
            async with sessions() as session:
                recovered = await execute_feedback_route(
                    session,
                    recovered_claim,
                    now=retry_start + timedelta(seconds=92),
                )
                self.assertEqual(recovered.lifecycle_state, "completed")
                self.assertEqual(recovered.attempt_count, 3)
                self.assertIsNotNone(recovered.outcome_signal_id)
                await session.commit()
        finally:
            async with sessions() as session:
                _ = await session.execute(
                    delete(AuditLog).where(AuditLog.principal_id == actor_id)
                )
                _ = await session.execute(
                    delete(GovernanceFeedbackSignal).where(
                        GovernanceFeedbackSignal.command_id.in_(command_ids)
                    )
                )
                await session.flush()
                _ = await session.execute(
                    delete(GovernanceSignal).where(
                        GovernanceSignal.created_by_id == actor_id
                    )
                )
                _ = await session.execute(
                    delete(WikiPage).where(WikiPage.id.in_(page_ids))
                )
                _ = await session.execute(
                    delete(Employee).where(Employee.id == actor_id)
                )
                await session.commit()
            await engine.dispose()


if __name__ == "__main__":
    _ = unittest.main()
