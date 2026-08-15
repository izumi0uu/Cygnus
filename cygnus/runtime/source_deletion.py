"""Database-led source deletion: tombstone + cleanup intent, sweeper retries.

Deletion is a two-phase, recoverable operation:

1. **Intent (request path).** ``request_source_deletion`` commits the tombstone
   (``sources.delete_requested_at``) and a ``SourceDeletion`` intent row in the
   same transaction — before any durable storage object is removed. A crash at
   this point leaves an intent that the sweeper will finish; the source is
   already invisible to readers.
2. **Cleanup (worker sweep).** ``sweep_source_deletions`` claims pending/failed
   intents, deletes the storage prefix idempotently (a missing object is a
   success), then — only after storage is clean — removes the wiki links and
   the source row in one transaction and marks the intent ``completed``.

Partial object failures keep the intent row in ``failed`` with ``last_error``
and ``attempt_count`` so the problem stays visible and is retried on the next
sweep. Completed rows survive the source row removal (``source_id`` becomes
NULL via SET NULL) so the deletion is auditable afterwards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import (
    Source,
    SourceDeletion,
    SourceDispatchExecution,
)
from cygnus.runtime.source_dispatch import (
    DISPATCH_STATUS_DISPATCHING,
    DISPATCH_STATUS_ENQUEUED,
    DISPATCH_STATUS_PENDING,
    DISPATCH_STATUS_RUNNING,
    DISPATCH_STATUS_STALE,
)

SOURCE_DELETION_PENDING = "pending"
SOURCE_DELETION_IN_PROGRESS = "in_progress"
SOURCE_DELETION_COMPLETED = "completed"
SOURCE_DELETION_FAILED = "failed"

# Retry budget + backoff for storage cleanup attempts.
MAX_SOURCE_DELETION_ATTEMPTS = 10
SOURCE_DELETION_BACKOFF = timedelta(minutes=2)

_ACTIVE_STATUSES = frozenset(
    {SOURCE_DELETION_PENDING, SOURCE_DELETION_IN_PROGRESS, SOURCE_DELETION_FAILED}
)


def source_storage_prefix(source_id: uuid.UUID | str) -> str:
    """The object-storage prefix owned by one source."""
    return f"sources/{source_id}/"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def request_source_deletion(
    db: AsyncSession,
    source: Source,
    *,
    actor_id: Optional[uuid.UUID | str] = None,
) -> SourceDeletion:
    """Commit tombstone + cleanup intent in one transaction (DB-led delete).

    Idempotent: a second request reuses the existing intent row and never
    downgrades a row that is already being cleaned up.
    """
    now = _now()
    source.delete_requested_at = source.delete_requested_at or now

    # Fence every in-flight dispatch execution in the same transaction: a
    # worker for a tombstoned source must never commit progress or pages in
    # the window before the sweeper removes the row.
    await db.execute(
        update(SourceDispatchExecution)
        .where(
            SourceDispatchExecution.source_id == source.id,
            SourceDispatchExecution.dispatch_status.in_(
                (
                    DISPATCH_STATUS_PENDING,
                    DISPATCH_STATUS_DISPATCHING,
                    DISPATCH_STATUS_ENQUEUED,
                    DISPATCH_STATUS_RUNNING,
                )
            ),
        )
        .values(
            dispatch_status=DISPATCH_STATUS_STALE,
            terminal_reason="source_deleted",
            last_error="source deletion tombstone committed; execution fenced",
            completed_at=now,
            lease_expires_at=None,
            next_attempt_at=None,
        )
    )

    row = (
        await db.execute(
            select(SourceDeletion).where(SourceDeletion.source_id == source.id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = SourceDeletion(
            id=uuid.uuid4(),
            source_id=source.id,
            requested_by_employee_id=(uuid.UUID(str(actor_id)) if actor_id else None),
            storage_prefix=source_storage_prefix(source.id),
            status=SOURCE_DELETION_PENDING,
            attempt_count=0,
        )
        db.add(row)
    elif row.status == SOURCE_DELETION_FAILED:
        # A previously failed cleanup gets another chance on request replay.
        row.status = SOURCE_DELETION_PENDING
        row.last_error = None
    return row


async def _claim_deletion(
    db: AsyncSession,
    row: SourceDeletion,
) -> None:
    now = _now()
    row.status = SOURCE_DELETION_IN_PROGRESS
    row.attempt_count = (row.attempt_count or 0) + 1
    row.started_at = row.started_at or now
    row.last_error = None


def _is_retry_due(row: SourceDeletion, *, now: datetime) -> bool:
    if row.status == SOURCE_DELETION_FAILED:
        # Back off after the last attempt; updated_at is bumped by the failure.
        return (row.updated_at or row.requested_at) + SOURCE_DELETION_BACKOFF <= now
    return True


async def _remove_source_rows(
    db: AsyncSession,
    deletion: SourceDeletion,
    source: Source,
) -> None:
    """Detach wiki pages and delete the source row in the caller's transaction.

    Storage cleanup has already succeeded at this point (or is idempotently
    complete), so removing the row is the terminal DB step. FK cascades remove
    SourceDepartment, SourceImage, SourceCompilationPlan, chunk rows and
    dispatch executions; the deletion intent survives via SET NULL.
    """
    from cygnus.runtime.services import wiki_service

    # Snapshot old scopes before detaching so their indexes can be rebuilt.
    old_scopes: list[tuple[str, Optional[uuid.UUID]]] = [("global", None)]
    try:
        from cygnus.runtime.ai.mrp.pipeline import _resolve_wiki_scopes

        old_scopes = await _resolve_wiki_scopes(db, source)
    except Exception as exc:
        logger.warning(
            "source_deletion: scope resolution failed for {} ({}); using global",
            source.id,
            exc,
        )

    deleted_pages = await wiki_service.detach_source_from_wiki(db, source.id)
    for scope_type, scope_id in old_scopes:
        try:
            await wiki_service.regenerate_index(
                db, scope_type=scope_type, scope_id=scope_id
            )
        except Exception as exc:
            logger.warning(
                "source_deletion: index regeneration failed for {} scope={}: {}",
                source.id,
                scope_type,
                exc,
            )

    await db.delete(source)
    deletion.source_id = None
    deletion.status = SOURCE_DELETION_COMPLETED
    deletion.completed_at = _now()
    deletion.last_error = None
    if deleted_pages:
        logger.info(
            "source_deletion: removed {} single-source page(s) for {}",
            deleted_pages,
            source.id,
        )


async def process_source_deletion(
    row_or_id: SourceDeletion | uuid.UUID | str,
    *,
    storage_service: Any = None,
    async_session_factory: Any = None,
) -> str:
    """Run one deletion to completion (or record a structured failure).

    Used by both the worker sweep and the best-effort request-path attempt.
    Returns the intent row's terminal status: completed or failed.
    """
    if async_session_factory is None:
        from cygnus.runtime.database import get_async_session_factory

        async_session_factory = get_async_session_factory()
    if storage_service is None:
        from cygnus.runtime.services.storage_service import storage_service

    async with async_session_factory() as db:
        if isinstance(row_or_id, SourceDeletion):
            row = row_or_id
        else:
            row = await db.get(SourceDeletion, uuid.UUID(str(row_or_id)))
        if row is None:
            return SOURCE_DELETION_COMPLETED
        row = await db.get(
            SourceDeletion, row.id, with_for_update=True, populate_existing=True
        )
        if row is None:
            return SOURCE_DELETION_COMPLETED
        if row.status == SOURCE_DELETION_COMPLETED:
            return SOURCE_DELETION_COMPLETED
        if row.source_id is None:
            # Source already gone; nothing left to clean.
            row.status = SOURCE_DELETION_COMPLETED
            row.completed_at = row.completed_at or _now()
            await db.commit()
            return SOURCE_DELETION_COMPLETED
        await _claim_deletion(db, row)
        await db.commit()

    # Step 1: durable storage cleanup (idempotent; outside any DB transaction).
    try:
        storage_service.delete_prefix(row.storage_prefix)
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:900]}"
        async with async_session_factory() as db:
            current = await db.get(
                SourceDeletion, row.id, with_for_update=True, populate_existing=True
            )
            if current is None or current.status == SOURCE_DELETION_COMPLETED:
                return SOURCE_DELETION_COMPLETED
            current.status = SOURCE_DELETION_FAILED
            current.last_error = error
            if (current.attempt_count or 0) >= MAX_SOURCE_DELETION_ATTEMPTS:
                current.last_error = (
                    f"{error} — retry budget exhausted "
                    f"({MAX_SOURCE_DELETION_ATTEMPTS} attempts)"
                )
            await db.commit()
        logger.warning(
            "source_deletion: storage cleanup failed for {}: {}",
            row.source_id,
            error,
        )
        return SOURCE_DELETION_FAILED

    # Step 2: terminal DB removal (same transaction as the completion mark).
    async with async_session_factory() as db:
        current = await db.get(
            SourceDeletion, row.id, with_for_update=True, populate_existing=True
        )
        if current is None:
            return SOURCE_DELETION_COMPLETED
        if current.status == SOURCE_DELETION_COMPLETED:
            return SOURCE_DELETION_COMPLETED
        if current.source_id is None:
            current.status = SOURCE_DELETION_COMPLETED
            current.completed_at = current.completed_at or _now()
            await db.commit()
            return SOURCE_DELETION_COMPLETED
        source = await db.get(Source, current.source_id, with_for_update=True)
        if source is None:
            current.status = SOURCE_DELETION_COMPLETED
            current.completed_at = _now()
            current.source_id = None
            await db.commit()
            return SOURCE_DELETION_COMPLETED
        try:
            await _remove_source_rows(db, current, source)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            error = f"{type(exc).__name__}: {str(exc)[:900]}"
            async with async_session_factory() as db2:
                retry = await db2.get(
                    SourceDeletion,
                    current.id,
                    with_for_update=True,
                    populate_existing=True,
                )
                if retry is not None and retry.status != SOURCE_DELETION_COMPLETED:
                    retry.status = SOURCE_DELETION_FAILED
                    retry.last_error = error
                    await db2.commit()
            logger.warning(
                "source_deletion: DB removal failed for {}: {}",
                current.source_id,
                error,
            )
            return SOURCE_DELETION_FAILED
    logger.success(
        "source_deletion: source {} cleaned (prefix {})",
        row.source_id,
        row.storage_prefix,
    )
    return SOURCE_DELETION_COMPLETED


async def sweep_source_deletions(*, limit: int = 25) -> int:
    """Drive every due deletion intent; returns the number processed."""
    if limit < 1:
        raise ValueError("limit must be positive")

    from cygnus.runtime.database import get_async_session_factory

    async_session_factory = get_async_session_factory()
    now = _now()
    async with async_session_factory() as db:
        rows = list(
            (
                await db.execute(
                    select(SourceDeletion)
                    .where(
                        SourceDeletion.status.in_(tuple(_ACTIVE_STATUSES)),
                        SourceDeletion.source_id.isnot(None),
                    )
                    .order_by(SourceDeletion.requested_at, SourceDeletion.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        due = [row for row in rows if _is_retry_due(row, now=now)]
    processed = 0
    for row in due:
        await process_source_deletion(row, async_session_factory=async_session_factory)
        processed += 1
    return processed
