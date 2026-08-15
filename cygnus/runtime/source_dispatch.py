"""Durable source dispatch lifecycle: generation/stage/attempt + lease fencing.

Each source pipeline cycle is identified by a monotonic
``sources.dispatch_generation``. Every worker handoff (stage) within the cycle
is recorded as a ``SourceDispatchExecution`` row whose ARQ job id is
deterministic, so a crash or restart can never silently lose or duplicate work:

- the API/task enqueue path records the outbox row transactionally and enqueues
  with ARQ's ``_job_id`` — ARQ documents an existing job as ``None``, which is
  a successful acknowledgement of a durable replay;
- worker tasks claim the current-generation execution at entry and fence every
  critical commit against ``sources.dispatch_generation`` — an attempt from an
  older generation (or a tombstoned source) is fenced as stale before it can
  write pages or flip terminal state;
- ``sweep_source_dispatches`` reconciles expired leases and re-enqueues safely,
  marks superseded executions, and exposes structured enqueue failures.

The module owns no HTTP surface and no ARQ pool wiring: it consumes the pool via
``get_arq_pool`` (lazily) and the session factory via ``get_async_session_factory``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.observability import (
    current_request_id,
    current_traceparent,
    record_queue,
)
from cygnus.runtime.database.models import Source, SourceDispatchExecution

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage + status vocabulary (mirrors the model check constraints)
# ---------------------------------------------------------------------------

DISPATCH_STAGE_INGEST = "ingest"
DISPATCH_STAGE_POST_EXTRACTION = "post_extraction"
DISPATCH_STAGE_MAP_REDUCE = "map_reduce"
DISPATCH_STAGE_REFINE = "refine"
DISPATCH_STAGE_REGENERATE_PLAN = "regenerate_plan"

DISPATCH_STATUS_PENDING = "pending"
DISPATCH_STATUS_DISPATCHING = "dispatching"
DISPATCH_STATUS_ENQUEUED = "enqueued"
DISPATCH_STATUS_RUNNING = "running"
DISPATCH_STATUS_COMPLETED = "completed"
DISPATCH_STATUS_STALE = "stale"
DISPATCH_STATUS_FAILED = "failed"

_TERMINAL_STATUSES = frozenset(
    {DISPATCH_STATUS_COMPLETED, DISPATCH_STATUS_STALE, DISPATCH_STATUS_FAILED}
)
_NON_TERMINAL_STATUSES = frozenset(
    {
        DISPATCH_STATUS_PENDING,
        DISPATCH_STATUS_DISPATCHING,
        DISPATCH_STATUS_ENQUEUED,
        DISPATCH_STATUS_RUNNING,
    }
)

# A worker lease covers one task run; an enqueued-but-unclaimed job is recovered
# after ENQUEUED_RECOVERY_SECONDS. An ambiguous enqueue failure is retried with
# the same deterministic ARQ id; only a known exception exhausts the budget.
DISPATCH_LEASE_SECONDS = 60
ENQUEUED_RECOVERY_SECONDS = 300
MAX_DISPATCH_ENQUEUE_ATTEMPTS = 5

_DISPATCH_JOB_PREFIX = "source-dispatch:"

# arq task name → pipeline stage. This is the single mapping the outbox uses to
# reconcile deterministic job ids with the stage vocabulary.
_TASK_STAGE: dict[str, str] = {
    "ingest_file_task": DISPATCH_STAGE_INGEST,
    "ingest_url_task": DISPATCH_STAGE_INGEST,
    "caption_images_task": DISPATCH_STAGE_POST_EXTRACTION,
    "ingest_map_reduce_task": DISPATCH_STAGE_MAP_REDUCE,
    "ingest_refine_task": DISPATCH_STAGE_REFINE,
    "regenerate_plan_task": DISPATCH_STAGE_REGENERATE_PLAN,
}


class SourceDispatchSuperseded(RuntimeError):
    """Raised when a worker's execution no longer matches source truth.

    A stale worker must not mark the source failed — the newer generation owns
    the source. Tasks catch this and abort without touching terminal state.
    """


@dataclass(frozen=True, slots=True)
class SourceDispatchClaim:
    """A leased execution a worker may safely drive to a terminal state."""

    dispatch_id: uuid.UUID
    source_id: uuid.UUID
    generation: int
    stage: str
    task_name: str
    task_args: tuple[Any, ...]
    job_id: str
    attempt_count: int
    lease_token: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record_dispatch_queue(
    row: SourceDispatchExecution,
    *,
    terminal_state: str | None = None,
    attempts: int = 0,
) -> None:
    """Emit payload-free queue age/attempt/terminal metrics for one row."""
    age_seconds: float | None = None
    created_at = getattr(row, "created_at", None)
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_seconds = max((_now() - created_at).total_seconds(), 0.0)
    try:
        record_queue(
            queue="source_dispatch",
            terminal_state=terminal_state,
            age_seconds=age_seconds,
            attempts=max(int(attempts), 0),
        )
    except Exception:
        # Metrics must never alter a durable dispatch transition.
        return


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(30 * (2 ** max(attempt_count - 1, 0)), 300))


def _dispatch_enqueue_kwargs(row: SourceDispatchExecution) -> dict[str, Any]:
    """Build deterministic ARQ kwargs from durable outbox trace metadata.

    A replay or sweep must retain the correlation originally persisted with the
    outbox row. Ambient context is only a fallback for legacy rows created
    before correlation columns existed; otherwise a later request could
    incorrectly relabel a durable job's trace.
    """
    correlation_id = (
        str(row.correlation_id) if getattr(row, "correlation_id", None) else None
    )
    traceparent = getattr(row, "traceparent", None)
    if correlation_id is None:
        correlation_id = current_request_id()
        traceparent = traceparent or current_traceparent()
    try:
        from cygnus.runtime.worker import _correlation_enqueue_kwargs

        correlation_kwargs = _correlation_enqueue_kwargs(
            correlation_id,
            traceparent=traceparent,
        )
    except Exception:
        correlation_kwargs = {}
    return {"_job_id": row.job_id, **correlation_kwargs}


# ---------------------------------------------------------------------------
# Deterministic job identity
# ---------------------------------------------------------------------------


def source_stage_job_id(source_id: uuid.UUID | str, stage: str, generation: int) -> str:
    """Return the single ARQ identity permitted for one (generation, stage)."""
    return f"{_DISPATCH_JOB_PREFIX}{source_id}:{stage}:{generation}"


def parse_dispatch_job_id(
    job_id: str | None,
) -> tuple[uuid.UUID, str, int] | None:
    """Parse a deterministic dispatch job id, or None for foreign/legacy ids."""
    if not job_id or not job_id.startswith(_DISPATCH_JOB_PREFIX):
        return None
    try:
        _, raw_source, stage, raw_generation = job_id.split(":")
        return uuid.UUID(raw_source), stage, int(raw_generation)
    except (ValueError, TypeError):
        return None


def dispatch_stage_for_task(task_name: str) -> str | None:
    return _TASK_STAGE.get(task_name)


async def record_source_dispatch(
    db: AsyncSession,
    source: Source,
    *,
    stage: str,
    task_name: str,
    task_args: tuple[Any, ...] = (),
    new_generation: bool = False,
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> tuple[SourceDispatchExecution, int, str]:
    """Create or reuse the outbox row for one (generation, stage) execution.

    ``new_generation=True`` starts a fresh pipeline cycle (initial ingest,
    retry, department-change re-ingest): the source's ``dispatch_generation``
    is bumped and every older execution is fenced as superseded by the sweep.

    The row starts ``pending`` so a crash between this commit and the enqueue
    is recovered by ``sweep_source_dispatches``. Terminal rows are never
    re-armed. Returns (row, generation, job_id).
    """
    generation = int(source.dispatch_generation or 0)
    if new_generation or generation < 1:
        generation = generation + 1 if new_generation else 1
        source.dispatch_generation = generation
    effective_correlation = correlation_id or current_request_id()
    effective_traceparent = traceparent or current_traceparent()
    correlation_uuid = None
    if effective_correlation:
        try:
            correlation_uuid = uuid.UUID(str(effective_correlation))
        except (TypeError, ValueError):
            correlation_uuid = None
    job_id = source_stage_job_id(source.id, stage, generation)

    statement = (
        pg_insert(SourceDispatchExecution)
        .values(
            id=uuid.uuid4(),
            source_id=source.id,
            generation=generation,
            stage=stage,
            task_name=task_name,
            task_args=list(task_args),
            job_id=job_id,
            correlation_id=correlation_uuid,
            traceparent=effective_traceparent,
            dispatch_status=DISPATCH_STATUS_PENDING,
            attempt_count=0,
        )
        .on_conflict_do_nothing(constraint="uq_source_dispatch_execution_stage")
    )
    await db.execute(statement)

    row = (
        await db.execute(
            select(SourceDispatchExecution).where(
                SourceDispatchExecution.source_id == source.id,
                SourceDispatchExecution.generation == generation,
                SourceDispatchExecution.stage == stage,
            )
        )
    ).scalar_one()
    if row.dispatch_status not in _TERMINAL_STATUSES:
        # Refresh the handoff target for a re-recorded non-terminal row
        # (e.g. the same stage enqueued by two continuation paths).
        if row.task_name != task_name or (row.task_args or []) != list(task_args):
            row.task_name = task_name
            row.task_args = list(task_args)
    return row, generation, job_id


async def enqueue_dispatch_execution(
    db: AsyncSession,
    row: SourceDispatchExecution,
    *,
    pool: Any = None,
) -> bool:
    """Enqueue the row's task with its deterministic id; ack or record failure.

    Caller commits. Returns True when ARQ accepted (or the job already exists).
    """
    if row.dispatch_status in _TERMINAL_STATUSES:
        logger.info(
            "source dispatch {} already terminal ({}); skipping enqueue",
            row.job_id,
            row.dispatch_status,
        )
        return False
    if pool is None:
        from cygnus.runtime.worker import get_arq_pool

        pool = await get_arq_pool()
    try:
        job = await pool.enqueue_job(
            row.task_name,
            *(row.task_args or ()),
            **_dispatch_enqueue_kwargs(row),
        )
        if job is None:
            logger.info(
                "source dispatch job {} already exists; acknowledging durable replay",
                row.job_id,
            )
        row.dispatch_status = DISPATCH_STATUS_ENQUEUED
        row.enqueued_at = row.enqueued_at or _now()
        row.lease_expires_at = _now() + timedelta(seconds=ENQUEUED_RECOVERY_SECONDS)
        row.next_attempt_at = None
        row.terminal_reason = None
        row.last_error = None
        _record_dispatch_queue(row)
        return True
    except Exception as exc:
        row.dispatch_status = DISPATCH_STATUS_PENDING
        row.attempt_count = (row.attempt_count or 0) + 1
        row.last_error = f"{type(exc).__name__}: {str(exc)[:900]}"
        row.lease_expires_at = None
        row.terminal_reason = None
        if row.attempt_count >= MAX_DISPATCH_ENQUEUE_ATTEMPTS:
            row.dispatch_status = DISPATCH_STATUS_FAILED
            row.terminal_reason = "enqueue_retry_exhausted"
            row.completed_at = _now()
        else:
            row.next_attempt_at = _now() + _retry_delay(row.attempt_count)
        _record_dispatch_queue(
            row,
            terminal_state=(
                "failed" if row.dispatch_status == DISPATCH_STATUS_FAILED else None
            ),
            attempts=1,
        )
        logger.warning(
            "source dispatch enqueue failed for {} (attempt {}): {}",
            row.job_id,
            row.attempt_count,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Worker claim / fence / terminal marks
# ---------------------------------------------------------------------------


async def _find_execution(
    db: AsyncSession,
    source_id: uuid.UUID | str,
    generation: int,
    stage: str,
    *,
    for_update: bool = False,
) -> SourceDispatchExecution | None:
    statement = select(SourceDispatchExecution).where(
        SourceDispatchExecution.source_id == source_id,
        SourceDispatchExecution.generation == generation,
        SourceDispatchExecution.stage == stage,
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


def _build_claim(
    row: SourceDispatchExecution,
    *,
    lease_token: str,
    now: datetime,
) -> SourceDispatchClaim:
    return SourceDispatchClaim(
        dispatch_id=row.id,
        source_id=row.source_id,
        generation=row.generation,
        stage=row.stage,
        task_name=row.task_name,
        task_args=tuple(row.task_args or ()),
        job_id=row.job_id,
        attempt_count=row.attempt_count,
        lease_token=lease_token,
    )


async def claim_source_dispatch(
    db: AsyncSession,
    source: Source,
    *,
    stage: str,
    job_id: str | None = None,
) -> SourceDispatchClaim | None:
    """Claim the current-generation execution for ``stage`` at worker entry.

    Returns ``None`` when there is nothing to fence: legacy sources without a
    recorded cycle, executions already terminal, or out-of-band jobs that were
    never routed through the outbox. Raises ``SourceDispatchSuperseded`` when
    the running job demonstrably belongs to an older generation — the worker
    must abort without touching source state.

    The lease is taken over unconditionally for the matching execution: ARQ
    delivers at most one in-flight job per job id, and a re-run only happens
    after the previous holder died, so a live lease is never a reason to drop
    the legitimate owner.
    """
    generation = int(source.dispatch_generation or 0)
    if generation < 1:
        return None

    parsed = parse_dispatch_job_id(job_id)
    if parsed is not None:
        parsed_source, parsed_stage, parsed_generation = parsed
        if (
            str(parsed_source) == str(source.id)
            and parsed_stage == stage
            and parsed_generation < generation
        ):
            # Deterministic job from an older cycle: fence it immediately.
            await _mark_stale_execution(
                db,
                source_id=source.id,
                generation=parsed_generation,
                stage=stage,
                reason="superseded_by_generation",
            )
            raise SourceDispatchSuperseded(
                f"source {source.id} generation moved {parsed_generation} → "
                f"{generation}; fencing stale {stage} attempt"
            )

    row = await _find_execution(db, source.id, generation, stage, for_update=True)
    if row is None:
        return None
    if row.dispatch_status in _TERMINAL_STATUSES:
        return None
    if job_id and row.job_id != job_id:
        # A different arq job id than the outbox one means this run was not
        # enqueued for the current execution — it cannot safely drive it.
        raise SourceDispatchSuperseded(
            f"job {job_id} does not match execution {row.job_id} for "
            f"source {source.id} {stage}; fencing foreign attempt"
        )

    now = _now()
    row.dispatch_status = DISPATCH_STATUS_RUNNING
    row.lease_token = uuid.uuid4().hex
    row.lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    row.next_attempt_at = None
    row.terminal_reason = None
    row.last_error = None
    return _build_claim(row, lease_token=row.lease_token, now=now)


async def start_dispatch_lease_renewal(
    session_factory,
    claim: SourceDispatchClaim,
    *,
    ttl_seconds: int = DISPATCH_LEASE_SECONDS,
    renew_interval_seconds: float = DISPATCH_LEASE_SECONDS / 3,
) -> asyncio.Task:
    """Start a background lease-renewal guard for a claimed execution.

    Renews ``lease_expires_at`` with the SAME lease token at <= 1/3 TTL while
    the claim is still current truth: status ``running``, token unchanged,
    generation unchanged, source not tombstoned. The guard exits on any
    terminal mark, token loss (another worker took the lease), supersession,
    or source deletion; a process crash stops renewal naturally and lets the
    sweeper recover the execution. This is a per-execution dispatch lease, not
    a process heartbeat.
    """
    if claim is None:
        raise ValueError("a claim is required to renew its lease")

    async def _renew() -> None:
        while True:
            await asyncio.sleep(renew_interval_seconds)
            try:
                async with session_factory() as db:
                    row = await db.get(
                        SourceDispatchExecution,
                        claim.dispatch_id,
                        with_for_update=True,
                        populate_existing=True,
                    )
                    if (
                        row is None
                        or row.dispatch_status != DISPATCH_STATUS_RUNNING
                        or row.lease_token != claim.lease_token
                    ):
                        return
                    source_state = (
                        await db.execute(
                            select(
                                Source.dispatch_generation,
                                Source.delete_requested_at,
                            ).where(Source.id == claim.source_id)
                        )
                    ).one_or_none()
                    if (
                        source_state is None
                        or source_state.delete_requested_at is not None
                        or int(source_state.dispatch_generation or 0)
                        != claim.generation
                    ):
                        return
                    row.lease_expires_at = _now() + timedelta(seconds=ttl_seconds)
                    await db.commit()
            except Exception as exc:
                logger.warning(
                    "source dispatch lease renewal stopped for {}: {}",
                    claim.job_id,
                    exc,
                )
                return

    return asyncio.create_task(_renew())


async def fence_source_dispatch(
    db: AsyncSession,
    claim: SourceDispatchClaim | None,
    *,
    source_id: uuid.UUID | str,
) -> None:
    """Raise ``SourceDispatchSuperseded`` unless the claim is still current.

    Called immediately before critical commits (page drafting, terminal state
    transitions). Re-reads source and execution truth directly so a concurrent
    retry (generation bump) or deletion fences the stale worker without
    touching the ORM objects it is about to write. A ``None`` claim (legacy /
    out-of-band execution with no recorded cycle) is not fenced, matching
    pre-outbox behavior.
    """
    if claim is None:
        return
    source_state = (
        await db.execute(
            select(Source.dispatch_generation, Source.delete_requested_at).where(
                Source.id == source_id
            )
        )
    ).one_or_none()
    if source_state is None or source_state.delete_requested_at is not None:
        raise SourceDispatchSuperseded(
            f"source {source_id} is gone or being deleted; fencing execution"
        )
    if int(source_state.dispatch_generation or 0) != claim.generation:
        raise SourceDispatchSuperseded(
            f"source {source_id} generation moved {claim.generation} → "
            f"{source_state.dispatch_generation}; fencing stale attempt"
        )
    execution = (
        await db.execute(
            select(
                SourceDispatchExecution.dispatch_status,
                SourceDispatchExecution.lease_token,
                SourceDispatchExecution.lease_expires_at,
            ).where(SourceDispatchExecution.id == claim.dispatch_id)
        )
    ).one_or_none()
    if (
        execution is None
        or execution.dispatch_status != DISPATCH_STATUS_RUNNING
        or execution.lease_token != claim.lease_token
        or execution.lease_expires_at is None
        or execution.lease_expires_at <= _now()
    ):
        raise SourceDispatchSuperseded(
            f"execution {claim.dispatch_id} lease lost or stale; fencing attempt"
        )


def _claim_owns_execution(
    row: SourceDispatchExecution | None,
    claim: SourceDispatchClaim,
) -> bool:
    """A terminal mark applies only while the claim still owns the lease.

    Token mismatch means another worker took the lease over; the stale worker
    must not flip terminal state on an execution it no longer drives.
    """
    return bool(
        row is not None
        and row.dispatch_status not in _TERMINAL_STATUSES
        and row.lease_token == claim.lease_token
    )


async def complete_source_dispatch(
    db: AsyncSession,
    claim: SourceDispatchClaim,
    *,
    reason: str = "completed",
) -> None:
    row = await db.get(SourceDispatchExecution, claim.dispatch_id)
    if row is None or not _claim_owns_execution(row, claim):
        return
    row.dispatch_status = DISPATCH_STATUS_COMPLETED
    row.terminal_reason = reason
    row.completed_at = _now()
    row.lease_expires_at = None
    row.next_attempt_at = None
    row.last_error = None
    _record_dispatch_queue(row, terminal_state="completed")


async def fail_source_dispatch(
    db: AsyncSession,
    claim: SourceDispatchClaim,
    *,
    error: str,
    reason: str = "execution_failed",
) -> None:
    row = await db.get(SourceDispatchExecution, claim.dispatch_id)
    if row is None or not _claim_owns_execution(row, claim):
        return
    row.dispatch_status = DISPATCH_STATUS_FAILED
    row.terminal_reason = reason
    row.last_error = f"{str(error)[:1000]}"
    row.completed_at = _now()
    row.lease_expires_at = None
    row.next_attempt_at = None
    _record_dispatch_queue(row, terminal_state="failed")


async def mark_source_dispatch_stale(
    db: AsyncSession,
    claim: SourceDispatchClaim,
    *,
    reason: str = "superseded",
) -> None:
    row = await db.get(SourceDispatchExecution, claim.dispatch_id)
    if row is None or not _claim_owns_execution(row, claim):
        return
    row.dispatch_status = DISPATCH_STATUS_STALE
    row.terminal_reason = reason
    row.last_error = "fenced: execution is no longer current source truth"
    row.completed_at = _now()
    row.lease_expires_at = None
    row.next_attempt_at = None
    _record_dispatch_queue(row, terminal_state="stale")


async def _mark_stale_execution(
    db: AsyncSession,
    *,
    source_id: uuid.UUID | str,
    generation: int,
    stage: str,
    reason: str,
) -> None:
    row = await _find_execution(db, source_id, generation, stage)
    if row is None or row.dispatch_status in _TERMINAL_STATUSES:
        return
    row.dispatch_status = DISPATCH_STATUS_STALE
    row.terminal_reason = reason
    row.last_error = "fenced: execution is no longer current source truth"
    row.completed_at = _now()
    row.lease_expires_at = None
    row.next_attempt_at = None


# ---------------------------------------------------------------------------
# Reconciliation sweep (worker cron + startup)
# ---------------------------------------------------------------------------


async def _acknowledge_enqueue(
    async_session_factory, claim: SourceDispatchClaim
) -> None:
    now = _now()
    async with async_session_factory() as db:
        row = await db.get(
            SourceDispatchExecution,
            claim.dispatch_id,
            with_for_update=True,
            populate_existing=True,
        )
        if row is None or not _owns_claim(row, claim):
            return
        if await _execution_is_superseded(db, row):
            row.dispatch_status = DISPATCH_STATUS_STALE
            row.terminal_reason = "superseded"
            row.last_error = "fenced: source moved on before acknowledgement"
            row.completed_at = now
            row.lease_expires_at = None
            row.next_attempt_at = None
        else:
            row.dispatch_status = DISPATCH_STATUS_ENQUEUED
            row.enqueued_at = row.enqueued_at or now
            row.lease_expires_at = now + timedelta(seconds=ENQUEUED_RECOVERY_SECONDS)
            row.next_attempt_at = None
            row.last_error = None
            row.terminal_reason = None
        await db.commit()


async def _record_enqueue_failure(
    async_session_factory,
    claim: SourceDispatchClaim,
    exc: Exception,
) -> None:
    now = _now()
    error = f"{type(exc).__name__}: {str(exc)[:900]}"
    async with async_session_factory() as db:
        row = await db.get(
            SourceDispatchExecution,
            claim.dispatch_id,
            with_for_update=True,
            populate_existing=True,
        )
        if row is None or not _owns_claim(row, claim):
            return
        if await _execution_is_superseded(db, row):
            row.dispatch_status = DISPATCH_STATUS_STALE
            row.terminal_reason = "superseded"
            row.last_error = "fenced: source moved on before enqueue retry"
            row.completed_at = now
            row.lease_expires_at = None
            row.next_attempt_at = None
        elif claim.attempt_count >= MAX_DISPATCH_ENQUEUE_ATTEMPTS:
            row.dispatch_status = DISPATCH_STATUS_FAILED
            row.terminal_reason = "enqueue_retry_exhausted"
            row.last_error = error
            row.completed_at = now
            row.lease_expires_at = None
            row.next_attempt_at = None
        else:
            row.dispatch_status = DISPATCH_STATUS_PENDING
            row.last_error = error
            row.next_attempt_at = now + _retry_delay(claim.attempt_count)
            row.lease_expires_at = None
            row.terminal_reason = None
        await db.commit()


def _owns_claim(
    row: SourceDispatchExecution,
    claim: SourceDispatchClaim,
) -> bool:
    return bool(
        row.dispatch_status == DISPATCH_STATUS_DISPATCHING
        and row.attempt_count == claim.attempt_count
    )


def _dispatch_is_due(
    row: SourceDispatchExecution,
    *,
    now: datetime,
) -> bool:
    """Whether the row is still claimable after the sweep's row lock."""
    if row.dispatch_status == DISPATCH_STATUS_PENDING:
        return row.next_attempt_at is None or row.next_attempt_at <= now
    if row.dispatch_status in (
        DISPATCH_STATUS_DISPATCHING,
        DISPATCH_STATUS_ENQUEUED,
        DISPATCH_STATUS_RUNNING,
    ):
        # With active lease renewal, an expired RUNNING lease means the worker
        # died — recovery re-enqueues the same deterministic job safely.
        return row.lease_expires_at is None or row.lease_expires_at <= now
    return False


