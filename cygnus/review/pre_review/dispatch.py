"""Durable ARQ dispatch for governed Wiki draft pre-review.

The lifecycle transaction writes one outbox row for each exact draft revision.
Dispatchers may run after a request, at worker startup, or from the worker cron;
they only ever read committed rows.  A deterministic ARQ job ID makes replaying
an unacknowledged enqueue safe across every process-death window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

from loguru import logger
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import (
    WikiDraftAiPreReviewDispatch,
    WikiPageDraft,
)


AI_PRE_REVIEW_DISPATCH_PENDING = "pending"
AI_PRE_REVIEW_DISPATCH_DISPATCHING = "dispatching"
AI_PRE_REVIEW_DISPATCH_ENQUEUED = "enqueued"
AI_PRE_REVIEW_DISPATCH_RUNNING = "running"
AI_PRE_REVIEW_DISPATCH_COMPLETED = "completed"
AI_PRE_REVIEW_DISPATCH_DISABLED = "disabled"
AI_PRE_REVIEW_DISPATCH_STALE = "stale"
AI_PRE_REVIEW_DISPATCH_FAILED = "failed"

_FINAL_DRAFT_AI_STATUSES = frozenset({"passed", "warned", "failed", "skipped"})

# An ambiguous network failure is retried with the same ARQ ID.  Only a known
# enqueue exception exhausts this budget; a deterministic ARQ duplicate is a
# successful acknowledgement because ARQ documents ``None`` as "job exists".
MAX_AI_PRE_REVIEW_ENQUEUE_ATTEMPTS = 3
DISPATCH_LEASE_SECONDS = 60
ENQUEUED_RECOVERY_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PendingAiPreReview:
    """The immutable identity of one draft content revision."""

    draft_id: uuid.UUID
    draft_version: int
    revision_round: int


@dataclass(frozen=True, slots=True)
class AiPreReviewDispatchClaim:
    """A persisted enqueue lease that may safely be replayed."""

    dispatch_id: uuid.UUID
    staged: PendingAiPreReview
    job_id: str
    attempt_count: int


def ai_pre_review_job_id(staged: PendingAiPreReview) -> str:
    """Return the single ARQ identity permitted for one draft revision."""
    return (
        "ai-pre-review:"
        f"{staged.draft_id}:{staged.draft_version}:{staged.revision_round}"
    )


async def stage_ai_pre_review(db: AsyncSession, draft: WikiPageDraft) -> None:
    """Write a transaction-bound outbox intent for a pending draft revision.

    The PostgreSQL uniqueness constraint makes repeated review requests an
    idempotent replay.  Because this INSERT uses the lifecycle session, a
    rollback removes the intent with the draft/ledger/notification truth.
    """
    if draft.status != "pending":
        return
    if draft.version < 1:
        raise ValueError("draft.version must be positive before AI review staging")

    staged = PendingAiPreReview(
        draft_id=draft.id,
        draft_version=draft.version,
        revision_round=draft.revision_round or 0,
    )
    statement = (
        pg_insert(WikiDraftAiPreReviewDispatch)
        .values(
            id=uuid.uuid4(),
            draft_id=staged.draft_id,
            draft_version=staged.draft_version,
            revision_round=staged.revision_round,
            job_id=ai_pre_review_job_id(staged),
            dispatch_status=AI_PRE_REVIEW_DISPATCH_PENDING,
            attempt_count=0,
        )
        .on_conflict_do_nothing(
            constraint="uq_wiki_draft_ai_pre_review_dispatch_revision"
        )
    )
    await db.execute(statement)


async def _ai_pre_review_enabled(db: AsyncSession) -> bool:
    """Resolve the permissive pre-review configuration from committed state."""
    try:
        from cygnus.runtime.services.config_service import ConfigService

        enabled = await ConfigService(db).get("ai_pre_review_enabled")
        return enabled is None or str(enabled).lower() != "false"
    except Exception:
        # A transient config read must not strand a committed review intent.
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _staged_from_dispatch(
    dispatch: WikiDraftAiPreReviewDispatch,
) -> PendingAiPreReview:
    return PendingAiPreReview(
        draft_id=dispatch.draft_id,
        draft_version=dispatch.draft_version,
        revision_round=dispatch.revision_round,
    )


def _matches_draft_revision(
    draft: WikiPageDraft | None,
    staged: PendingAiPreReview,
) -> bool:
    return bool(
        draft is not None
        and draft.status == "pending"
        and draft.version == staged.draft_version
        and (draft.revision_round or 0) == staged.revision_round
    )


def _matches_pending_draft(
    draft: WikiPageDraft | None,
    staged: PendingAiPreReview,
) -> bool:
    return bool(
        draft is not None
        and _matches_draft_revision(draft, staged)
        and draft.ai_check_status == "pending"
    )


def _matches_queued_draft(
    draft: WikiPageDraft | None,
    staged: PendingAiPreReview,
) -> bool:
    return bool(
        draft is not None
        and _matches_draft_revision(draft, staged)
        and draft.ai_check_status == "queued"
    )


def _has_terminal_draft_verdict(
    draft: WikiPageDraft | None,
    staged: PendingAiPreReview,
) -> bool:
    return bool(
        draft is not None
        and _matches_draft_revision(draft, staged)
        and draft.ai_check_status in _FINAL_DRAFT_AI_STATUSES
    )


def _mark_stale(
    dispatch: WikiDraftAiPreReviewDispatch,
    *,
    now: datetime,
) -> None:
    dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_STALE
    dispatch.terminal_reason = "stale_or_superseded"
    dispatch.last_error = "staged draft revision is no longer current"
    dispatch.next_attempt_at = None
    dispatch.lease_expires_at = None
    dispatch.completed_at = now


def _mark_completed(
    dispatch: WikiDraftAiPreReviewDispatch,
    *,
    now: datetime,
    reason: str,
) -> None:
    dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_COMPLETED
    dispatch.terminal_reason = reason
    dispatch.next_attempt_at = None
    dispatch.lease_expires_at = None
    dispatch.completed_at = now


def _claim_dispatch(
    dispatch: WikiDraftAiPreReviewDispatch,
    *,
    now: datetime,
) -> AiPreReviewDispatchClaim:
    """Move a due outbox row into a replay-safe ARQ delivery lease."""
    staged = _staged_from_dispatch(dispatch)
    dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_DISPATCHING
    dispatch.attempt_count = (dispatch.attempt_count or 0) + 1
    dispatch.next_attempt_at = None
    dispatch.lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    dispatch.terminal_reason = None
    return AiPreReviewDispatchClaim(
        dispatch_id=dispatch.id,
        staged=staged,
        job_id=dispatch.job_id,
        attempt_count=dispatch.attempt_count,
    )


def _dispatch_is_due(
    dispatch: WikiDraftAiPreReviewDispatch,
    *,
    now: datetime,
) -> bool:
    if dispatch.dispatch_status == AI_PRE_REVIEW_DISPATCH_PENDING:
        return dispatch.next_attempt_at is None or dispatch.next_attempt_at <= now
    if dispatch.dispatch_status in (
        AI_PRE_REVIEW_DISPATCH_DISPATCHING,
        AI_PRE_REVIEW_DISPATCH_ENQUEUED,
    ):
        return dispatch.lease_expires_at is None or dispatch.lease_expires_at <= now
    return False


def _clear_stale_queued_draft(
    draft: WikiPageDraft | None,
    staged: PendingAiPreReview,
) -> None:
    """Remove a queue marker when its exact outbox intent is terminally stale."""
    if (
        draft is not None
        and draft.version == staged.draft_version
        and (draft.revision_round or 0) == staged.revision_round
        and draft.ai_check_status == "queued"
    ):
        draft.ai_check_status = "skipped"
        draft.ai_check_results = None
        draft.ai_checked_at = None


async def _claim_due_dispatches(
    db: AsyncSession,
    *,
    limit: int,
) -> list[AiPreReviewDispatchClaim]:
    """Lease due intents after serializing against the current draft row."""
    now = _now()
    due = or_(
        and_(
            WikiDraftAiPreReviewDispatch.dispatch_status
            == AI_PRE_REVIEW_DISPATCH_PENDING,
            or_(
                WikiDraftAiPreReviewDispatch.next_attempt_at.is_(None),
                WikiDraftAiPreReviewDispatch.next_attempt_at <= now,
            ),
        ),
        and_(
            WikiDraftAiPreReviewDispatch.dispatch_status.in_(
                (
                    AI_PRE_REVIEW_DISPATCH_DISPATCHING,
                    AI_PRE_REVIEW_DISPATCH_ENQUEUED,
                )
            ),
            or_(
                WikiDraftAiPreReviewDispatch.lease_expires_at.is_(None),
                WikiDraftAiPreReviewDispatch.lease_expires_at <= now,
            ),
        ),
    )
    candidates = list(
        (
            await db.execute(
                select(WikiDraftAiPreReviewDispatch)
                .where(due)
                .order_by(
                    WikiDraftAiPreReviewDispatch.created_at,
                    WikiDraftAiPreReviewDispatch.id,
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    claims: list[AiPreReviewDispatchClaim] = []
    changed = False
    ai_pre_review_enabled: bool | None = None

    for candidate in candidates:
        staged = _staged_from_dispatch(candidate)
        # Lock in lifecycle order: draft first, then its intent.  A concurrent
        # transition cannot commit a terminal draft between this validation and
        # the queued marker written below.
        draft = await db.get(
            WikiPageDraft,
            staged.draft_id,
            with_for_update=True,
            populate_existing=True,
        )
        dispatch = await db.get(
            WikiDraftAiPreReviewDispatch,
            candidate.id,
            with_for_update=True,
            populate_existing=True,
        )
        if dispatch is None or not _dispatch_is_due(dispatch, now=now):
            continue

        if draft is not None and _has_terminal_draft_verdict(draft, staged):
            _mark_completed(
                dispatch,
                now=now,
                reason=f"draft_terminal_{draft.ai_check_status}",
            )
            changed = True
            continue

        if dispatch.dispatch_status == AI_PRE_REVIEW_DISPATCH_PENDING:
            if draft is not None and _matches_pending_draft(draft, staged):
                if ai_pre_review_enabled is None:
                    ai_pre_review_enabled = await _ai_pre_review_enabled(db)
                if not ai_pre_review_enabled:
                    draft.ai_check_status = "skipped"
                    draft.ai_check_results = None
                    draft.ai_checked_at = None
                    dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_DISABLED
                    dispatch.terminal_reason = "config_disabled"
                    dispatch.last_error = None
                    dispatch.next_attempt_at = None
                    dispatch.lease_expires_at = None
                    dispatch.completed_at = now
                    changed = True
                    continue
            elif not _matches_queued_draft(draft, staged):
                _clear_stale_queued_draft(draft, staged)
                _mark_stale(dispatch, now=now)
                changed = True
                continue
        elif not _matches_queued_draft(draft, staged):
            _clear_stale_queued_draft(draft, staged)
            _mark_stale(dispatch, now=now)
            changed = True
            continue

        assert draft is not None
        if draft.ai_check_status == "pending":
            draft.ai_check_status = "queued"
            draft.ai_check_results = None
            draft.ai_checked_at = None
        claims.append(_claim_dispatch(dispatch, now=now))
        changed = True

    if changed:
        await db.commit()
    return claims


def _owns_claim(
    dispatch: WikiDraftAiPreReviewDispatch,
    claim: AiPreReviewDispatchClaim,
) -> bool:
    return bool(
        dispatch.dispatch_status == AI_PRE_REVIEW_DISPATCH_DISPATCHING
        and dispatch.attempt_count == claim.attempt_count
    )


async def _acknowledge_enqueue(
    async_session_factory,
    claim: AiPreReviewDispatchClaim,
) -> None:
    """Persist ARQ acceptance, including ARQ's deterministic duplicate result."""
    now = _now()
    async with async_session_factory() as db:
        draft = await db.get(
            WikiPageDraft,
            claim.staged.draft_id,
            with_for_update=True,
            populate_existing=True,
        )
        dispatch = await db.get(
            WikiDraftAiPreReviewDispatch,
            claim.dispatch_id,
            with_for_update=True,
            populate_existing=True,
        )
        if dispatch is None or not _owns_claim(dispatch, claim):
            return
        if _has_terminal_draft_verdict(draft, claim.staged):
            _mark_completed(
                dispatch,
                now=now,
                reason=f"draft_terminal_{draft.ai_check_status}",
            )
        elif _matches_queued_draft(draft, claim.staged):
            dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_ENQUEUED
            dispatch.enqueued_at = dispatch.enqueued_at or now
            dispatch.lease_expires_at = now + timedelta(
                seconds=ENQUEUED_RECOVERY_SECONDS
            )
            dispatch.next_attempt_at = None
            dispatch.last_error = None
            dispatch.terminal_reason = None
        else:
            _clear_stale_queued_draft(draft, claim.staged)
            _mark_stale(dispatch, now=now)
        await db.commit()


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(30 * (2 ** max(attempt_count - 1, 0)), 300))


