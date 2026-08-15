from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, call, patch

from cygnus.governance.feedback_execution import (
    FeedbackRouteClaim,
    FeedbackRouteClaimSweep,
    FeedbackRouteTerminalization,
)
from cygnus.governance.feedback_operations import FeedbackRouteWorkerEvent
from cygnus.governance.feedback_routing import FeedbackRouteKind, FeedbackRouteState


class _Session:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1
        self.events.append(f"{self.name}.commit")

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append(f"{self.name}.rollback")


class _SessionScope:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        self.session.events.append(f"{self.session.name}.enter")
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.session.events.append(f"{self.session.name}.exit")
        return False


class _HeartbeatRedis:
    """Minimal Redis fake so WorkerSettings.on_startup can publish heartbeats."""

    async def set(self, *_args, **_kwargs) -> None:
        return None


class _SessionFactory:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = iter(sessions)
        self.opened: list[_Session] = []

    def __call__(self) -> _SessionScope:
        session = next(self._sessions)
        self.opened.append(session)
        return _SessionScope(session)


def _claim(*, recovered: bool = False, attempt_count: int = 1) -> FeedbackRouteClaim:
    return FeedbackRouteClaim(
        route_id=uuid.uuid4(),
        route_kind=FeedbackRouteKind.REVIEW,
        lease_token=uuid.uuid4().hex,
        attempt_count=attempt_count,
        claimed_from_state=(
            FeedbackRouteState.RUNNING if recovered else FeedbackRouteState.QUEUED
        ),
    )


def _sweep(*claims: FeedbackRouteClaim) -> FeedbackRouteClaimSweep:
    return FeedbackRouteClaimSweep(claims=claims, terminalized=())


def _route_result(
    state: FeedbackRouteState,
    *,
    terminal_reason: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        lifecycle_state=state.value,
        outcome_signal_id=(
            uuid.uuid4() if state is FeedbackRouteState.COMPLETED else None
        ),
        terminal_reason=terminal_reason,
    )


class FeedbackRouteWorkerWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_drain_commits_claims_before_isolated_execution_transactions(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        now = object()
        first = _claim()
        second = _claim()
        events: list[str] = []
        claim_session = _Session("claim", events)
        first_execution = _Session("execute-first", events)
        second_execution = _Session("execute-second", events)
        session_factory = _SessionFactory(
            [claim_session, first_execution, second_execution]
        )

        async def execute(session, claim, *, now) -> SimpleNamespace:
            events.append(f"{session.name}.execute:{claim.route_id}")
            if claim is second:
                return _route_result(
                    FeedbackRouteState.BLOCKED,
                    terminal_reason="target_required",
                )
            return _route_result(FeedbackRouteState.COMPLETED)

        def emit(**fields: object) -> dict[str, object]:
            events.append(f"event:{fields['event']}")
            return dict(fields)

        with (
            patch.object(
                worker_module,
                "claim_feedback_routes",
                AsyncMock(return_value=_sweep(first, second)),
            ) as claim_routes,
            patch.object(
                worker_module,
                "execute_feedback_route",
                AsyncMock(side_effect=execute),
            ) as execute_route,
            patch.object(
                worker_module,
                "record_feedback_route_failure",
                AsyncMock(),
            ) as record_failure,
            patch.object(
                worker_module,
                "emit_feedback_route_worker_event",
                side_effect=emit,
            ) as emit_event,
        ):
            drained = await worker_module.drain_feedback_routes(
                now=now,
                limit=2,
                session_factory=session_factory,
            )

        self.assertEqual(drained, 2)
        claim_routes.assert_awaited_once_with(claim_session, now=now, limit=2)
        self.assertEqual(
            execute_route.await_args_list,
            [
                call(first_execution, first, now=now),
                call(second_execution, second, now=now),
            ],
        )
        record_failure.assert_not_awaited()
        self.assertEqual(
            session_factory.opened,
            [claim_session, first_execution, second_execution],
        )
        self.assertEqual(claim_session.commit_count, 1)
        self.assertEqual(first_execution.commit_count, 1)
        self.assertEqual(second_execution.commit_count, 1)
        self.assertEqual(
            [
                claim_session.rollback_count,
                first_execution.rollback_count,
                second_execution.rollback_count,
            ],
            [0, 0, 0],
        )
        emitted = [item.kwargs for item in emit_event.call_args_list]
        self.assertEqual(
            [item["event"] for item in emitted],
            [
                FeedbackRouteWorkerEvent.CLAIMED,
                FeedbackRouteWorkerEvent.CLAIMED,
                FeedbackRouteWorkerEvent.COMPLETED,
                FeedbackRouteWorkerEvent.BLOCKED,
            ],
        )
        self.assertEqual(emitted[-1]["terminal_reason"], "target_required")
        self.assertLess(
            events.index("claim.commit"),
            events.index(f"event:{FeedbackRouteWorkerEvent.CLAIMED}"),
        )
        self.assertLess(
            events.index("claim.commit"),
            events.index(f"execute-first.execute:{first.route_id}"),
        )

    async def test_execution_failure_rolls_back_records_in_fresh_session_and_continues(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        now = object()
        bad_claim = _claim()
        good_claim = _claim()
        events: list[str] = []
        claim_session = _Session("claim", events)
        bad_execution = _Session("execute-bad", events)
        bad_failure = _Session("failure-bad", events)
        good_execution = _Session("execute-good", events)
        session_factory = _SessionFactory(
            [claim_session, bad_execution, bad_failure, good_execution]
        )
        execution_error = RuntimeError("route execution failed with customer payload")

        async def execute(session, claim, *, now) -> SimpleNamespace:
            events.append(f"{session.name}.execute:{claim.route_id}")
            if claim is bad_claim:
                raise execution_error
            return _route_result(FeedbackRouteState.COMPLETED)

        with (
            patch.object(
                worker_module,
                "claim_feedback_routes",
                AsyncMock(return_value=_sweep(bad_claim, good_claim)),
            ),
            patch.object(
                worker_module,
                "execute_feedback_route",
                AsyncMock(side_effect=execute),
            ) as execute_route,
            patch.object(
                worker_module,
                "record_feedback_route_failure",
                AsyncMock(return_value=_route_result(FeedbackRouteState.QUEUED)),
            ) as record_failure,
            patch.object(
                worker_module,
                "emit_feedback_route_worker_event",
                return_value={},
            ) as emit_event,
        ):
            drained = await worker_module.drain_feedback_routes(
                now=now,
                limit=2,
                session_factory=session_factory,
            )

        self.assertEqual(drained, 2)
        self.assertEqual(
            session_factory.opened,
            [claim_session, bad_execution, bad_failure, good_execution],
        )
        self.assertEqual(claim_session.commit_count, 1)
        self.assertEqual(bad_execution.commit_count, 0)
        self.assertEqual(bad_execution.rollback_count, 1)
        self.assertEqual(bad_failure.commit_count, 1)
        self.assertEqual(bad_failure.rollback_count, 0)
        self.assertEqual(good_execution.commit_count, 1)
        self.assertEqual(good_execution.rollback_count, 0)
        record_failure.assert_awaited_once_with(
            bad_failure,
            bad_claim,
            error=execution_error,
            now=now,
        )
        self.assertEqual(
            execute_route.await_args_list,
            [
                call(bad_execution, bad_claim, now=now),
                call(good_execution, good_claim, now=now),
            ],
        )
        emitted = [item.kwargs for item in emit_event.call_args_list]
        self.assertEqual(
            [item["event"] for item in emitted],
            [
                FeedbackRouteWorkerEvent.CLAIMED,
                FeedbackRouteWorkerEvent.CLAIMED,
                FeedbackRouteWorkerEvent.EXECUTION_ERROR,
                FeedbackRouteWorkerEvent.RETRY_SCHEDULED,
                FeedbackRouteWorkerEvent.COMPLETED,
            ],
        )
        self.assertEqual(emitted[2]["exception_class"], "RuntimeError")
        self.assertNotIn("customer payload", str(emitted))
        self.assertLess(
            events.index("failure-bad.commit"),
            events.index(f"execute-good.execute:{good_claim.route_id}"),
        )

    async def test_lost_execution_lease_rolls_back_without_failure_mutation(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        claim = _claim()
        events: list[str] = []
        claim_session = _Session("claim", events)
        execution_session = _Session("execute", events)
        session_factory = _SessionFactory([claim_session, execution_session])

        with (
            patch.object(
                worker_module,
                "claim_feedback_routes",
                AsyncMock(return_value=_sweep(claim)),
            ) as claim_routes,
            patch.object(
                worker_module,
                "execute_feedback_route",
                AsyncMock(side_effect=worker_module.FeedbackRouteLeaseLost()),
            ),
            patch.object(
                worker_module,
                "record_feedback_route_failure",
                AsyncMock(),
            ) as record_failure,
            patch.object(
                worker_module,
                "emit_feedback_route_worker_event",
                return_value={},
            ) as emit_event,
        ):
            drained = await worker_module.drain_feedback_routes(
                session_factory=session_factory,
            )

        self.assertEqual(drained, 1)
        claim_routes.assert_awaited_once_with(claim_session, now=None, limit=25)
        self.assertEqual(claim_session.commit_count, 1)
        self.assertEqual(execution_session.commit_count, 0)
        self.assertEqual(execution_session.rollback_count, 1)
        record_failure.assert_not_awaited()
        emitted = [item.kwargs for item in emit_event.call_args_list]
        self.assertEqual(
            [item["event"] for item in emitted],
            [FeedbackRouteWorkerEvent.CLAIMED, FeedbackRouteWorkerEvent.LEASE_LOST],
        )
        self.assertEqual(emitted[-1]["exception_class"], "FeedbackRouteLeaseLost")

    async def test_claim_recovery_emits_recovered_and_terminal_failed_outcomes(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        recovered = _claim(recovered=True, attempt_count=2)
        terminalized = FeedbackRouteTerminalization(
            route_id=uuid.uuid4(),
            route_kind=FeedbackRouteKind.REFRESH,
            previous_state=FeedbackRouteState.RUNNING,
            attempt_count=3,
            terminal_reason="retry_exhausted",
        )
        sweep = FeedbackRouteClaimSweep(
            claims=(recovered,),
            terminalized=(terminalized,),
        )
        events: list[str] = []
        session_factory = _SessionFactory(
            [_Session("claim", events), _Session("execute", events)]
        )
        with (
            patch.object(
                worker_module,
                "claim_feedback_routes",
                AsyncMock(return_value=sweep),
            ),
            patch.object(
                worker_module,
                "execute_feedback_route",
                AsyncMock(return_value=_route_result(FeedbackRouteState.COMPLETED)),
            ),
            patch.object(
                worker_module,
                "emit_feedback_route_worker_event",
                return_value={},
            ) as emit_event,
        ):
            drained = await worker_module.drain_feedback_routes(
                session_factory=session_factory
            )

        self.assertEqual(drained, 1)
        emitted = [item.kwargs for item in emit_event.call_args_list]
        self.assertEqual(
            [item["event"] for item in emitted],
            [
                FeedbackRouteWorkerEvent.FAILED,
                FeedbackRouteWorkerEvent.LEASE_RECOVERED,
                FeedbackRouteWorkerEvent.COMPLETED,
            ],
        )
        self.assertEqual(emitted[0]["transition"], "running_to_failed")
        self.assertEqual(emitted[1]["transition"], "running_to_running")

    async def test_cron_and_startup_both_invoke_feedback_route_drain(self) -> None:
        import cygnus.runtime.worker as worker_module

        pre_review_sweep = AsyncMock(return_value=0)
        route_drain = AsyncMock(side_effect=[3, 0])
        with (
            patch(
                "cygnus.review.pre_review.dispatch.sweep_ai_pre_review_dispatches",
                pre_review_sweep,
            ),
            patch.object(worker_module, "drain_feedback_routes", route_drain),
        ):
            await worker_module.sweep_feedback_routes_cron({})
            await worker_module.WorkerSettings.on_startup({"redis": _HeartbeatRedis()})

        self.assertEqual(route_drain.await_count, 2)
        pre_review_sweep.assert_awaited_once()
        cron_names = {
            getattr(item, "name", None)
            or getattr(item, "__name__", None)
            or getattr(getattr(item, "coroutine", None), "__name__", None)
            for item in worker_module.WorkerSettings.cron_jobs
        }
        self.assertTrue(
            any(
                name and name.endswith("sweep_feedback_routes_cron")
                for name in cron_names
            )
        )

    async def test_startup_skips_delivery_claims_while_route_is_unavailable(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        pre_review_sweep = AsyncMock(return_value=0)
        feedback_drain = AsyncMock(return_value=0)
        route_ready = AsyncMock(return_value=False)
        delivery_drain = AsyncMock(return_value=1)
        with (
            patch(
                "cygnus.review.pre_review.dispatch.sweep_ai_pre_review_dispatches",
                pre_review_sweep,
            ),
            patch.object(worker_module, "drain_feedback_routes", feedback_drain),
            patch("cygnus.publish.delivery.delivery_targets_ready", route_ready),
            patch(
                "cygnus.publish.delivery.drain_propagation_deliveries",
                delivery_drain,
            ),
        ):
            await worker_module.WorkerSettings.on_startup({"redis": _HeartbeatRedis()})

        route_ready.assert_awaited_once_with()
        delivery_drain.assert_not_awaited()

    async def test_feedback_startup_failure_does_not_skip_pre_review_recovery(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        pre_review_sweep = AsyncMock(return_value=1)
        route_drain = AsyncMock(side_effect=RuntimeError("database unavailable"))
        with (
            patch(
                "cygnus.review.pre_review.dispatch.sweep_ai_pre_review_dispatches",
                pre_review_sweep,
            ),
            patch.object(worker_module, "drain_feedback_routes", route_drain),
        ):
            await worker_module.WorkerSettings.on_startup({"redis": _HeartbeatRedis()})

        pre_review_sweep.assert_awaited_once()
        route_drain.assert_awaited_once()

    async def test_pre_review_startup_failure_does_not_skip_feedback_recovery(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module

        pre_review_sweep = AsyncMock(side_effect=RuntimeError("redis unavailable"))
        route_drain = AsyncMock(return_value=1)
        with (
            patch(
                "cygnus.review.pre_review.dispatch.sweep_ai_pre_review_dispatches",
                pre_review_sweep,
            ),
            patch.object(worker_module, "drain_feedback_routes", route_drain),
        ):
            await worker_module.WorkerSettings.on_startup({"redis": _HeartbeatRedis()})

        pre_review_sweep.assert_awaited_once()
        route_drain.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
