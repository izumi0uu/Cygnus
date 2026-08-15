"""Focused recovery tests for the database-led source deletion lifecycle.

Covers the CYG-130/CYG-128 source-lifecycle contract:

- DELETE commits tombstone + cleanup intent BEFORE any durable storage object
  is removed (deletion is database-led and recoverable),
- storage cleanup is idempotent and retried by the sweeper,
- a partial object failure stays visible on the intent row (status, last_error,
  attempt_count) instead of being swallowed,
- completed deletions survive the source row removal and stay auditable.

Drives the module with fakes (no live Postgres/MinIO), matching the project's
mock-session test conventions.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import Source, SourceDeletion
from cygnus.runtime import source_deletion as deletion


def _source(*, tombstoned: bool = False) -> Source:
    source = Source(id=uuid.uuid4(), title="t")
    source.delete_requested_at = datetime.now(timezone.utc) if tombstoned else None
    return source


def _deletion(source: Source) -> SourceDeletion:
    return SourceDeletion(
        id=uuid.uuid4(),
        source_id=source.id,
        requested_by_employee_id=None,
        storage_prefix=deletion.source_storage_prefix(source.id),
        status=deletion.SOURCE_DELETION_PENDING,
        attempt_count=0,
    )


class _FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeDb:
    """Minimal AsyncSession stand-in with per-model get and canned results."""

    def __init__(self, *, get_rows=None, results=None):
        self.get_rows = get_rows or {}
        self.results = list(results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rolled_back = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        # Canned results feed SELECT statements only. Non-select statements
        # (e.g. the dispatch-fencing UPDATE in request_source_deletion) get an
        # empty result so they never consume a canned row meant for a select.
        if getattr(stmt, "is_select", False) and self.results:
            return self.results.pop(0)
        return _FakeResult(scalar=None)

    async def get(self, model, ident, **kwargs):
        return self.get_rows.get(getattr(model, "__name__", None))

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rolled_back += 1

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)


class _FakeFactory:
    """Session factory returning queued fakes (one per ``async with``)."""

    def __init__(self, *dbs):
        self._dbs = list(dbs)

    def __call__(self):
        if self._dbs:
            return self._dbs.pop(0)
        return _FakeDb()


class SourceStoragePrefixTests(unittest.TestCase):
    def test_storage_prefix_is_scoped_to_source(self) -> None:
        source_id = uuid.uuid4()
        self.assertEqual(
            deletion.source_storage_prefix(source_id), f"sources/{source_id}/"
        )


class DeletionIntentTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_commits_tombstone_and_intent_in_one_transaction(
        self,
    ) -> None:
        source = _source()
        db = _FakeDb()
        row = await deletion.request_source_deletion(
            cast(AsyncSession, cast(object, db)), source, actor_id=uuid.uuid4()
        )
        self.assertIsNotNone(source.delete_requested_at)
        self.assertEqual(row.status, deletion.SOURCE_DELETION_PENDING)
        self.assertEqual(row.source_id, source.id)
        self.assertEqual(row.storage_prefix, f"sources/{source.id}/")
        self.assertIn(row, db.added)

    async def test_request_is_idempotent_and_reraises_failed_cleanup(self) -> None:
        source = _source()
        first = await deletion.request_source_deletion(
            cast(AsyncSession, cast(object, _FakeDb())), source
        )
        self.assertEqual(first.status, deletion.SOURCE_DELETION_PENDING)
        # A second request finds the existing intent row and reuses it.
        existing = _deletion(source)
        existing.status = deletion.SOURCE_DELETION_FAILED
        existing.last_error = "s3 down"
        db = _FakeDb(
            results=[_FakeResult(scalar=existing)],
        )
        row = await deletion.request_source_deletion(
            cast(AsyncSession, cast(object, db)), source
        )
        self.assertIs(row, existing)
        self.assertEqual(row.status, deletion.SOURCE_DELETION_PENDING)
        self.assertIsNone(row.last_error)

    async def test_retry_due_after_backoff_only(self) -> None:
        now = datetime.now(timezone.utc)
        fresh_failure = _deletion(_source())
        fresh_failure.status = deletion.SOURCE_DELETION_FAILED
        fresh_failure.updated_at = now
        self.assertFalse(deletion._is_retry_due(fresh_failure, now=now))

        old_failure = _deletion(_source())
        old_failure.status = deletion.SOURCE_DELETION_FAILED
        old_failure.updated_at = (
            now - deletion.SOURCE_DELETION_BACKOFF - timedelta(minutes=1)
        )
        self.assertTrue(deletion._is_retry_due(old_failure, now=now))


class DeletionExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_storage_failure_stays_visible_and_failed(self) -> None:
        source = _source()
        row = _deletion(source)
        claim_db = _FakeDb(
            get_rows={"SourceDeletion": row, "Source": source},
        )
        failure_db = _FakeDb(
            get_rows={"SourceDeletion": row, "Source": source},
        )
        factory = _FakeFactory(claim_db, failure_db)
        storage = SimpleNamespace(
            delete_prefix=MagicMock(
                side_effect=RuntimeError("minio endpoint unreachable")
            )
        )

        status = await deletion.process_source_deletion(
            row.id,
            storage_service=storage,
            async_session_factory=factory,
        )

        self.assertEqual(status, deletion.SOURCE_DELETION_FAILED)
        self.assertEqual(row.status, deletion.SOURCE_DELETION_FAILED)
        self.assertIn("minio endpoint unreachable", row.last_error or "")
        self.assertEqual(row.attempt_count, 1)
        # The source row must NOT be removed while storage cleanup failed.
        self.assertNotIn(source, claim_db.deleted)

    async def test_success_removes_source_row_after_storage_cleanup(self) -> None:
        source = _source()
        row = _deletion(source)
        claim_db = _FakeDb(
            get_rows={"SourceDeletion": row, "Source": source},
        )
        final_db = _FakeDb(
            get_rows={"SourceDeletion": row, "Source": source},
        )
        factory = _FakeFactory(claim_db, final_db)
        storage = SimpleNamespace(delete_prefix=MagicMock(return_value=None))

        with (
            patch(
                "cygnus.runtime.ai.mrp.pipeline._resolve_wiki_scopes",
                AsyncMock(return_value=[("global", None)]),
            ),
            patch(
                "cygnus.runtime.services.wiki_service.detach_source_from_wiki",
                AsyncMock(return_value=1),
            ),
            patch(
                "cygnus.runtime.services.wiki_service.regenerate_index",
                AsyncMock(return_value=None),
            ),
        ):
            status = await deletion.process_source_deletion(
                row.id,
                storage_service=storage,
                async_session_factory=factory,
            )

        self.assertEqual(status, deletion.SOURCE_DELETION_COMPLETED)
        self.assertEqual(row.status, deletion.SOURCE_DELETION_COMPLETED)
        self.assertIsNotNone(row.completed_at)
        # The intent survives the source removal (SET NULL keeps it auditable).
        self.assertIsNone(row.source_id)
        self.assertIn(source, final_db.deleted)
        storage.delete_prefix.assert_called_once_with(row.storage_prefix)

    async def test_sweep_processes_due_pending_intents(self) -> None:
        source = _source()
        pending = _deletion(source)
        # The sweep query selects only active statuses, so the fake returns the
        # due row exactly as the real WHERE would.
        db = _FakeDb(
            results=[
                _FakeResult(rows=[pending]),
            ]
        )

        with patch(
            "cygnus.runtime.source_deletion.process_source_deletion",
            AsyncMock(return_value=deletion.SOURCE_DELETION_COMPLETED),
        ) as process_mock:
            # Patch the session factory used by sweep_source_deletions.
            with patch(
                "cygnus.runtime.database.get_async_session_factory",
                return_value=lambda: db,
            ):
                count = await deletion.sweep_source_deletions(limit=10)

        self.assertEqual(count, 1)
        process_mock.assert_awaited_once()
        assert process_mock.await_args is not None
        self.assertIs(process_mock.await_args.args[0], pending)

    async def test_claim_sets_in_progress_with_attempt_count(self) -> None:
        source = _source()
        row = _deletion(source)
        db = _FakeDb()
        await deletion._claim_deletion(cast(AsyncSession, cast(object, db)), row)
        self.assertEqual(row.status, deletion.SOURCE_DELETION_IN_PROGRESS)
        self.assertEqual(row.attempt_count, 1)
        self.assertIsNotNone(row.started_at)


if __name__ == "__main__":
    unittest.main()