async def _execution_is_superseded(
    db: AsyncSession,
    row: SourceDispatchExecution,
) -> bool:
    source_state = (
        await db.execute(
            select(Source.dispatch_generation, Source.delete_requested_at).where(
                Source.id == row.source_id
            )
        )
    ).one_or_none()
    if source_state is None or source_state.delete_requested_at is not None:
        return True
    return int(source_state.dispatch_generation or 0) > row.generation


async def _claim_due_executions(
    db: AsyncSession,
    *,
    limit: int,
) -> list[SourceDispatchExecution]:
    """Lease due outbox rows whose generation is still current source truth."""
    now = _now()
    current_sources = select(Source.id).where(
        Source.id == SourceDispatchExecution.source_id,
        Source.delete_requested_at.is_(None),
        Source.dispatch_generation == SourceDispatchExecution.generation,
    )
    due = or_(
        and_(
            SourceDispatchExecution.dispatch_status == DISPATCH_STATUS_PENDING,
            or_(
                SourceDispatchExecution.next_attempt_at.is_(None),
                SourceDispatchExecution.next_attempt_at <= now,
            ),
        ),
        and_(
            SourceDispatchExecution.dispatch_status.in_(
                (
                    DISPATCH_STATUS_DISPATCHING,
                    DISPATCH_STATUS_ENQUEUED,
                    DISPATCH_STATUS_RUNNING,
                )
            ),
            or_(
                SourceDispatchExecution.lease_expires_at.is_(None),
                SourceDispatchExecution.lease_expires_at <= now,
            ),
        ),
    )
    rows = list(
        (
            await db.execute(
                select(SourceDispatchExecution)
                .where(due, SourceDispatchExecution.source_id.in_(current_sources))
                .order_by(
                    SourceDispatchExecution.created_at,
                    SourceDispatchExecution.id,
                )
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    changed = False
    for row in rows:
        # Re-check after the row lock: a worker may have claimed the execution
        # while this sweep was waiting, renewing its lease.
        if not _dispatch_is_due(row, now=now):
            continue
        row.dispatch_status = DISPATCH_STATUS_DISPATCHING
        row.attempt_count = (row.attempt_count or 0) + 1
        row.lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
        row.next_attempt_at = None
        row.terminal_reason = None
        row.last_error = None
        changed = True
    if changed:
        await db.commit()
    return rows


async def sweep_source_dispatches(*, limit: int = 50) -> int:
    """Recover every due committed dispatch intent without an HTTP request.

    Fences superseded executions, leases due ones, and enqueues each lease
    with its deterministic ARQ id. Returns the number of claimed executions.
    """
    if limit < 1:
        raise ValueError("limit must be positive")

    from cygnus.runtime.database import get_async_session_factory

    async_session_factory = get_async_session_factory()

    async with async_session_factory() as db:
        now = _now()
        # 1. Fence executions superseded by a newer generation or a tombstone.
        await db.execute(
            update(SourceDispatchExecution)
            .where(
                SourceDispatchExecution.dispatch_status.in_(
                    tuple(_NON_TERMINAL_STATUSES)
                ),
                SourceDispatchExecution.source_id.in_(
                    select(Source.id).where(
                        Source.id == SourceDispatchExecution.source_id,
                        or_(
                            Source.delete_requested_at.isnot(None),
                            Source.dispatch_generation
                            > SourceDispatchExecution.generation,
                        ),
                    )
                ),
            )
            .values(
                dispatch_status=DISPATCH_STATUS_STALE,
                terminal_reason="superseded",
                last_error="superseded by a newer execution generation or "
                "source deletion",
                lease_expires_at=None,
                next_attempt_at=None,
                completed_at=now,
            )
        )
        # 2. Terminate orphaned RUNNING executions: a running lease whose source
        # has already been flipped to a terminal error (worker died and ARQ
        # exhausted its retries) can never resume — keep the structured failure.
        await db.execute(
            update(SourceDispatchExecution)
            .where(
                SourceDispatchExecution.dispatch_status == DISPATCH_STATUS_RUNNING,
                or_(
                    SourceDispatchExecution.lease_expires_at.is_(None),
                    SourceDispatchExecution.lease_expires_at <= now,
                ),
                SourceDispatchExecution.source_id.in_(
                    select(Source.id).where(
                        Source.id == SourceDispatchExecution.source_id,
                        Source.status == "error",
                    )
                ),
            )
            .values(
                dispatch_status=DISPATCH_STATUS_FAILED,
                terminal_reason="worker_lease_expired",
                last_error="worker died without a terminal state; lease expired",
                lease_expires_at=None,
                next_attempt_at=None,
                completed_at=now,
            )
        )
        await db.commit()

        claims = await _claim_due_executions(db, limit=limit)
    if not claims:
        return 0

    try:
        from cygnus.runtime.worker import get_arq_pool

        pool = await get_arq_pool()
    except Exception as exc:
        logger.warning("source dispatch ARQ pool unavailable: {}", exc)
        for row in claims:
            claim = _build_claim(
                row,
                lease_token=row.lease_token or uuid.uuid4().hex,
                now=_now(),
            )
            await _record_enqueue_failure(async_session_factory, claim, exc)
        return len(claims)

    for row in claims:
        claim = _build_claim(
            row,
            lease_token=row.lease_token or uuid.uuid4().hex,
            now=_now(),
        )
        try:
            job = await pool.enqueue_job(
                row.task_name,
                *(row.task_args or ()),
                **_dispatch_enqueue_kwargs(row),
            )
            if job is None:
                logger.info(
                    "source dispatch job {} already exists; acknowledging durable replay",
                    row.job_id,
                )
        except Exception as exc:
            logger.warning(
                "source dispatch enqueue failed for {} (attempt {}): {}",
                row.job_id,
                row.attempt_count,
                exc,
            )
            await _record_enqueue_failure(async_session_factory, claim, exc)
            continue
        await _acknowledge_enqueue(async_session_factory, claim)
    return len(claims)