async def _record_enqueue_failure(
    async_session_factory,
    claim: AiPreReviewDispatchClaim,
    exc: Exception,
) -> None:
    """Retry a known queue failure or terminally resolve the draft after budget."""
    now = _now()
    error = str(exc)[:1000] or type(exc).__name__
    async with async_session_factory() as db:
        draft = await db.get(
            WikiPageDraft,
            claim.staged.draft_id,
            with_for_update=True,
            populate_existing=True,
        )
        dispatch = await db.get(
            WikiDraftAiPreReviewDispatch,
            claim.dispatch_id,
            with_for_update=True,
            populate_existing=True,
        )
        if dispatch is None or not _owns_claim(dispatch, claim):
            return
        if _has_terminal_draft_verdict(draft, claim.staged):
            _mark_completed(
                dispatch,
                now=now,
                reason=f"draft_terminal_{draft.ai_check_status}",
            )
        elif not _matches_queued_draft(draft, claim.staged):
            _clear_stale_queued_draft(draft, claim.staged)
            _mark_stale(dispatch, now=now)
        elif claim.attempt_count >= MAX_AI_PRE_REVIEW_ENQUEUE_ATTEMPTS:
            dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_FAILED
            dispatch.terminal_reason = "enqueue_retry_exhausted"
            dispatch.last_error = error
            dispatch.next_attempt_at = None
            dispatch.lease_expires_at = None
            dispatch.completed_at = now
            draft.ai_check_status = "skipped"
            draft.ai_check_results = None
            draft.ai_checked_at = None
        else:
            dispatch.dispatch_status = AI_PRE_REVIEW_DISPATCH_PENDING
            dispatch.last_error = error
            dispatch.next_attempt_at = now + _retry_delay(claim.attempt_count)
            dispatch.lease_expires_at = None
            dispatch.terminal_reason = None
        await db.commit()


