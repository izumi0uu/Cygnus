from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Protocol, cast
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import WikiPageDraft


class _DraftFixture(Protocol):
    """Structural shape of the SimpleNamespace draft double."""

    id: uuid.UUID
    status: str
    version: int
    revision_round: int
    ai_check_status: str
    ai_check_results: dict[str, object] | None
    ai_checked_at: datetime | None


class _DispatchRowFixture(Protocol):
    """Structural shape of the SimpleNamespace outbox-row double."""

    id: uuid.UUID
    draft_id: uuid.UUID
    draft_version: int
    revision_round: int
    job_id: str
    dispatch_status: str
    attempt_count: int
    last_error: str | None
    terminal_reason: str | None
    next_attempt_at: datetime | None
    lease_expires_at: datetime | None
    enqueued_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class _Result:
    def __init__(self, values: Sequence[object]):
        self._values = list(values)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return list(self._values)

    def scalar_one_or_none(self) -> object | None:
        return self._values[0] if self._values else None


class _SessionScope:
    def __init__(self, session: object):
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _SessionFactory:
    def __init__(self, session: object):
        self._session = session

    def __call__(self) -> _SessionScope:
        return _SessionScope(self._session)


class _DispatchSession:
    """Small transaction-aware session double for the outbox state machine."""

    def __init__(
        self,
        records: list[_DispatchRowFixture],
        drafts: dict[uuid.UUID, _DraftFixture],
    ):
        self.records = records
        self.drafts = drafts
        self.statements: list[object] = []
        self.commit_count = 0

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(self.records)
        return _Result(self.records[:1])

    async def get(
        self, _model: object, identifier: uuid.UUID, **_kwargs
    ) -> _DraftFixture | _DispatchRowFixture | None:
        draft = self.drafts.get(identifier)
        if draft is not None:
            return draft
        return next(
            (record for record in self.records if record.id == identifier),
            None,
        )

    async def commit(self) -> None:
        self.commit_count += 1


class _LifecycleSession:
    def __init__(self) -> None:
        self.intent_count = 0
        self.committed = False

    async def execute(self, _statement: object) -> None:
        self.intent_count += 1

    async def rollback(self) -> None:
        self.intent_count = 0


def _draft(
    *,
    draft_id: uuid.UUID | None = None,
    version: int = 1,
    revision_round: int = 0,
    ai_check_status: str = "pending",
) -> _DraftFixture:
    return SimpleNamespace(
        id=draft_id or uuid.uuid4(),
        status="pending",
        version=version,
        revision_round=revision_round,
        ai_check_status=ai_check_status,
        ai_check_results=None,
        ai_checked_at=None,
    )


def _dispatch_row(
    dispatch_module,
    draft: _DraftFixture,
    *,
    status: str = "pending",
    attempt_count: int = 0,
    lease_expires_at: datetime | None = None,
) -> _DispatchRowFixture:
    staged = dispatch_module.PendingAiPreReview(
        draft_id=draft.id,
        draft_version=draft.version,
        revision_round=draft.revision_round,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        draft_id=staged.draft_id,
        draft_version=staged.draft_version,
        revision_round=staged.revision_round,
        job_id=dispatch_module.ai_pre_review_job_id(staged),
        dispatch_status=status,
        attempt_count=attempt_count,
        last_error=None,
        terminal_reason=None,
        next_attempt_at=None,
        lease_expires_at=lease_expires_at,
        enqueued_at=None,
        completed_at=None,
        created_at=datetime.now(timezone.utc),
    )


class CommittedAiPreReviewDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_rollback_leaves_no_outbox_intent(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft(version=4, revision_round=2)
        session = _LifecycleSession()
        await dispatch.stage_ai_pre_review(
            cast(AsyncSession, session),
            cast(WikiPageDraft, draft),
        )

        # The stage operation never commits; the lifecycle owner controls the
        # same transaction as the draft and can roll it back atomically.
        self.assertEqual(session.intent_count, 1)
        await session.rollback()
        self.assertEqual(session.intent_count, 0)

    async def test_crash_before_enqueue_is_recovered_by_sweep(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft(version=4, revision_round=2)
        row = _dispatch_row(dispatch, draft)
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=object()))

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
            patch.object(
                dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=True)
            ),
        ):
            leased = await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(leased, 1)
        self.assertEqual(draft.ai_check_status, "queued")
        self.assertEqual(row.dispatch_status, "enqueued")
        pool.enqueue_job.assert_awaited_once_with(
            "ai_pre_review_draft_task",
            str(draft.id),
            2,
            4,
            _job_id=row.job_id,
        )

    async def test_enqueue_then_crash_replays_same_job_id_without_duplicate_work(
        self,
    ) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft(version=3, revision_round=1)
        row = _dispatch_row(dispatch, draft)
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(enqueue_job=AsyncMock(side_effect=[object(), None]))

        with patch.object(
            dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=True)
        ):
            claims = await dispatch._claim_due_dispatches(
                cast(AsyncSession, session),
                limit=10,
            )
        self.assertEqual(len(claims), 1)

        # Redis accepted the first call, then the dispatcher died before its
        # acknowledgement commit.  The lease expiry makes the row recoverable.
        await pool.enqueue_job(
            "ai_pre_review_draft_task",
            str(draft.id),
            1,
            3,
            _job_id=row.job_id,
        )
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
            patch.object(
                dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=True)
            ),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "enqueued")
        self.assertEqual(
            pool.enqueue_job.await_args_list[0].kwargs["_job_id"], row.job_id
        )
        self.assertEqual(
            pool.enqueue_job.await_args_list[1].kwargs["_job_id"], row.job_id
        )

    async def test_deterministic_job_id_includes_revision_identity(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft_id = uuid.uuid4()
        staged = dispatch.PendingAiPreReview(draft_id, 7, 4)
        self.assertEqual(
            dispatch.ai_pre_review_job_id(staged),
            f"ai-pre-review:{draft_id}:7:4",
        )
        self.assertNotEqual(
            dispatch.ai_pre_review_job_id(staged),
            dispatch.ai_pre_review_job_id(dispatch.PendingAiPreReview(draft_id, 8, 4)),
        )

    async def test_stale_revision_is_terminally_suppressed(self) -> None:
        from cygnus.review.pre_review import dispatch

        staged_draft = _draft(version=1, revision_round=0)
        current_draft = _draft(
            draft_id=staged_draft.id,
            version=2,
            revision_round=1,
        )
        row = _dispatch_row(dispatch, staged_draft)
        session = _DispatchSession([row], {current_draft.id: current_draft})
        pool = SimpleNamespace(enqueue_job=AsyncMock())

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "stale")
        self.assertEqual(row.terminal_reason, "stale_or_superseded")
        pool.enqueue_job.assert_not_awaited()

    async def test_terminal_draft_clears_its_orphaned_queue_marker(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft(ai_check_status="queued")
        draft.status = "withdrawn"
        row = _dispatch_row(dispatch, draft)
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(enqueue_job=AsyncMock())

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "stale")
        self.assertEqual(draft.ai_check_status, "skipped")
        pool.enqueue_job.assert_not_awaited()

    async def test_disabled_config_is_persisted_without_enqueue(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft()
        row = _dispatch_row(dispatch, draft)
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(enqueue_job=AsyncMock())

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
            patch.object(
                dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=False)
            ),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "disabled")
        self.assertEqual(row.terminal_reason, "config_disabled")
        self.assertEqual(draft.ai_check_status, "skipped")
        pool.enqueue_job.assert_not_awaited()

    async def test_enqueue_failure_retries_with_backoff(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft()
        row = _dispatch_row(dispatch, draft)
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(
            enqueue_job=AsyncMock(side_effect=RuntimeError("redis unavailable"))
        )

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
            patch.object(
                dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=True)
            ),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "pending")
        self.assertEqual(row.last_error, "redis unavailable")
        self.assertIsNotNone(row.next_attempt_at)
        self.assertEqual(draft.ai_check_status, "queued")

    async def test_enqueue_failure_exhausts_budget_with_terminal_reason(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft()
        row = _dispatch_row(
            dispatch,
            draft,
            attempt_count=dispatch.MAX_AI_PRE_REVIEW_ENQUEUE_ATTEMPTS - 1,
        )
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(
            enqueue_job=AsyncMock(side_effect=RuntimeError("redis unavailable"))
        )

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
            patch.object(
                dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=True)
            ),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "failed")
        self.assertEqual(row.terminal_reason, "enqueue_retry_exhausted")
        self.assertEqual(draft.ai_check_status, "skipped")
        self.assertIsNone(row.next_attempt_at)

    async def test_successful_enqueue_acknowledges_outbox(self) -> None:
        from cygnus.review.pre_review import dispatch

        draft = _draft(version=5, revision_round=2)
        row = _dispatch_row(dispatch, draft)
        session = _DispatchSession([row], {draft.id: draft})
        pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=object()))

        with (
            patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=_SessionFactory(session),
            ),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=pool)),
            patch.object(
                dispatch, "_ai_pre_review_enabled", AsyncMock(return_value=True)
            ),
        ):
            await dispatch.sweep_ai_pre_review_dispatches()

        self.assertEqual(row.dispatch_status, "enqueued")
        self.assertIsNotNone(row.enqueued_at)
        self.assertEqual(draft.ai_check_status, "queued")

    async def test_worker_rejects_job_without_matching_durable_intent(self) -> None:
        from cygnus.review.pre_review import runner

        draft = _draft(ai_check_status="queued")
        session = _DispatchSession([], {draft.id: draft})
        with patch(
            "cygnus.runtime.database.async_session_factory",
            new=_SessionFactory(session),
        ):
            await runner.run_async_checks(
                str(draft.id),
                expected_round=0,
                expected_version=1,
            )

        self.assertEqual(draft.ai_check_status, "queued")
        self.assertEqual(session.commit_count, 0)

    async def test_worker_rejects_job_without_durable_revision_identity(self) -> None:
        from cygnus.review.pre_review import runner

        draft = _draft(ai_check_status="queued")
        session = _DispatchSession([], {draft.id: draft})

        with patch(
            "cygnus.runtime.database.async_session_factory",
            new=_SessionFactory(session),
        ):
            await runner.run_async_checks(str(draft.id))

        self.assertEqual(draft.ai_check_status, "queued")
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.statements, [])


if __name__ == "__main__":
    unittest.main()
