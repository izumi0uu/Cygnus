"""Focused recovery/concurrency tests for the durable source dispatch lifecycle.

Covers the CYG-130/CYG-128 execution-reliability contract:

- deterministic job identity (crash/restart cannot silently duplicate enqueues),
- generation fencing of stale attempts (an older-generation job is fenced
  before it can write progress or pages),
- lease take-over on legitimate re-runs,
- safe enqueue reconciliation: ARQ duplicate = acknowledgement; known enqueue
  failures stay pending with a retry budget and structured errors.

The tests drive the module with fakes (no live Postgres/Redis), matching the
project's existing mock-session test conventions.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import Source, SourceDispatchExecution
from cygnus.runtime import source_dispatch as dispatch


def _source(*, generation: int = 1, deleted: bool = False) -> Source:
    source = Source(id=uuid.uuid4(), title="t")
    source.dispatch_generation = generation
    source.delete_requested_at = datetime.now(timezone.utc) if deleted else None
    return source


def _execution(
    *,
    source_id: uuid.UUID,
    generation: int,
    stage: str = dispatch.DISPATCH_STAGE_INGEST,
    status: str = dispatch.DISPATCH_STATUS_PENDING,
    attempt_count: int = 0,
) -> SourceDispatchExecution:
    return SourceDispatchExecution(
        id=uuid.uuid4(),
        source_id=source_id,
        generation=generation,
        stage=stage,
        task_name="ingest_file_task",
        task_args=["src"],
        job_id=dispatch.source_stage_job_id(source_id, stage, generation),
        dispatch_status=status,
        attempt_count=attempt_count,
    )


class _Result:
    """Canned SQLAlchemy result projection."""

    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)

    def one_or_none(self):
        return self._scalar


class _FakeDb:
    """Minimal AsyncSession stand-in with a queue of canned results."""

    def __init__(self, results=None, get_row=None):
        self.results = list(results or [])
        self.get_row = get_row
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rolled_back = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        if self.results:
            return self.results.pop(0)
        return _Result(rows=[], scalar=None)

    async def get(self, model, ident, **kwargs):
        if isinstance(self.get_row, dict):
            return self.get_row.get(getattr(model, "__name__", None))
        return self.get_row

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rolled_back += 1

    async def flush(self):
        pass

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)


class _FakeFactory:
    """Session factory returning queued fakes (one per ``async with``)."""

    def __init__(self, *dbs):
        self._dbs = list(dbs)

    def __call__(self):
        if self._dbs:
            return self._dbs.pop(0)
        return _FakeDb()


class DeterministicJobIdentityTests(unittest.TestCase):
    def test_job_id_roundtrips_through_parser(self) -> None:
        source_id = uuid.uuid4()
        job_id = dispatch.source_stage_job_id(
            source_id, dispatch.DISPATCH_STAGE_MAP_REDUCE, 3
        )
        parsed = dispatch.parse_dispatch_job_id(job_id)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        parsed_source, parsed_stage, parsed_generation = parsed
        self.assertEqual(parsed_source, source_id)
        self.assertEqual(parsed_stage, dispatch.DISPATCH_STAGE_MAP_REDUCE)
        self.assertEqual(parsed_generation, 3)

    def test_foreign_job_ids_are_not_parsed(self) -> None:
        self.assertIsNone(dispatch.parse_dispatch_job_id(None))
        self.assertIsNone(dispatch.parse_dispatch_job_id("arq:some-uuid:task"))
        self.assertIsNone(
            dispatch.parse_dispatch_job_id("source-dispatch:not-a-uuid:ingest:1")
        )

    def test_task_stage_mapping_covers_every_source_task(self) -> None:
        self.assertEqual(
            dispatch.dispatch_stage_for_task("ingest_file_task"),
            dispatch.DISPATCH_STAGE_INGEST,
        )
        self.assertEqual(
            dispatch.dispatch_stage_for_task("ingest_url_task"),
            dispatch.DISPATCH_STAGE_INGEST,
        )
        self.assertEqual(
            dispatch.dispatch_stage_for_task("caption_images_task"),
            dispatch.DISPATCH_STAGE_POST_EXTRACTION,
        )
        self.assertEqual(
            dispatch.dispatch_stage_for_task("ingest_map_reduce_task"),
            dispatch.DISPATCH_STAGE_MAP_REDUCE,
        )
        self.assertEqual(
            dispatch.dispatch_stage_for_task("ingest_refine_task"),
            dispatch.DISPATCH_STAGE_REFINE,
        )
        self.assertEqual(
            dispatch.dispatch_stage_for_task("regenerate_plan_task"),
            dispatch.DISPATCH_STAGE_REGENERATE_PLAN,
        )
        self.assertIsNone(dispatch.dispatch_stage_for_task("ingest_skill_task"))


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_starts_cycle_at_generation_one(self) -> None:
        source = _source(generation=0)
        row = _execution(
            source_id=source.id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
        )
        db = _FakeDb(results=[_Result(rows=[]), _Result(scalar=row)])
        recorded, generation, job_id = await dispatch.record_source_dispatch(
            cast(AsyncSession, cast(object, db)),
            source,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            task_name="ingest_file_task",
            task_args=("src",),
            new_generation=True,
        )
        self.assertEqual(generation, 1)
        self.assertEqual(source.dispatch_generation, 1)
        self.assertEqual(
            job_id,
            dispatch.source_stage_job_id(source.id, dispatch.DISPATCH_STAGE_INGEST, 1),
        )
        self.assertIs(recorded, row)

    async def test_record_bumps_generation_for_new_cycle(self) -> None:
        source = _source(generation=2)
        row = _execution(
            source_id=source.id,
            generation=3,
            stage=dispatch.DISPATCH_STAGE_MAP_REDUCE,
        )
        db = _FakeDb(results=[_Result(rows=[]), _Result(scalar=row)])
        _recorded, generation, _job_id = await dispatch.record_source_dispatch(
            cast(AsyncSession, cast(object, db)),
            source,
            stage=dispatch.DISPATCH_STAGE_MAP_REDUCE,
            task_name="ingest_map_reduce_task",
            task_args=("src",),
            new_generation=True,
        )
        self.assertEqual(generation, 3)
        self.assertEqual(source.dispatch_generation, 3)

    async def test_record_never_rearms_a_terminal_row(self) -> None:
        source = _source(generation=1)
        row = _execution(
            source_id=source.id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_COMPLETED,
        )
        row.terminal_reason = "awaiting_approval"
        db = _FakeDb(results=[_Result(rows=[]), _Result(scalar=row)])
        recorded, _generation, _job_id = await dispatch.record_source_dispatch(
            cast(AsyncSession, cast(object, db)),
            source,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            task_name="ingest_file_task",
            task_args=("src",),
            new_generation=False,
        )
        self.assertEqual(recorded.dispatch_status, dispatch.DISPATCH_STATUS_COMPLETED)


class ClaimFencingTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_fences_older_generation_deterministic_job(self) -> None:
        source = _source(generation=2)
        old_row = _execution(
            source_id=source.id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
        )
        db = _FakeDb(results=[_Result(scalar=old_row)])
        stale_job_id = dispatch.source_stage_job_id(
            source.id, dispatch.DISPATCH_STAGE_INGEST, 1
        )
        with self.assertRaises(dispatch.SourceDispatchSuperseded):
            await dispatch.claim_source_dispatch(
                cast(AsyncSession, cast(object, db)),
                source,
                stage=dispatch.DISPATCH_STAGE_INGEST,
                job_id=stale_job_id,
            )
        self.assertEqual(old_row.dispatch_status, dispatch.DISPATCH_STATUS_STALE)
        self.assertEqual(old_row.terminal_reason, "superseded_by_generation")

    async def test_claim_fences_foreign_job_for_current_execution(self) -> None:
        source = _source(generation=1)
        row = _execution(
            source_id=source.id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_ENQUEUED,
        )
        db = _FakeDb(results=[_Result(scalar=row)])
        with self.assertRaises(dispatch.SourceDispatchSuperseded):
            await dispatch.claim_source_dispatch(
                cast(AsyncSession, cast(object, db)),
                source,
                stage=dispatch.DISPATCH_STAGE_INGEST,
                job_id="arq:some-other-job",
            )

    async def test_claim_takes_over_matching_execution_with_lease(self) -> None:
        source = _source(generation=1)
        row = _execution(
            source_id=source.id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_ENQUEUED,
        )
        db = _FakeDb(results=[_Result(scalar=row)])
        job_id = dispatch.source_stage_job_id(
            source.id, dispatch.DISPATCH_STAGE_INGEST, 1
        )
        claim = await dispatch.claim_source_dispatch(
            cast(AsyncSession, cast(object, db)),
            source,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            job_id=job_id,
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(row.dispatch_status, dispatch.DISPATCH_STATUS_RUNNING)
        self.assertIsNotNone(row.lease_token)
        self.assertIsNotNone(row.lease_expires_at)
        self.assertEqual(claim.generation, 1)
        self.assertEqual(claim.job_id, job_id)

    async def test_claim_returns_none_for_legacy_generation_zero(self) -> None:
        source = _source(generation=0)
        claim = await dispatch.claim_source_dispatch(
            cast(AsyncSession, cast(object, _FakeDb())),
            source,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            job_id="anything",
        )
        self.assertIsNone(claim)

    async def test_fence_raises_when_generation_moved(self) -> None:
        source_id = uuid.uuid4()
        claim = dispatch.SourceDispatchClaim(
            dispatch_id=uuid.uuid4(),
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_REFINE,
            task_name="ingest_refine_task",
            task_args=(),
            job_id="source-dispatch:x:refine:1",
            attempt_count=1,
            lease_token="tok",
        )
        db = _FakeDb(
            results=[
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_generation=2, delete_requested_at=None
                    )
                ),
            ]
        )
        with self.assertRaises(dispatch.SourceDispatchSuperseded):
            await dispatch.fence_source_dispatch(
                cast(AsyncSession, cast(object, db)), claim, source_id=source_id
            )

    async def test_fence_raises_when_source_tombstoned(self) -> None:
        source_id = uuid.uuid4()
        claim = dispatch.SourceDispatchClaim(
            dispatch_id=uuid.uuid4(),
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_REFINE,
            task_name="ingest_refine_task",
            task_args=(),
            job_id="source-dispatch:x:refine:1",
            attempt_count=1,
            lease_token="tok",
        )
        db = _FakeDb(
            results=[
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_generation=1,
                        delete_requested_at=datetime.now(timezone.utc),
                    )
                ),
            ]
        )
        with self.assertRaises(dispatch.SourceDispatchSuperseded):
            await dispatch.fence_source_dispatch(
                cast(AsyncSession, cast(object, db)), claim, source_id=source_id
            )

    async def test_fence_passes_when_execution_is_current(self) -> None:
        source_id = uuid.uuid4()
        claim = dispatch.SourceDispatchClaim(
            dispatch_id=uuid.uuid4(),
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_REFINE,
            task_name="ingest_refine_task",
            task_args=(),
            job_id="source-dispatch:x:refine:1",
            attempt_count=1,
            lease_token="tok",
        )
        db = _FakeDb(
            results=[
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_generation=1, delete_requested_at=None
                    )
                ),
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_status=dispatch.DISPATCH_STATUS_RUNNING,
                        lease_token="tok",
                        lease_expires_at=datetime.now(timezone.utc)
                        + timedelta(seconds=60),
                    )
                ),
            ]
        )
        # No exception means the fence passed.
        await dispatch.fence_source_dispatch(
            cast(AsyncSession, cast(object, db)), claim, source_id=source_id
        )

    async def test_fence_raises_when_lease_token_changed(self) -> None:
        source_id = uuid.uuid4()
        claim = dispatch.SourceDispatchClaim(
            dispatch_id=uuid.uuid4(),
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_REFINE,
            task_name="ingest_refine_task",
            task_args=(),
            job_id="source-dispatch:x:refine:1",
            attempt_count=1,
            lease_token="original-token",
        )
        db = _FakeDb(
            results=[
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_generation=1, delete_requested_at=None
                    )
                ),
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_status=dispatch.DISPATCH_STATUS_RUNNING,
                        # Another worker took the lease over with a new token.
                        lease_token="other-worker-token",
                        lease_expires_at=datetime.now(timezone.utc)
                        + timedelta(seconds=60),
                    )
                ),
            ]
        )
        with self.assertRaises(dispatch.SourceDispatchSuperseded):
            await dispatch.fence_source_dispatch(
                cast(AsyncSession, cast(object, db)), claim, source_id=source_id
            )

    async def test_fence_raises_when_lease_expired(self) -> None:
        source_id = uuid.uuid4()
        claim = dispatch.SourceDispatchClaim(
            dispatch_id=uuid.uuid4(),
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_REFINE,
            task_name="ingest_refine_task",
            task_args=(),
            job_id="source-dispatch:x:refine:1",
            attempt_count=1,
            lease_token="tok",
        )
        db = _FakeDb(
            results=[
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_generation=1, delete_requested_at=None
                    )
                ),
                _Result(
                    scalar=SimpleNamespace(
                        dispatch_status=dispatch.DISPATCH_STATUS_RUNNING,
                        lease_token="tok",
                        # Renewal stopped (worker crashed): lease already lapsed.
                        lease_expires_at=datetime.now(timezone.utc)
                        - timedelta(seconds=1),
                    )
                ),
            ]
        )
        with self.assertRaises(dispatch.SourceDispatchSuperseded):
            await dispatch.fence_source_dispatch(
                cast(AsyncSession, cast(object, db)), claim, source_id=source_id
            )

    async def test_fence_is_noop_without_claim(self) -> None:
        # Legacy executions without a recorded cycle must not be fenced.
        await dispatch.fence_source_dispatch(
            cast(AsyncSession, cast(object, _FakeDb())), None, source_id=uuid.uuid4()
        )


class LeaseRenewalTests(unittest.IsolatedAsyncioTestCase):
    def _claim(self, row: SourceDispatchExecution) -> dispatch.SourceDispatchClaim:
        return dispatch.SourceDispatchClaim(
            dispatch_id=row.id,
            source_id=row.source_id,
            generation=row.generation,
            stage=row.stage,
            task_name=row.task_name,
            task_args=tuple(row.task_args or ()),
            job_id=row.job_id,
            attempt_count=1,
            lease_token="tok",
        )

    async def test_renewal_extends_lease_with_same_token(self) -> None:
        import asyncio

        source_id = uuid.uuid4()
        row = _execution(
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_RUNNING,
        )
        row.lease_token = "tok"
        row.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        claim = self._claim(row)
        source_state = SimpleNamespace(dispatch_generation=1, delete_requested_at=None)
        db = _FakeDb(
            get_row=row,
            results=[_Result(scalar=source_state)],
        )
        factory = _FakeFactory(db)

        renewal = await dispatch.start_dispatch_lease_renewal(
            factory, claim, renew_interval_seconds=0.01, ttl_seconds=60
        )
        try:
            before = row.lease_expires_at
            await asyncio.sleep(0.05)
            self.assertGreater(row.lease_expires_at, before)
            self.assertEqual(row.lease_token, "tok")
        finally:
            renewal.cancel()
            await asyncio.sleep(0)

    async def test_renewal_stops_on_token_loss(self) -> None:
        import asyncio

        source_id = uuid.uuid4()
        row = _execution(
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_RUNNING,
        )
        row.lease_token = "tok"
        row.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        claim = self._claim(row)
        source_state = SimpleNamespace(dispatch_generation=1, delete_requested_at=None)
        db = _FakeDb(
            get_row=row,
            results=[_Result(scalar=source_state)],
        )
        factory = _FakeFactory(db)

        renewal = await dispatch.start_dispatch_lease_renewal(
            factory, claim, renew_interval_seconds=0.01, ttl_seconds=60
        )
        try:
            await asyncio.sleep(0.05)
            self.assertGreater(
                row.lease_expires_at,
                datetime.now(timezone.utc) + timedelta(seconds=55),
            )
            # Another worker takes the lease over: the renewal now reads a row
            # with a different lease token and must stop renewing.
            takeover_row = _execution(
                source_id=source_id,
                generation=1,
                stage=dispatch.DISPATCH_STAGE_INGEST,
                status=dispatch.DISPATCH_STATUS_RUNNING,
            )
            takeover_row.lease_token = "other-worker-token"
            db.get_row = takeover_row
            await asyncio.sleep(0.05)
            first_snapshot = row.lease_expires_at
            await asyncio.sleep(0.05)
            # No further renewals land on the original row after the takeover.
            self.assertEqual(row.lease_expires_at, first_snapshot)
        finally:
            renewal.cancel()
            await asyncio.sleep(0)


class EnqueueReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_failure_keeps_row_pending_with_backoff_then_exhausts(
        self,
    ) -> None:
        source_id = uuid.uuid4()
        row = _execution(source_id=source_id, generation=1)
        pool = SimpleNamespace(
            enqueue_job=AsyncMock(side_effect=RuntimeError("redis down"))
        )
        db = _FakeDb()
        ok = await dispatch.enqueue_dispatch_execution(
            cast(AsyncSession, cast(object, db)), row, pool=pool
        )
        self.assertFalse(ok)
        self.assertEqual(row.dispatch_status, dispatch.DISPATCH_STATUS_PENDING)
        self.assertEqual(row.attempt_count, 1)
        self.assertIsNotNone(row.next_attempt_at)
        self.assertIn("redis down", row.last_error or "")

        for _ in range(dispatch.MAX_DISPATCH_ENQUEUE_ATTEMPTS - 1):
            await dispatch.enqueue_dispatch_execution(
                cast(AsyncSession, cast(object, db)), row, pool=pool
            )
        self.assertEqual(row.dispatch_status, dispatch.DISPATCH_STATUS_FAILED)
        self.assertEqual(row.terminal_reason, "enqueue_retry_exhausted")

    async def test_enqueue_acknowledges_duplicate_job(self) -> None:
        source_id = uuid.uuid4()
        row = _execution(
            source_id=source_id,
            generation=1,
            status=dispatch.DISPATCH_STATUS_DISPATCHING,
            attempt_count=1,
        )
        pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=None))
        ok = await dispatch.enqueue_dispatch_execution(
            cast(AsyncSession, cast(object, _FakeDb())), row, pool=pool
        )
        self.assertTrue(ok)
        self.assertEqual(row.dispatch_status, dispatch.DISPATCH_STATUS_ENQUEUED)
        self.assertIsNotNone(row.enqueued_at)
        self.assertIsNotNone(row.lease_expires_at)

    async def test_enqueue_replay_prefers_persisted_trace_over_ambient_context(
        self,
    ) -> None:
        from cygnus.observability import request_correlation
        from cygnus.observability._context import traceparent_for

        source_id = uuid.uuid4()
        persisted_correlation = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        row = _execution(
            source_id=source_id,
            generation=1,
            status=dispatch.DISPATCH_STATUS_DISPATCHING,
        )
        row.correlation_id = persisted_correlation
        row.traceparent = traceparent_for(str(persisted_correlation))
        pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=None))

        with request_correlation("3fa85f64-5717-4562-b3fc-2c963f66afa6"):
            ok = await dispatch.enqueue_dispatch_execution(
                cast(AsyncSession, cast(object, _FakeDb())), row, pool=pool
            )

        self.assertTrue(ok)
        pool.enqueue_job.assert_awaited_once_with(
            "ingest_file_task",
            "src",
            _job_id=row.job_id,
            _cygnus_correlation_id=str(persisted_correlation),
            _cygnus_traceparent=traceparent_for(str(persisted_correlation)),
        )

    async def test_sweep_reconciles_expired_lease_and_acknowledges_duplicate(
        self,
    ) -> None:
        source_id = uuid.uuid4()
        row = _execution(
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_ENQUEUED,
        )
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        source_state = SimpleNamespace(dispatch_generation=1, delete_requested_at=None)
        claim_db = _FakeDb(
            results=[
                _Result(rows=[]),  # superseded-generation update
                _Result(rows=[]),  # orphaned-running update
                _Result(rows=[row]),  # due-execution select
            ],
            get_row=row,
        )
        ack_db = _FakeDb(
            results=[_Result(scalar=source_state)],
            get_row=row,
        )
        factory = _FakeFactory(claim_db, ack_db)
        pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=None))

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=factory,
            ),
            patch(
                "cygnus.runtime.worker.get_arq_pool",
                AsyncMock(return_value=pool),
            ),
        ):
            count = await dispatch.sweep_source_dispatches(limit=10)

        self.assertEqual(count, 1)
        self.assertEqual(row.dispatch_status, dispatch.DISPATCH_STATUS_ENQUEUED)
        self.assertEqual(row.attempt_count, 1)
        pool.enqueue_job.assert_awaited_once_with(
            "ingest_file_task", "src", _job_id=row.job_id
        )

    async def test_sweep_enqueue_failure_stays_pending_for_retry(self) -> None:
        source_id = uuid.uuid4()
        row = _execution(
            source_id=source_id,
            generation=1,
            stage=dispatch.DISPATCH_STAGE_INGEST,
            status=dispatch.DISPATCH_STATUS_ENQUEUED,
        )
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        source_state = SimpleNamespace(dispatch_generation=1, delete_requested_at=None)
        claim_db = _FakeDb(
            results=[
                _Result(rows=[]),
                _Result(rows=[]),
                _Result(rows=[row]),
            ],
            get_row=row,
        )
        failure_db = _FakeDb(
            results=[_Result(scalar=source_state)],
            get_row=row,
        )
        factory = _FakeFactory(claim_db, failure_db)
        pool = SimpleNamespace(
            enqueue_job=AsyncMock(side_effect=RuntimeError("redis down"))
        )

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=factory,
            ),
            patch(
                "cygnus.runtime.worker.get_arq_pool",
                AsyncMock(return_value=pool),
            ),
        ):
            count = await dispatch.sweep_source_dispatches(limit=10)

        self.assertEqual(count, 1)
        self.assertEqual(row.dispatch_status, dispatch.DISPATCH_STATUS_PENDING)
        self.assertIsNotNone(row.next_attempt_at)
        self.assertIn("redis down", row.last_error or "")


if __name__ == "__main__":
    unittest.main()