async def _enqueue_claim(
    async_session_factory,
    pool,
    claim: AiPreReviewDispatchClaim,
) -> None:
    try:
        job = await pool.enqueue_job(
            "ai_pre_review_draft_task",
            str(claim.staged.draft_id),
            claim.staged.revision_round,
            claim.staged.draft_version,
            _job_id=claim.job_id,
        )
        if job is None:
            logger.info(
                "AI pre-review job {} already exists; acknowledging durable replay",
                claim.job_id,
            )
    except Exception as exc:
        logger.warning(
            "AI pre-review enqueue failed for draft {} revision {} (attempt {}): {}",
            claim.staged.draft_id,
            claim.staged.draft_version,
            claim.attempt_count,
            exc,
        )
        await _record_enqueue_failure(async_session_factory, claim, exc)
        return
    await _acknowledge_enqueue(async_session_factory, claim)


async def sweep_ai_pre_review_dispatches(*, limit: int = 100) -> int:
    """Recover every due committed pre-review intent without an HTTP request."""
    if limit < 1:
        raise ValueError("limit must be positive")

    from cygnus.runtime.database import get_async_session_factory
    from cygnus.runtime.worker import get_arq_pool

    async_session_factory = get_async_session_factory()
    async with async_session_factory() as db:
        claims = await _claim_due_dispatches(db, limit=limit)
    if not claims:
        return 0

    try:
        pool = await get_arq_pool()
    except Exception as exc:
        logger.warning("AI pre-review ARQ pool unavailable: {}", exc)
        for claim in claims:
            await _record_enqueue_failure(async_session_factory, claim, exc)
        return len(claims)

    for claim in claims:
        await _enqueue_claim(async_session_factory, pool, claim)
    return len(claims)


async def dispatch_pending_ai_pre_reviews() -> int:
    """Request-path accelerator for the durable outbox recovery sweep."""
    return await sweep_ai_pre_review_dispatches()
