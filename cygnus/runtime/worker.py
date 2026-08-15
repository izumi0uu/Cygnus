"""
arq Worker — async Redis queue for document ingestion.

The worker now compiles each source into the LLM Wiki (markdown pages stored
in PostgreSQL) instead of producing chunk embeddings. See cygnus/runtime/ai/wiki_compiler.py.

Start with (graceful drain runner, used by docker-compose):
    python -m cygnus.runtime.worker            # WorkerSettings
    python -m cygnus.runtime.worker SkillWorkerSettings
Plain arq CLI remains available:
    arq cygnus.runtime.worker.WorkerSettings
"""

import asyncio
import functools
import uuid
import zipfile
from typing import Any, Optional, cast
from time import monotonic_ns

from arq import cron
from arq import func as arq_func
from arq.connections import ArqRedis, RedisSettings, create_pool
from loguru import logger

from cygnus.runtime.arq_serializer import dumps as queue_serialize
from cygnus.runtime.arq_serializer import loads as queue_deserialize
from sqlalchemy import select
from sqlalchemy.engine import CursorResult

from cygnus.governance.feedback_execution import (
    FeedbackRouteClaim,
    FeedbackRouteLeaseLost,
    claim_feedback_routes,
    execute_feedback_route,
    record_feedback_route_failure,
)
from cygnus.governance.feedback_operations import (
    FeedbackRouteWorkerEvent,
    emit_feedback_route_worker_event,
)
from cygnus.governance.feedback_routing import FeedbackRouteState

from cygnus.runtime.config import get_settings
from cygnus.runtime.readiness import (
    DEFAULT_WORKER_QUEUE,
    DEFAULT_WORKER_ROLE,
    SKILLS_WORKER_QUEUE,
    SKILLS_WORKER_ROLE,
    mark_worker_job_finished,
    mark_worker_job_started,
    start_worker_heartbeat,
    stop_worker_heartbeat,
)
from cygnus.runtime.source_state import (
    attach_source_runtime_job,
    mark_source_awaiting_approval,
    mark_source_plan_ready_for_review,
    mark_source_post_extraction_resume,
    mark_source_processing,
    mark_source_ready,
    mark_source_runtime_error,
)

settings = get_settings()

_FEEDBACK_ROUTE_SWEEP_LIMIT = 25
WorkerContext = dict[str, object]


#: Reserved internal ARQ kwargs carrying durable trace context. The universal
#: wrapper removes both before business task invocation so task signatures stay
#: stable and no trace metadata leaks into product inputs.
_CORRELATION_KWARG = "_cygnus_correlation_id"
_TRACEPARENT_KWARG = "_cygnus_traceparent"


def _correlation_enqueue_kwargs(
    correlation_id: Optional[str] = None,
    *,
    traceparent: Optional[str] = None,
) -> dict[str, Any]:
    """Return validated internal ARQ trace kwargs when correlation is known.

    The traceparent is accepted only when it matches the deterministic W3C
    value for the validated correlation ID. This retains durable row metadata
    on replay while refusing malformed or unrelated trace headers.
    """
    cid = correlation_id
    if not cid:
        try:
            from cygnus.observability import current_request_id

            cid = current_request_id()
        except Exception:  # noqa: BLE001 — enqueue must never break
            cid = None
    if not cid:
        return {}
    try:
        from cygnus.observability import resolve_request_id_header
        from cygnus.observability._context import traceparent_for

        validated = resolve_request_id_header(cid)
    except Exception:  # noqa: BLE001
        validated = None
    if not validated:
        return {}
    kwargs: dict[str, Any] = {_CORRELATION_KWARG: validated}
    expected_traceparent = traceparent_for(validated)
    if traceparent == expected_traceparent:
        kwargs[_TRACEPARENT_KWARG] = traceparent
    return kwargs


def _track_heartbeat_job(fn):
    """Publish ARQ job start/finish metadata in the worker heartbeat.

    The wrapper reports only ARQ-provided job metadata (id, attempt, enqueue
    time) and never inspects job payloads.  ``functools.wraps`` keeps the
    function name stable so ARQ routing, retry, and timeout semantics are
    unchanged, and the heartbeat updates swallow their own failures so job
    execution is never altered by heartbeat observability.

    CYG-142: when a job carries the reserved ``_cygnus_correlation_id`` kwarg
    it is popped and rebound into the request correlation context for the
    duration of the job, so worker-side spans/metrics/audit rows join the
    original request trace end to end.
    """

    @functools.wraps(fn)
    async def wrapped(ctx: WorkerContext, *args, **kwargs):
        correlation_id = kwargs.pop(_CORRELATION_KWARG, None)
        traceparent = kwargs.pop(_TRACEPARENT_KWARG, None)
        await mark_worker_job_started(ctx)
        job_id = ctx.get("job_id")
        job_try = ctx.get("job_try")
        outcome = "completed"
        failure: BaseException | None = None
        try:
            from contextlib import nullcontext

            from cygnus.observability import (
                emit_structured_log,
                request_correlation,
                start_span,
            )

            span_attributes = {
                "arq.job_id": job_id,
                "arq.job_try": job_try,
            }
            correlation_scope = (
                nullcontext()
                if not correlation_id
                else request_correlation(correlation_id)
            )
            with correlation_scope:
                with start_span("arq.job", span_attributes):
                    return await fn(ctx, *args, **kwargs)
        except BaseException as exc:
            outcome = "failed"
            failure = exc
            raise
        finally:
            try:
                from cygnus.observability import emit_structured_log

                emit_structured_log(
                    logger,
                    "error" if failure is not None else "info",
                    event="arq_job",
                    status=outcome,
                    actor_class="worker",
                    job_id=job_id,
                    correlation_id=correlation_id,
                    traceparent=traceparent,
                    terminal_reason=(type(failure).__name__ if failure else None),
                    error=failure,
                )
            except Exception:
                pass
            await mark_worker_job_finished(ctx)

    return wrapped


def get_redis_settings() -> RedisSettings:
    resolved_settings = get_settings()
    return RedisSettings(
        host=resolved_settings.redis_host,
        port=resolved_settings.redis_port,
        database=resolved_settings.redis_db,
        password=resolved_settings.redis_password or None,
    )


def _get_redis_settings() -> RedisSettings:
    """Backward-compatible alias for legacy imports."""
    return get_redis_settings()


# arq Redis pool (lazy init)
_arq_pool: Optional[ArqRedis] = None


async def get_arq_pool() -> ArqRedis:
    """Lazy-init arq Redis connection pool."""
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            get_redis_settings(),
            job_serializer=queue_serialize,
            job_deserializer=queue_deserialize,
        )
    return _arq_pool


async def reset_arq_pool() -> None:
    """Drop the shared arq pool so infra wiring can be rebuilt cleanly."""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.aclose()
    _arq_pool = None


def resolve_post_extraction_task(*, has_images: bool) -> str:
    """Return the next worker job after pre-extraction completes."""
    return "caption_images_task" if has_images else "ingest_map_reduce_task"


def resolve_retry_task(
    *,
    source_type: str,
    pipeline_phase: str | None,
    current_status: str | None,
) -> str:
    """Resolve which worker job should resume a source retry.

    This turns persisted source lifecycle truth (`status` + `pipeline_phase`)
    into a concrete arq job name so retry/resume paths can re-enter the real
    worker pipeline instead of restarting from a generic placeholder path.
    """
    if pipeline_phase in ("refine", "verify", "commit"):
        return "ingest_refine_task"
    if (
        pipeline_phase in ("map", "reduce", "plan_review")
        or current_status == "plan_ready"
    ):
        return "ingest_map_reduce_task"
    return "ingest_url_task" if source_type == "url" else "ingest_file_task"


# ---------------------------------------------------------------------------
# Progress helper (re-exported from utils for backward compatibility)
# ---------------------------------------------------------------------------

from cygnus.runtime.utils.progress import ProgressTracker  # noqa: E402

# ---------------------------------------------------------------------------
# Ingestion tasks
# ---------------------------------------------------------------------------


async def enqueue_post_extraction_pipeline(
    source_id: str,
    has_images: bool,
    *,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> Optional[str]:
    """Enqueue caption_images_task (if images) or ingest_map_reduce_task directly.

    Shared by ingest_file_task auto-proceed and the approve-extraction API.
    With ``db`` + ``source`` the handoff is recorded in the durable dispatch
    outbox (deterministic ARQ job id); otherwise the legacy path is used.
    Returns the enqueued job_id, or None if enqueue failed.
    """
    from cygnus.runtime.source_dispatch import DISPATCH_STAGE_POST_EXTRACTION

    task_name = resolve_post_extraction_task(has_images=has_images)
    if db is not None and source is not None:
        return await _enqueue_via_outbox(
            db,
            source,
            stage=DISPATCH_STAGE_POST_EXTRACTION,
            task_name=task_name,
            task_args=(source_id,),
            new_generation=False,
        )
    pool = await get_arq_pool()
    job = await pool.enqueue_job(task_name, source_id, **_correlation_enqueue_kwargs())
    return job.job_id if job else None


async def _enqueue_via_outbox(
    db,
    source,
    *,
    stage: str,
    task_name: str,
    task_args: tuple[Any, ...],
    new_generation: bool,
) -> Optional[str]:
    """Record a source handoff in the durable dispatch outbox and enqueue it.

    Returns the deterministic ARQ job id, or ``None`` when the enqueue failed —
    the outbox row stays ``pending`` with a structured error and the worker
    sweep re-enqueues it safely.
    """
    from cygnus.runtime.source_dispatch import (
        enqueue_dispatch_execution,
        record_source_dispatch,
    )

    row, _generation, _job_id = await record_source_dispatch(
        db,
        source,
        stage=stage,
        task_name=task_name,
        task_args=tuple(task_args),
        new_generation=new_generation,
    )
    await db.flush()
    ok = await enqueue_dispatch_execution(db, row)
    return row.job_id if ok else None


async def enqueue_source_ingest_file(
    source_id: str,
    *,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> Optional[str]:
    """Enqueue the initial file-ingest worker path for a source.

    With ``db`` + ``source`` the handoff is recorded in the durable dispatch
    outbox (deterministic ARQ job id, lease lifecycle); otherwise the legacy
    fire-and-forget path is used.
    """
    from cygnus.runtime.source_dispatch import DISPATCH_STAGE_INGEST

    if db is not None and source is not None:
        return await _enqueue_via_outbox(
            db,
            source,
            stage=DISPATCH_STAGE_INGEST,
            task_name="ingest_file_task",
            task_args=(source_id,),
            new_generation=True,
        )
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "ingest_file_task", source_id, **_correlation_enqueue_kwargs()
    )
    return job.job_id if job else None


async def enqueue_source_ingest_url(
    source_id: str,
    *,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> Optional[str]:
    """Enqueue the initial URL-ingest worker path for a source.

    With ``db`` + ``source`` the handoff is recorded in the durable dispatch
    outbox; otherwise the legacy fire-and-forget path is used.
    """
    from cygnus.runtime.source_dispatch import DISPATCH_STAGE_INGEST

    if db is not None and source is not None:
        return await _enqueue_via_outbox(
            db,
            source,
            stage=DISPATCH_STAGE_INGEST,
            task_name="ingest_url_task",
            task_args=(source_id,),
            new_generation=True,
        )
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "ingest_url_task", source_id, **_correlation_enqueue_kwargs()
    )
    return job.job_id if job else None


async def enqueue_source_map_reduce(
    source_id: str,
    *,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> Optional[str]:
    """Enqueue the source map-reduce worker path (new cycle after a
    department-change re-ingest when dispatched through the outbox)."""
    from cygnus.runtime.source_dispatch import DISPATCH_STAGE_MAP_REDUCE

    if db is not None and source is not None:
        return await _enqueue_via_outbox(
            db,
            source,
            stage=DISPATCH_STAGE_MAP_REDUCE,
            task_name="ingest_map_reduce_task",
            task_args=(source_id,),
            new_generation=True,
        )
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "ingest_map_reduce_task", source_id, **_correlation_enqueue_kwargs()
    )
    return job.job_id if job else None


async def enqueue_source_refine(
    source_id: str,
    *,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> Optional[str]:
    """Enqueue the source refine worker path after plan approval."""
    from cygnus.runtime.source_dispatch import DISPATCH_STAGE_REFINE

    if db is not None and source is not None:
        return await _enqueue_via_outbox(
            db,
            source,
            stage=DISPATCH_STAGE_REFINE,
            task_name="ingest_refine_task",
            task_args=(source_id,),
            new_generation=False,
        )
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "ingest_refine_task", source_id, **_correlation_enqueue_kwargs()
    )
    return job.job_id if job else None


async def enqueue_source_retry(
    source_id: str,
    *,
    source_type: str,
    pipeline_phase: str | None,
    current_status: str | None,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> tuple[Optional[str], str]:
    """Resolve and enqueue the correct retry worker path for a source.

    With ``db`` + ``source`` the retry starts a new dispatch generation
    (fencing any straggler from the failed attempt) through the outbox.
    """
    task_name = resolve_retry_task(
        source_type=source_type,
        pipeline_phase=pipeline_phase,
        current_status=current_status,
    )
    if db is not None and source is not None:
        from cygnus.runtime.source_dispatch import dispatch_stage_for_task

        stage = dispatch_stage_for_task(task_name) or task_name
        job_id = await _enqueue_via_outbox(
            db,
            source,
            stage=stage,
            task_name=task_name,
            task_args=(source_id,),
            new_generation=True,
        )
        return (job_id, task_name)
    pool = await get_arq_pool()
    job = await pool.enqueue_job(task_name, source_id, **_correlation_enqueue_kwargs())
    return (job.job_id if job else None, task_name)


async def enqueue_source_plan_regeneration(
    source_id: str,
    reviewer_note: str,
    *,
    db: Optional[Any] = None,
    source: Optional[Any] = None,
) -> Optional[str]:
    """Enqueue the source plan-regeneration worker path."""
    from cygnus.runtime.source_dispatch import DISPATCH_STAGE_REGENERATE_PLAN

    if db is not None and source is not None:
        return await _enqueue_via_outbox(
            db,
            source,
            stage=DISPATCH_STAGE_REGENERATE_PLAN,
            task_name="regenerate_plan_task",
            task_args=(source_id, reviewer_note),
            new_generation=False,
        )
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "regenerate_plan_task",
        source_id,
        reviewer_note,
        **_correlation_enqueue_kwargs(),
    )
    return job.job_id if job else None


async def finalize_verbatim_source(session, source, tracker) -> dict[str, str | int]:
    """Verbatim path: index raw chunks (no LLM) and mark the source ready.

    Skips the entire MRP wiki pipeline AND the awaiting_approval token gate —
    verbatim indexing burns no LLM tokens, so even very long legal documents go
    straight to ready.
    """
    from cygnus.retrieval.source_chunks import index_verbatim_source

    await tracker.update(60, "Indexing verbatim document (no wiki)...")
    n_chunks = await index_verbatim_source(session, source)
    mark_source_ready(
        source,
        progress_message=(
            f"Verbatim: indexed {n_chunks} chunks, no wiki"
            if n_chunks
            else "Verbatim: stored, no embedding model (keyword search only)"
        ),
    )
    await session.commit()
    logger.info(f"Source {source.id} finalized as verbatim ({n_chunks} chunks indexed)")
    return {"status": "ready", "verbatim_chunks": n_chunks}


async def ingest_file_task(ctx: WorkerContext, source_id: str):
    """
    arq task: full file ingestion → wiki compilation.
    Steps: download from MinIO → extract text → outline → enqueue MRP + caption_images_task.
    Image captioning is offloaded to caption_images_task so this job is not blocked by image count.
    File must already be uploaded to MinIO before this task is enqueued.
    """
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source, SourceImage
    from cygnus.substrate.source_images import extract_images, inline_image_markers
    from cygnus.substrate.source_outline import assemble_full_text, build_outline
    from cygnus.substrate.source_text import _extract_text_from_file
    from cygnus.runtime.services.storage_service import storage_service
    from cygnus.runtime.utils.tokens import count_tokens

    sid = uuid.UUID(source_id)
    tracker = ProgressTracker(sid)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            logger.warning(f"Source {source_id} not found, it may have been deleted.")
            return
        if not source.minio_key:
            raise ValueError(f"Source {source_id} has no file in storage")

        from cygnus.runtime.source_dispatch import (
            DISPATCH_STAGE_INGEST,
            DISPATCH_STAGE_POST_EXTRACTION,
            SourceDispatchSuperseded,
            claim_source_dispatch,
            complete_source_dispatch,
            enqueue_dispatch_execution,
            fail_source_dispatch,
            fence_source_dispatch,
            mark_source_dispatch_stale,
            record_source_dispatch,
            start_dispatch_lease_renewal,
        )

        if source.delete_requested_at is not None:
            logger.info(f"Source {source_id} is being deleted; skipping ingest")
            return
        try:
            claim = await claim_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_INGEST,
                job_id=str(ctx.get("job_id") or ""),
            )
            await session.commit()
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} ingest fenced at entry: {exc}")
            await session.rollback()
            return

        renewal_task = None
        if claim is not None:
            renewal_task = await start_dispatch_lease_renewal(
                async_session_factory, claim
            )

        file_name = source.file_name or source.minio_key.split("/")[-1]

        try:
            mark_source_processing(
                source,
                progress=0,
                progress_message="Starting processing...",
            )
            await session.commit()

            if source.full_text and source.extracted_token_count is not None:
                # ARQ re-run after a crash (or retry after a post-extraction
                # failure): extraction already committed — resume at the gate
                # instead of re-downloading and duplicating image rows.
                token_count = source.extracted_token_count
                image_ids = (
                    (
                        await session.execute(
                            select(SourceImage.id).where(SourceImage.source_id == sid)
                        )
                    )
                    .scalars()
                    .all()
                )
                logger.info(
                    f"Source {source_id} resumed after committed extraction "
                    f"({len(image_ids)} images, {token_count} tokens)"
                )
                image_count = len(image_ids)
                has_images = bool(image_ids)
            else:
                # --- Step 1: Download from MinIO (10%) ---
                # Re-enforce the ingress ceiling while streaming the object.
                # This prevents a replaced storage object from bypassing the
                # bounded upload that originally created the source row.
                await tracker.update(5, "Loading file...")
                file_data = storage_service.download_file(
                    source.minio_key,
                    max_bytes=settings.max_source_upload_bytes,
                )
                await tracker.update(10, "File loaded")

                # --- Step 2: Extract text per page (25%) ---
                await tracker.update(15, "Extracting text (per page)...")
                # Resolve vision provider for OCR fallback on image-only PDFs
                vision_provider = None
                try:
                    from cygnus.runtime.ai.registry import ProviderRegistry

                    registry = ProviderRegistry(session)
                    vision_provider = await registry.get_vision()
                except Exception:
                    pass  # OCR fallback unavailable — continue without it
                pages_data = await _extract_text_from_file(
                    file_data, file_name, vision_provider=vision_provider
                )

                if not pages_data or not any(
                    (p.get("content") or "").strip() for p in pages_data
                ):
                    mark_source_runtime_error(
                        source,
                        error_message="Unable to extract text content",
                    )
                    await session.commit()
                    return {"status": "error", "message": "No text content"}

                await tracker.update(25, "Text extraction complete")

                # --- Step 3: Extract images (40%) ---
                # Captioning is offloaded to caption_images_task (enqueued below)
                # so this job is not blocked by the number of images.
                await tracker.update(30, "Extracting images...")
                images = extract_images(
                    file_data, file_name, source_id, storage_service
                )

                # Persist images so wiki content_md can reference them by uuid.
                for img in images:
                    row = SourceImage(
                        source_id=uuid.UUID(source_id),
                        minio_key=img.minio_key,
                        page_number=img.page_number,
                        image_index=img.image_index,
                        caption=img.caption,
                        content_type=img.content_type,
                        size_bytes=img.size_bytes,
                    )
                    session.add(row)
                    await session.flush()
                    img.image_id = str(row.id)

                # Inline image markers into per-page text so the compiler sees them.
                inline_image_markers(pages_data, images)
                await tracker.update(40, f"Analyzed {len(images)} images")
                image_count = len(images)
                has_images = bool(images)

                # --- Step 4: Build outline + assemble full_text (50%) ---
                await tracker.update(45, "Building document outline...")
                source.outline_json = build_outline(pages_data)
                full_text, page_offsets = assemble_full_text(pages_data)
                source.full_text = full_text
                source.page_offsets = page_offsets

                # --- Step 5: Token count (drives auto-approve vs gate) ---
                token_count = count_tokens(full_text)
                source.extracted_token_count = token_count
                await session.commit()
                await tracker.update(
                    50,
                    f"Outline: {len(source.outline_json or [])} top-level sections, ~{token_count} tokens",
                )

            # --- Verbatim: skip MRP + approval gate, index raw chunks, done ---
            if source.preserve_verbatim:
                await fence_source_dispatch(session, claim, source_id=sid)
                result = await finalize_verbatim_source(session, source, tracker)
                if claim is not None:
                    await complete_source_dispatch(
                        session, claim, reason="verbatim_ready"
                    )
                    await session.commit()
                return result

            # --- Step 6: Gate or auto-proceed ---
            threshold = settings.auto_approve_extraction_threshold_tokens
            if token_count > threshold:
                mark_source_awaiting_approval(
                    source,
                    token_count=token_count,
                    threshold=threshold,
                )
                await session.commit()
                if claim is not None:
                    await complete_source_dispatch(
                        session, claim, reason="awaiting_approval"
                    )
                    await session.commit()
                logger.info(
                    f"Source {source_id} gated at awaiting_approval: {token_count} tokens "
                    f"({image_count} images extracted, captioning deferred)"
                )
                return {
                    "status": "awaiting_approval",
                    "token_count": token_count,
                    "images": image_count,
                }

            await tracker.update(55, "Queuing compilation pipeline...")
            await fence_source_dispatch(session, claim, source_id=sid)
            dispatch_row, _generation, _job_id = await record_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_POST_EXTRACTION,
                task_name=resolve_post_extraction_task(has_images=has_images),
                task_args=(source_id,),
                new_generation=False,
            )
            await session.flush()
            dispatch_ok = await enqueue_dispatch_execution(session, dispatch_row)
            job_id = dispatch_row.job_id if dispatch_ok else None
            mark_source_post_extraction_resume(
                source,
                has_images=has_images,
                job_id=job_id,
                progress=55,
            )
            if claim is not None:
                await complete_source_dispatch(
                    session, claim, reason="post_extraction_enqueued"
                )
            await session.commit()

            logger.info(
                f"Source {source_id} pre-processing done; next: {'caption→MRP' if has_images else 'MRP'}"
            )
            return {
                "status": "processing",
                "token_count": token_count,
                "images": image_count,
            }

        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} ingest superseded: {exc}")
            try:
                if claim is not None:
                    await mark_source_dispatch_stale(
                        session, claim, reason="superseded_by_generation"
                    )
                    await session.commit()
            except Exception:
                await session.rollback()
            return
        except BaseException as e:
            logger.error(f"Pre-processing failed for {source_id}: {e}")
            error_msg = str(e)[:500]
            progress_msg = f"Error: {str(e)[:200]}"

            async def _mark_error_file() -> None:
                from cygnus.runtime.database import async_session_factory as _sf
                from cygnus.runtime.database.models import (
                    Source as _Source,
                    SourceDispatchExecution as _Dispatch,
                )

                async with _sf() as err_session:
                    src = await err_session.get(_Source, sid)
                    if src:
                        mark_source_runtime_error(
                            src,
                            error_message=error_msg,
                            progress_message=progress_msg,
                        )
                        await err_session.commit()
                if claim is not None:
                    async with _sf() as dsp_session:
                        claim_row = await dsp_session.get(_Dispatch, claim.dispatch_id)
                        if claim_row is not None:
                            await fail_source_dispatch(
                                dsp_session, claim, error=error_msg
                            )
                            await dsp_session.commit()

            try:
                await asyncio.shield(_mark_error_file())
            except Exception:
                pass
            raise
        finally:
            if renewal_task is not None:
                renewal_task.cancel()


async def ingest_url_task(ctx: WorkerContext, source_id: str):
    """arq task: URL ingestion → wiki compilation."""
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source
    from cygnus.substrate.source_outline import assemble_full_text, build_outline
    from cygnus.substrate.source_text import _extract_text_from_url
    from cygnus.runtime.utils.tokens import count_tokens

    sid = uuid.UUID(source_id)
    tracker = ProgressTracker(sid)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            logger.warning(f"Source {source_id} not found, it may have been deleted.")
            return

        from cygnus.runtime.source_dispatch import (
            DISPATCH_STAGE_INGEST,
            DISPATCH_STAGE_POST_EXTRACTION,
            SourceDispatchSuperseded,
            claim_source_dispatch,
            complete_source_dispatch,
            enqueue_dispatch_execution,
            fail_source_dispatch,
            fence_source_dispatch,
            mark_source_dispatch_stale,
            record_source_dispatch,
            start_dispatch_lease_renewal,
        )

        if source.delete_requested_at is not None:
            logger.info(f"Source {source_id} is being deleted; skipping ingest")
            return
        try:
            claim = await claim_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_INGEST,
                job_id=str(ctx.get("job_id") or ""),
            )
            await session.commit()
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} URL ingest fenced at entry: {exc}")
            await session.rollback()
            return

        renewal_task = None
        if claim is not None:
            renewal_task = await start_dispatch_lease_renewal(
                async_session_factory, claim
            )

        try:
            mark_source_processing(source, progress=0)
            await session.commit()

            if source.full_text and source.extracted_token_count is not None:
                # ARQ re-run after a crash: fetch + extraction already committed.
                token_count = source.extracted_token_count
                logger.info(
                    f"URL source {source_id} resumed after committed extraction "
                    f"({token_count} tokens)"
                )
            else:
                await tracker.update(15, "Fetching content from URL...")
                if not source.url:
                    mark_source_runtime_error(
                        source,
                        error_message="Source has no URL",
                    )
                    await session.commit()
                    return {"status": "error"}
                pages_data = await _extract_text_from_url(source.url)

                if not pages_data or not any(
                    (p.get("content") or "").strip() for p in pages_data
                ):
                    mark_source_runtime_error(
                        source,
                        error_message="Unable to fetch content from URL",
                    )
                    await session.commit()
                    return {"status": "error"}

                await tracker.update(40, "Building outline...")
                source.outline_json = build_outline(pages_data)
                full_text, page_offsets = assemble_full_text(pages_data)
                source.full_text = full_text
                source.page_offsets = page_offsets
                token_count = count_tokens(full_text)
                source.extracted_token_count = token_count
                await session.commit()

            # --- Verbatim: skip MRP + approval gate, index raw chunks, done ---
            if source.preserve_verbatim:
                await fence_source_dispatch(session, claim, source_id=sid)
                result = await finalize_verbatim_source(session, source, tracker)
                if claim is not None:
                    await complete_source_dispatch(
                        session, claim, reason="verbatim_ready"
                    )
                    await session.commit()
                return result

            threshold = settings.auto_approve_extraction_threshold_tokens
            if token_count > threshold:
                mark_source_awaiting_approval(
                    source,
                    token_count=token_count,
                    threshold=threshold,
                )
                await session.commit()
                if claim is not None:
                    await complete_source_dispatch(
                        session, claim, reason="awaiting_approval"
                    )
                    await session.commit()
                logger.info(
                    f"URL source {source_id} gated at awaiting_approval: {token_count} tokens"
                )
                return {"status": "awaiting_approval", "token_count": token_count}

            await tracker.update(55, "Queuing compilation pipeline...")
            await fence_source_dispatch(session, claim, source_id=sid)
            dispatch_row, _generation, _job_id = await record_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_POST_EXTRACTION,
                task_name=resolve_post_extraction_task(has_images=False),
                task_args=(source_id,),
                new_generation=False,
            )
            await session.flush()
            dispatch_ok = await enqueue_dispatch_execution(session, dispatch_row)
            job_id = dispatch_row.job_id if dispatch_ok else None
            mark_source_post_extraction_resume(
                source,
                has_images=False,
                job_id=job_id,
                progress=55,
            )
            if claim is not None:
                await complete_source_dispatch(
                    session, claim, reason="post_extraction_enqueued"
                )
            await session.commit()

            logger.info(
                f"URL source {source_id} pre-processing done, MRP task enqueued: {job_id or 'n/a'}"
            )
            return {"status": "processing", "token_count": token_count}

        except SourceDispatchSuperseded as exc:
            logger.info(f"URL source {source_id} ingest superseded: {exc}")
            try:
                if claim is not None:
                    await mark_source_dispatch_stale(
                        session, claim, reason="superseded_by_generation"
                    )
                    await session.commit()
            except Exception:
                await session.rollback()
            return
        except BaseException as e:
            logger.error(f"URL ingestion failed for {source_id}: {e}")
            error_msg = str(e)[:500]

            async def _mark_error_url() -> None:
                from cygnus.runtime.database import async_session_factory as _sf
                from cygnus.runtime.database.models import (
                    Source as _Source,
                    SourceDispatchExecution as _Dispatch,
                )

                async with _sf() as err_session:
                    src = await err_session.get(_Source, sid)
                    if src:
                        mark_source_runtime_error(
                            src,
                            error_message=error_msg,
                        )
                        await err_session.commit()
                if claim is not None:
                    async with _sf() as dsp_session:
                        claim_row = await dsp_session.get(_Dispatch, claim.dispatch_id)
                        if claim_row is not None:
                            await fail_source_dispatch(
                                dsp_session, claim, error=error_msg
                            )
                            await dsp_session.commit()

            try:
                await asyncio.shield(_mark_error_url())
            except Exception:
                pass
            raise
        finally:
            if renewal_task is not None:
                renewal_task.cancel()


# ---------------------------------------------------------------------------
# Worker configuration
# ---------------------------------------------------------------------------


async def ingest_skill_task(
    ctx: WorkerContext, skill_id: str, version_id: str, file_path: str, file_name: str
):
    """
    arq task: unzip skill package from disk buffer, store in MinIO, and extract metadata.
    """
    import os

    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Skill, SkillVersion
    from cygnus.runtime.services.storage_service import storage_service

    sid = uuid.UUID(skill_id)
    vid = uuid.UUID(version_id)
    skill_name = file_name.rsplit(".", 1)[0]

    logger.info(f"Starting ingestion for skill: {skill_name} ({skill_id})")

    async with async_session_factory() as session:
        skill = await session.get(Skill, sid)
        version = await session.get(SkillVersion, vid)

        if not skill or not version:
            logger.error(f"Skill {skill_id} or Version {version_id} not found in DB")
            return

        try:
            skill.status = "processing"
            await session.commit()

            if not os.path.exists(file_path):
                logger.error(f"Disk buffer file not found: {file_path}")
                skill.status = "error"
                await session.commit()
                return

            import asyncio

            from cygnus.substrate.source_text import _guess_content_type

            # 1. Unzip with streaming, security checks, and concurrent uploads
            MAX_UNCOMPRESSED_SIZE = 10 * 1024 * 1024  # 10 MB
            MAX_FILE_COUNT = 100

            total_size = 0
            file_count = 0

            upload_tasks = []
            semaphore = asyncio.Semaphore(10)

            async def _upload_worker(zf_path, member_name, obj_name, file_size):
                async with semaphore:
                    # Open a fresh ZipFile instance in the thread to avoid GIL lock contention
                    with zipfile.ZipFile(zf_path) as local_zf:
                        with local_zf.open(member_name) as f_stream:
                            await storage_service.upload_stream_async(
                                obj_name,
                                f_stream,
                                file_size,
                                _guess_content_type(member_name),
                            )

            with zipfile.ZipFile(file_path) as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue

                    filename = member.filename

                    # [Security] Zip Slip check
                    if (
                        filename.startswith("/")
                        or filename.startswith("\\")
                        or "../" in filename
                        or "..\\" in filename
                    ):
                        raise ValueError(
                            f"Security risk: Zip Slip detected in {filename}"
                        )

                    # [Security] File count check
                    file_count += 1
                    if file_count > MAX_FILE_COUNT:
                        raise ValueError(f"Too many files (exceeds {MAX_FILE_COUNT})")

                    # [Security] Zip Bomb check
                    total_size += member.file_size
                    if total_size > MAX_UNCOMPRESSED_SIZE:
                        raise ValueError("Uncompressed size too large (exceeds 10MB)")

                    object_name = f"skills/{skill_id}/versions/{version.version_number}/content/{filename}"
                    target_readme = f"{skill_name}/SKILL.md".lower()

                    if filename.lower() == target_readme or filename.lower().endswith(
                        "/skill.md"
                    ):
                        with zf.open(member) as f:
                            content = f.read()

                        storage_service.upload_file(
                            object_name=object_name,
                            data=content,
                            content_type=_guess_content_type(filename),
                        )
                    else:
                        upload_tasks.append(
                            _upload_worker(
                                file_path, filename, object_name, member.file_size
                            )
                        )

            if upload_tasks:
                await asyncio.gather(*upload_tasks)

            # 3. Calculate content-based hash (consistent with contribution workflow)
            storage_path = (
                f"skills/{skill_id}/versions/{version.version_number}/content/"
            )
            file_hash = storage_service.calculate_prefix_hash(storage_path)

            # 4. Update DB with extracted metadata

            skill.version_hash = file_hash
            skill.current_version = version.version_number
            skill.storage_path = storage_path
            skill.status = "active"

            version.version_hash = file_hash
            version.storage_path = storage_path

            await session.commit()
            logger.success(
                f"Skill {skill_name} version {version.version_number} processed successfully"
            )

        except Exception as e:
            logger.exception(f"Failed to process skill {skill_name}: {e}")
            skill.status = "error"
            await session.commit()
        finally:
            # Clean up disk buffer
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Cleaned up disk buffer: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {file_path}: {e}")


async def delete_skill_task(ctx: WorkerContext, skill_id: str):
    """
    arq task: delete skill files from MinIO and remove from DB.
    """
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Skill
    from cygnus.runtime.services.storage_service import storage_service

    sid = uuid.UUID(skill_id)

    logger.info(f"Starting deletion task for skill: {skill_id}")

    async with async_session_factory() as session:
        skill = await session.get(Skill, sid)
        if not skill:
            logger.warning(f"Skill {skill_id} already deleted or not found")
            return

        try:
            from sqlalchemy.orm import selectinload

            # 1. Fetch skill with contributions to get their storage paths
            stmt = (
                select(Skill)
                .where(Skill.id == sid)
                .options(selectinload(Skill.contributions))
            )
            res = await session.execute(stmt)
            skill = res.scalars().first()
            if not skill:
                return

            # 2. Delete files from MinIO for the skill itself
            prefix = f"skills/{skill_id}/"
            storage_service.delete_prefix(prefix)

            # 3. Delete files for all associated contributions
            for contrib in skill.contributions:
                if contrib.storage_path:
                    logger.info(
                        f"Deleting storage for contribution {contrib.id}: {contrib.storage_path}"
                    )
                    storage_service.delete_prefix(contrib.storage_path)

            # 4. Delete skill from DB (cascades to SkillVersion and SkillContribution DB rows)
            await session.delete(skill)
            await session.commit()

            logger.success(
                f"Skill {skill_id} and all related assets (versions, contributions) deleted successfully"
            )

        except Exception as e:
            logger.exception(f"Failed to delete skill {skill_id}: {e}")
            raise


async def cleanup_temp_uploads_cron(ctx: WorkerContext):
    """
    Cronjob: Scan and clean orphaned files in temp_uploads left behind by a server crash (older than 1 hour).
    """
    import os
    import time

    temp_dir = "temp_uploads"
    if not os.path.exists(temp_dir):
        return

    cutoff_time = time.time() - 3600  # 1 hour ago

    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < cutoff_time:
                try:
                    os.remove(file_path)
                    logger.info(f"Cronjob: Cleaned up orphaned temp file {filename}")
                except Exception as e:
                    logger.debug(f"Cronjob: Failed to clean {filename}: {e}")


# ---------------------------------------------------------------------------
# Embedding migration: re-embed every wiki page with a new model
# ---------------------------------------------------------------------------


async def reembed_all_pages_task(ctx: WorkerContext, job_id: str) -> None:
    """
    Re-embed every wiki page using the model spec referenced by the job.

    On success, atomically flips `app_config.active_embedding_model_spec_id`
    to the new spec — search keeps using the OLD model until that flip lands,
    so there is no zero-result window during the migration.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from cygnus.runtime.ai.embedding_catalog import get_spec
    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import EmbeddingJob, Source, WikiPage
    from cygnus.retrieval.embedding_storage import (
        cleanup_stale_embeddings,
        cleanup_stale_source_chunk_embeddings,
        compute_content_hash,
        embedding_input_text,
        upsert_page_embedding,
    )
    from cygnus.runtime.services.config_service import (
        ACTIVE_EMBEDDING_MODEL_KEY,
        ConfigService,
    )

    job_uuid = uuid.UUID(job_id)
    BATCH = 50

    async with async_session_factory() as session:
        job = await session.get(EmbeddingJob, job_uuid)
        if job is None:
            logger.error(f"reembed: job {job_id} not found")
            return
        if job.status not in ("pending", "running"):
            logger.info(f"reembed: job {job_id} status={job.status}, skipping")
            return

        try:
            spec = get_spec(job.model_spec_id)
        except Exception as e:
            job.status = "failed"
            job.error_message = f"Unknown model spec: {e}"
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return

        # Provision a provider bound to the NEW spec (not the active one).
        registry = ProviderRegistry(session)
        try:
            provider = await registry.get_embedding(task="document", spec_id=spec.id)
        except Exception as e:
            job.status = "failed"
            job.error_message = f"Provider init failed: {e}"
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return

        # Count work and mark running.
        total = (
            (
                await session.execute(
                    select(WikiPage.id).where(WikiPage.slug.notin_(["_index", "_log"]))
                )
            )
            .scalars()
            .all()
        )
        job.total_pages = len(total)
        job.done_pages = 0
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await session.commit()

    logger.info(
        f"reembed: starting job {job_id} model={spec.id} dim={spec.dimension} "
        f"total={len(total)}"
    )

    # Process batches in independent sessions so progress is visible to UI poll.
    for offset in range(0, len(total), BATCH):
        batch_ids = total[offset : offset + BATCH]
        async with async_session_factory() as session:
            # Re-check cancellation flag.
            job = await session.get(EmbeddingJob, job_uuid)
            if job is None or job.status == "cancelled":
                logger.info(f"reembed: job {job_id} cancelled at offset={offset}")
                return

            pages = (
                (
                    await session.execute(
                        select(WikiPage).where(WikiPage.id.in_(batch_ids))
                    )
                )
                .scalars()
                .all()
            )
            inputs = [
                embedding_input_text(p.title, p.summary or "", p.content_md or "")
                for p in pages
            ]
            try:
                vectors = await provider.embed_batch(inputs)
            except Exception as e:
                job.status = "failed"
                job.error_message = f"Embedding API failed: {e}"
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()
                logger.exception(f"reembed: job {job_id} failed at offset={offset}")
                return

            for page, vec in zip(pages, vectors):
                await upsert_page_embedding(
                    session,
                    page_id=page.id,
                    spec=spec,
                    vector=list(vec),
                    content_hash=compute_content_hash(
                        page.title, page.summary or "", page.content_md or ""
                    ),
                )
            job.done_pages = min(offset + len(pages), job.total_pages)
            await session.commit()

    # Re-embed verbatim source chunks against the NEW spec too, so the unified
    # search pool stays consistent after the flip. Each source re-indexes against
    # spec.id explicitly (active spec is still the OLD one until the flip below).
    async with async_session_factory() as session:
        from cygnus.retrieval.source_chunks import index_verbatim_source

        verbatim_sources = (
            (
                await session.execute(
                    select(Source).where(
                        Source.preserve_verbatim.is_(True),
                        Source.status == "ready",
                    )
                )
            )
            .scalars()
            .all()
        )
        for vs in verbatim_sources:
            try:
                await index_verbatim_source(session, vs, spec_id=spec.id)
            except Exception as e:
                logger.warning(f"reembed: verbatim source {vs.id} re-index failed: {e}")
        if verbatim_sources:
            logger.info(f"reembed: re-indexed {len(verbatim_sources)} verbatim sources")

    # Atomic flip + cleanup of old model's vectors.
    async with async_session_factory() as session:
        job = await session.get(EmbeddingJob, job_uuid)
        if job is None or job.status == "cancelled":
            return
        svc = ConfigService(session)
        await svc.set(ACTIVE_EMBEDDING_MODEL_KEY, spec.id)
        deleted = await cleanup_stale_embeddings(session, keep_spec_id=spec.id)
        deleted += await cleanup_stale_source_chunk_embeddings(
            session, keep_spec_id=spec.id
        )
        job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info(
            f"reembed: job {job_id} complete — flipped to {spec.id}, "
            f"cleaned up {deleted} stale embedding rows"
        )


# ---------------------------------------------------------------------------
# MRP arq tasks
# ---------------------------------------------------------------------------


async def ingest_map_reduce_task(ctx: WorkerContext, source_id: str):
    """
    arq task: Phase 0-2 of MRP pipeline (Triage + MAP + REDUCE).

    Reads source.full_text and outline_json (set by ingest_file_task / ingest_url_task),
    runs parallel chunk extraction, entity deduplication, KB reconciliation, and
    produces a Compilation Plan saved to source_compilation_plans.

    If mrp_auto_approve_plan=True → immediately enqueues ingest_refine_task.
    Otherwise → sets source.status='plan_ready' and waits for human approval via API.
    """
    from cygnus.runtime.ai.mrp.pipeline import run_mrp_pipeline
    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import KnowledgeType, Source

    sid = uuid.UUID(source_id)
    tracker = ProgressTracker(sid)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            logger.warning(f"Source {source_id} not found, it may have been deleted.")
            return
        if not source.full_text:
            raise ValueError(
                f"Source {source_id} has no full_text — run pre-processing first"
            )

        from cygnus.runtime.source_dispatch import (
            DISPATCH_STAGE_MAP_REDUCE,
            SourceDispatchSuperseded,
            claim_source_dispatch,
            complete_source_dispatch,
            fail_source_dispatch,
            fence_source_dispatch,
            mark_source_dispatch_stale,
            start_dispatch_lease_renewal,
        )

        if source.delete_requested_at is not None:
            logger.info(f"Source {source_id} is being deleted; skipping MRP")
            return
        try:
            claim = await claim_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_MAP_REDUCE,
                job_id=str(ctx.get("job_id") or ""),
            )
            await session.commit()
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} map-reduce fenced at entry: {exc}")
            await session.rollback()
            return

        renewal_task = None
        if claim is not None:
            renewal_task = await start_dispatch_lease_renewal(
                async_session_factory, claim
            )

        # Verbatim sources never run MRP, regardless of which task enqueued them
        # (e.g. a dept-change re-ingest). Index raw chunks and finish.
        if source.preserve_verbatim:
            try:
                await fence_source_dispatch(session, claim, source_id=sid)
                result = await finalize_verbatim_source(session, source, tracker)
                if claim is not None:
                    await complete_source_dispatch(
                        session, claim, reason="verbatim_ready"
                    )
                    await session.commit()
                return result
            except BaseException as e:
                logger.error(f"Verbatim indexing failed for {source_id}: {e}")
                mark_source_runtime_error(
                    source,
                    error_message=str(e)[:500],
                )
                await session.commit()
                raise

        try:
            mark_source_processing(
                source,
                progress=56,
                progress_message="Extracting knowledge from document...",
            )
            await session.commit()

            registry = ProviderRegistry(session)

            kt_slug = kt_name = kt_desc = None
            if source.knowledge_type_id:
                kt = await session.get(KnowledgeType, source.knowledge_type_id)
                if kt:
                    kt_slug, kt_name, kt_desc = kt.slug, kt.name, kt.description

            result = await run_mrp_pipeline(
                session=session,
                source=source,
                full_text=source.full_text,
                tracker=tracker,
                registry=registry,
                kt_slug=kt_slug,
                kt_name=kt_name,
                kt_desc=kt_desc,
            )

            if result.get("status") == "plan_ready":
                src = await session.get(Source, sid)
                if src:
                    await fence_source_dispatch(session, claim, source_id=sid)
                    mark_source_plan_ready_for_review(src)
                    await session.commit()
                    if claim is not None:
                        await complete_source_dispatch(
                            session, claim, reason="plan_ready"
                        )
                        await session.commit()
                logger.info(f"Source {source_id} plan ready: {result.get('plan_id')}")
            elif result.get("status") == "plan_auto_approved":
                src = await session.get(Source, sid)
                if src:
                    await fence_source_dispatch(session, claim, source_id=sid)
                    job_id = result.get("job_id")
                    if isinstance(job_id, str):
                        attach_source_runtime_job(src, job_id=job_id)
                    src.auto_recover_count = 0
                    await session.commit()
                    if claim is not None:
                        await complete_source_dispatch(
                            session, claim, reason="plan_auto_approved"
                        )
                        await session.commit()
                logger.info(
                    f"Source {source_id} plan auto-approved, refine task enqueued"
                )
            else:
                if claim is not None:
                    await complete_source_dispatch(
                        session, claim, reason="map_reduce_done"
                    )
                    await session.commit()
                logger.info(f"Source {source_id} map-reduce result: {result}")

            return result

        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} map-reduce superseded: {exc}")
            try:
                if claim is not None:
                    await mark_source_dispatch_stale(
                        session, claim, reason="superseded_by_generation"
                    )
                    await session.commit()
            except Exception:
                await session.rollback()
            return
        except BaseException as e:
            logger.error(f"MAP-REDUCE failed for {source_id}: {e}")
            error_msg = str(e)[:500]
            progress_msg = f"Error: {str(e)[:200]}"

            async def _mark_error_mr() -> None:
                from cygnus.runtime.database import async_session_factory as _sf
                from cygnus.runtime.database.models import (
                    Source as _Source,
                    SourceDispatchExecution as _Dispatch,
                )

                async with _sf() as err_session:
                    src = await err_session.get(_Source, sid)
                    if src:
                        mark_source_runtime_error(
                            src,
                            error_message=error_msg,
                            progress_message=progress_msg,
                        )
                        await err_session.commit()
                if claim is not None:
                    async with _sf() as dsp_session:
                        claim_row = await dsp_session.get(_Dispatch, claim.dispatch_id)
                        if claim_row is not None:
                            await fail_source_dispatch(
                                dsp_session, claim, error=error_msg
                            )
                            await dsp_session.commit()

            try:
                await asyncio.shield(_mark_error_mr())
            except Exception:
                pass
            raise
        finally:
            if renewal_task is not None:
                renewal_task.cancel()


async def ingest_refine_task(ctx: WorkerContext, source_id: str):
    """
    arq task: Phase 3-5 of MRP pipeline (REFINE + VERIFY + COMMIT).

    Enqueued by either:
    - Plan approval API endpoint (POST /sources/{id}/plan/approve)
    - Auto-approve from ingest_map_reduce_task when mrp_auto_approve_plan=True
    """
    from cygnus.runtime.ai.mrp.pipeline import run_refine_pipeline
    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import KnowledgeType, Source

    sid = uuid.UUID(source_id)
    tracker = ProgressTracker(sid)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            logger.warning(f"Source {source_id} not found, it may have been deleted.")
            return
        if not source.full_text:
            raise ValueError(f"Source {source_id} has no full_text")

        from cygnus.runtime.source_dispatch import (
            DISPATCH_STAGE_REFINE,
            SourceDispatchSuperseded,
            claim_source_dispatch,
            complete_source_dispatch,
            fail_source_dispatch,
            fence_source_dispatch,
            mark_source_dispatch_stale,
            start_dispatch_lease_renewal,
        )

        if source.delete_requested_at is not None:
            logger.info(f"Source {source_id} is being deleted; skipping refine")
            return
        try:
            claim = await claim_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_REFINE,
                job_id=str(ctx.get("job_id") or ""),
            )
            await session.commit()
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} refine fenced at entry: {exc}")
            await session.rollback()
            return

        renewal_task = None
        if claim is not None:
            renewal_task = await start_dispatch_lease_renewal(
                async_session_factory, claim
            )

        try:
            mark_source_processing(
                source,
                progress=78,
                progress_message="Writing wiki pages...",
            )
            await session.commit()

            # Critical fence: page drafting must never run for a stale
            # generation or a tombstoned source.
            await fence_source_dispatch(session, claim, source_id=sid)

            registry = ProviderRegistry(session)

            kt_slug = kt_name = kt_desc = None
            if source.knowledge_type_id:
                kt = await session.get(KnowledgeType, source.knowledge_type_id)
                if kt:
                    kt_slug, kt_name, kt_desc = kt.slug, kt.name, kt.description

            result = await run_refine_pipeline(
                session=session,
                source=source,
                full_text=source.full_text,
                tracker=tracker,
                registry=registry,
                kt_slug=kt_slug,
                kt_name=kt_name,
                kt_desc=kt_desc,
            )

            if claim is not None:
                await complete_source_dispatch(
                    session, claim, reason="pipeline_complete"
                )
                await session.commit()

            logger.success(
                f"Source {source_id} MRP drafts complete: "
                f"+{result.get('drafts_created', 0)} create drafts, "
                f"+{result.get('edit_drafts_created', 0)} edit drafts, "
                f"{result.get('drafts_replayed', 0)} replayed"
            )
            return result

        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} refine superseded: {exc}")
            try:
                if claim is not None:
                    await mark_source_dispatch_stale(
                        session, claim, reason="superseded_by_generation"
                    )
                    await session.commit()
            except Exception:
                await session.rollback()
            return
        except BaseException as e:
            logger.error(f"REFINE failed for {source_id}: {e}")
            error_msg = str(e)[:500]
            progress_msg = f"Error: {str(e)[:200]}"

            async def _mark_error_refine() -> None:
                from cygnus.runtime.database import async_session_factory as _sf
                from cygnus.runtime.database.models import (
                    Source as _Source,
                    SourceDispatchExecution as _Dispatch,
                )

                async with _sf() as err_session:
                    src = await err_session.get(_Source, sid)
                    if src:
                        mark_source_runtime_error(
                            src,
                            error_message=error_msg,
                            progress_message=progress_msg,
                        )
                        await err_session.commit()
                if claim is not None:
                    async with _sf() as dsp_session:
                        claim_row = await dsp_session.get(_Dispatch, claim.dispatch_id)
                        if claim_row is not None:
                            await fail_source_dispatch(
                                dsp_session, claim, error=error_msg
                            )
                            await dsp_session.commit()

            try:
                await asyncio.shield(_mark_error_refine())
            except Exception:
                pass
            raise
        finally:
            if renewal_task is not None:
                renewal_task.cancel()


async def regenerate_plan_task(ctx: WorkerContext, source_id: str, user_note: str):
    """
    arq task: re-run KB reconciliation + planning call with reviewer feedback.

    Toggles plan.status: pending_review/rejected → regenerating → pending_review.
    Frontend polls GET /sources/{id}/plan to observe completion.
    """
    from cygnus.runtime.ai.mrp.reducer import reconcile_with_kb, run_planning_call
    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source, SourceCompilationPlan
    from cygnus.review import (
        fail_source_plan_regeneration,
        restore_source_plan_pending_review,
    )

    sid = uuid.UUID(source_id)

    async with async_session_factory() as session:
        from sqlalchemy.orm import selectinload

        from cygnus.runtime.source_dispatch import (
            DISPATCH_STAGE_REGENERATE_PLAN,
            SourceDispatchSuperseded,
            claim_source_dispatch,
            complete_source_dispatch,
            fail_source_dispatch,
            fence_source_dispatch,
            mark_source_dispatch_stale,
            start_dispatch_lease_renewal,
        )

        source = (
            await session.execute(
                select(Source)
                .options(selectinload(Source.knowledge_type))
                .where(Source.id == sid)
            )
        ).scalar_one_or_none()
        if not source:
            logger.warning(f"regenerate_plan_task: source {source_id} not found")
            return
        if source.delete_requested_at is not None:
            logger.info(f"Source {source_id} is being deleted; skipping regeneration")
            return
        try:
            claim = await claim_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_REGENERATE_PLAN,
                job_id=str(ctx.get("job_id") or ""),
            )
            await session.commit()
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} regeneration fenced at entry: {exc}")
            await session.rollback()
            return

        renewal_task = None
        if claim is not None:
            renewal_task = await start_dispatch_lease_renewal(
                async_session_factory, claim
            )

        plan = (
            await session.execute(
                select(SourceCompilationPlan).where(
                    SourceCompilationPlan.source_id == sid
                )
            )
        ).scalar_one_or_none()
        if not plan:
            logger.warning(f"regenerate_plan_task: no plan for source {source_id}")
            return

        plan_json = plan.plan_json or {}
        canonical_entities = plan_json.get("_entities", [])
        canonical_concepts = plan_json.get("_concepts", [])

        try:
            registry = ProviderRegistry(session)
            llm = await registry.get_llm()
            embedding_provider = None
            try:
                embedding_provider = await registry.get_embedding(task="document")
            except Exception:
                pass

            reconciliation: dict[str, dict[str, object]] = {}
            if embedding_provider and (canonical_entities or canonical_concepts):
                try:
                    reconciliation = await reconcile_with_kb(
                        session,
                        canonical_entities,
                        canonical_concepts,
                        embedding_provider,
                        source,
                        llm=llm,
                    )
                except Exception as exc:
                    logger.warning(f"regenerate_plan_task: KB reconcile failed: {exc}")

            kt_name = source.knowledge_type.name if source.knowledge_type else None
            kt_desc = (
                source.knowledge_type.description if source.knowledge_type else None
            )
            strategy = source.pipeline_strategy or "standard"

            new_plan_dict = await run_planning_call(
                llm=llm,
                source=source,
                strategy=strategy,
                canonical_entities=canonical_entities,
                canonical_concepts=canonical_concepts,
                reconciliation=reconciliation,
                kt_name=kt_name,
                kt_desc=kt_desc,
                user_note=user_note,
            )

            internal_keys = {
                k: plan_json[k]
                for k in ("_claims", "_entities", "_concepts")
                if k in plan_json
            }
            new_plan_dict.update(internal_keys)
            # The regenerated plan always carries the current persisted source
            # language tag (never inherited stale, never auto-detected).
            from cygnus.substrate.source_language import resolve_source_language

            new_plan_dict["language"] = resolve_source_language(source)

            await fence_source_dispatch(session, claim, source_id=sid)
            restore_source_plan_pending_review(plan, plan_json=new_plan_dict)
            await session.commit()
            if claim is not None:
                await complete_source_dispatch(
                    session, claim, reason="plan_regenerated"
                )
                await session.commit()
            logger.success(
                f"regenerate_plan_task: plan refreshed for source {source_id}"
            )
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} regeneration superseded: {exc}")
            try:
                if claim is not None:
                    await mark_source_dispatch_stale(
                        session, claim, reason="superseded_by_generation"
                    )
                    await session.commit()
            except Exception:
                await session.rollback()
            return
        except Exception as exc:
            logger.exception(f"regenerate_plan_task failed for {source_id}: {exc}")
            # Restore plan to pending_review so user isn't stuck on 'regenerating'
            plan2 = await session.get(SourceCompilationPlan, plan.id)
            if plan2:
                fail_source_plan_regeneration(plan2, reason=str(exc))
            if claim is not None:
                await fail_source_dispatch(
                    session,
                    claim,
                    error=str(exc)[:500],
                    reason="plan_regeneration_failed",
                )
            await session.commit()
        finally:
            if renewal_task is not None:
                renewal_task.cancel()


def _feedback_route_duration_ms(started_ns: int) -> int:
    return max(0, (monotonic_ns() - started_ns) // 1_000_000)


def _emit_feedback_route_terminal_outcome(
    claim: FeedbackRouteClaim,
    route,
    *,
    duration_ms: int,
) -> None:
    state = FeedbackRouteState(route.lifecycle_state)
    if state is FeedbackRouteState.COMPLETED:
        event = FeedbackRouteWorkerEvent.COMPLETED
        transition = "running_to_completed"
    elif state is FeedbackRouteState.BLOCKED:
        event = FeedbackRouteWorkerEvent.BLOCKED
        transition = "running_to_blocked"
    elif state is FeedbackRouteState.FAILED:
        event = FeedbackRouteWorkerEvent.FAILED
        transition = "running_to_failed"
    else:
        event = FeedbackRouteWorkerEvent.EXECUTION_ERROR
        transition = "unexpected_execution_result"
    emit_feedback_route_worker_event(
        event=event,
        route_id=claim.route_id,
        route_kind=claim.route_kind,
        transition=transition,
        attempt_count=claim.attempt_count,
        duration_ms=duration_ms,
        outcome_signal_id=route.outcome_signal_id,
        terminal_reason=route.terminal_reason,
        exception_class=(
            "UnexpectedFeedbackRouteState"
            if event is FeedbackRouteWorkerEvent.EXECUTION_ERROR
            else None
        ),
    )


async def _execute_feedback_route_claim(
    session_factory,
    claim: FeedbackRouteClaim,
    *,
    now=None,
) -> None:
    """Execute one leased route and emit only post-rollback/commit outcomes."""

    started_ns = monotonic_ns()
    execution_error: Exception | None = None
    route = None

    try:
        async with session_factory() as execution_session:
            try:
                route = await execute_feedback_route(execution_session, claim, now=now)
                await execution_session.commit()
            except FeedbackRouteLeaseLost as exc:
                await execution_session.rollback()
                emit_feedback_route_worker_event(
                    event=FeedbackRouteWorkerEvent.LEASE_LOST,
                    route_id=claim.route_id,
                    route_kind=claim.route_kind,
                    transition="execution_lease_lost",
                    attempt_count=claim.attempt_count,
                    duration_ms=_feedback_route_duration_ms(started_ns),
                    exception_class=type(exc).__name__,
                )
                return
            except Exception as exc:
                execution_error = exc
                await execution_session.rollback()
    except Exception as exc:
        emit_feedback_route_worker_event(
            event=FeedbackRouteWorkerEvent.EXECUTION_ERROR,
            route_id=claim.route_id,
            route_kind=claim.route_kind,
            transition="execution_transaction_failed",
            attempt_count=claim.attempt_count,
            duration_ms=_feedback_route_duration_ms(started_ns),
            exception_class=type(exc).__name__,
        )
        return

    if execution_error is None:
        if route is None:
            raise AssertionError("feedback route execution returned no route")
        _emit_feedback_route_terminal_outcome(
            claim,
            route,
            duration_ms=_feedback_route_duration_ms(started_ns),
        )
        return

    emit_feedback_route_worker_event(
        event=FeedbackRouteWorkerEvent.EXECUTION_ERROR,
        route_id=claim.route_id,
        route_kind=claim.route_kind,
        transition="execution_failed",
        attempt_count=claim.attempt_count,
        duration_ms=_feedback_route_duration_ms(started_ns),
        exception_class=type(execution_error).__name__,
    )
    failure_route = None
    try:
        async with session_factory() as failure_session:
            try:
                failure_route = await record_feedback_route_failure(
                    failure_session,
                    claim,
                    error=execution_error,
                    now=now,
                )
                await failure_session.commit()
            except FeedbackRouteLeaseLost as exc:
                await failure_session.rollback()
                emit_feedback_route_worker_event(
                    event=FeedbackRouteWorkerEvent.LEASE_LOST,
                    route_id=claim.route_id,
                    route_kind=claim.route_kind,
                    transition="failure_recording_lease_lost",
                    attempt_count=claim.attempt_count,
                    duration_ms=_feedback_route_duration_ms(started_ns),
                    exception_class=type(exc).__name__,
                )
                return
            except Exception as exc:
                await failure_session.rollback()
                emit_feedback_route_worker_event(
                    event=FeedbackRouteWorkerEvent.FAILURE_RECORDING_ERROR,
                    route_id=claim.route_id,
                    route_kind=claim.route_kind,
                    transition="failure_recording_failed",
                    attempt_count=claim.attempt_count,
                    duration_ms=_feedback_route_duration_ms(started_ns),
                    exception_class=type(exc).__name__,
                )
                return
    except Exception as exc:
        emit_feedback_route_worker_event(
            event=FeedbackRouteWorkerEvent.FAILURE_RECORDING_ERROR,
            route_id=claim.route_id,
            route_kind=claim.route_kind,
            transition="failure_transaction_failed",
            attempt_count=claim.attempt_count,
            duration_ms=_feedback_route_duration_ms(started_ns),
            exception_class=type(exc).__name__,
        )
        return

    if failure_route is None:
        raise AssertionError("feedback route failure recording returned no route")
    failure_state = FeedbackRouteState(failure_route.lifecycle_state)
    if failure_state is FeedbackRouteState.QUEUED:
        event = FeedbackRouteWorkerEvent.RETRY_SCHEDULED
        transition = "running_to_queued"
    elif failure_state is FeedbackRouteState.FAILED:
        event = FeedbackRouteWorkerEvent.FAILED
        transition = "running_to_failed"
    else:
        event = FeedbackRouteWorkerEvent.FAILURE_RECORDING_ERROR
        transition = "unexpected_failure_result"
    emit_feedback_route_worker_event(
        event=event,
        route_id=claim.route_id,
        route_kind=claim.route_kind,
        transition=transition,
        attempt_count=claim.attempt_count,
        duration_ms=_feedback_route_duration_ms(started_ns),
        terminal_reason=failure_route.terminal_reason,
        exception_class=type(execution_error).__name__,
    )


async def drain_feedback_routes(
    *,
    now=None,
    limit: int = _FEEDBACK_ROUTE_SWEEP_LIMIT,
    session_factory=None,
) -> int:
    """Commit one bounded claim sweep, emit outcomes, then execute each lease."""

    if not 1 <= limit <= _FEEDBACK_ROUTE_SWEEP_LIMIT:
        raise ValueError(f"limit must be between 1 and {_FEEDBACK_ROUTE_SWEEP_LIMIT}")

    if session_factory is None:
        from cygnus.runtime.database import get_async_session_factory

        session_factory = get_async_session_factory()

    async with session_factory() as claim_session:
        try:
            sweep = await claim_feedback_routes(
                claim_session,
                now=now,
                limit=limit,
            )
            await claim_session.commit()
        except Exception:
            await claim_session.rollback()
            raise

    for terminalized in sweep.terminalized:
        emit_feedback_route_worker_event(
            event=FeedbackRouteWorkerEvent.FAILED,
            route_id=terminalized.route_id,
            route_kind=terminalized.route_kind,
            transition=(
                f"{terminalized.previous_state.value}_to_"
                f"{FeedbackRouteState.FAILED.value}"
            ),
            attempt_count=terminalized.attempt_count,
            terminal_reason=terminalized.terminal_reason,
        )
    for claim in sweep.claims:
        recovered = claim.claimed_from_state is FeedbackRouteState.RUNNING
        emit_feedback_route_worker_event(
            event=(
                FeedbackRouteWorkerEvent.LEASE_RECOVERED
                if recovered
                else FeedbackRouteWorkerEvent.CLAIMED
            ),
            route_id=claim.route_id,
            route_kind=claim.route_kind,
            transition=("running_to_running" if recovered else "queued_to_running"),
            attempt_count=claim.attempt_count,
        )
    for claim in sweep.claims:
        await _execute_feedback_route_claim(
            session_factory,
            claim,
            now=now,
        )
    return len(sweep.claims)


async def sweep_feedback_routes_cron(ctx: WorkerContext) -> None:
    """Drain a small durable feedback-route batch on the worker schedule."""
    _ = ctx
    try:
        count = await drain_feedback_routes()
    except Exception as exc:
        logger.warning("Feedback route cron sweep failed class {}", type(exc).__name__)
        return
    if count:
        logger.info("Feedback route cron sweep claimed {} route(s)", count)
    # CYG-142: bounded queue lifecycle telemetry (lazy, exception-swallowed).
    try:
        from cygnus.observability import record_queue

        record_queue(queue="arq:queue", terminal_state="swept", age_seconds=None)
    except Exception as exc:  # pragma: no cover — telemetry must not break sweeps
        logger.debug("feedback sweep telemetry skipped: {}", type(exc).__name__)


async def sweep_propagation_deliveries_cron(ctx: WorkerContext) -> None:
    """Dispatch bounded pending propagation deliveries on the worker schedule.

    Claiming/executing mirrors the feedback-route sweep: one bounded claim
    batch, per-claim outcome recording, and stale in_flight lease recovery.
    Deliveries for surfaces without a configured target stay pending; no
    fabricated attempt or failure truth is written.
    """
    _ = ctx
    from cygnus.publish.delivery import drain_propagation_deliveries

    try:
        count = await drain_propagation_deliveries()
    except Exception as exc:
        logger.warning("Propagation delivery sweep failed class {}", type(exc).__name__)
        return
    if count:
        logger.info("Propagation delivery sweep dispatched {} delivery(ies)", count)


async def sweep_ai_pre_review_dispatch_cron(ctx: WorkerContext):
    """Drain committed AI-review outbox intents on the worker schedule."""
    _ = ctx
    from cygnus.review.pre_review.dispatch import sweep_ai_pre_review_dispatches

    try:
        count = await sweep_ai_pre_review_dispatches()
    except Exception as exc:
        logger.warning("AI pre-review outbox sweep failed: {}", exc)
        return
    if count:
        logger.info("AI pre-review outbox sweep leased {} intent(s)", count)


async def sweep_stuck_ai_review_cron(ctx: WorkerContext):
    """Resolve worker-death states for drafts and their delivery intents.

    A hard worker death can happen after the runner commits ``running`` but
    before it writes a verdict.  Both the draft and its exact outbox row must
    become explicit terminal truth so neither can spin forever.
    """
    _ = ctx
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, update

    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import (
        WikiDraftAiPreReviewDispatch,
        WikiPageDraft,
    )

    timeout_sec = max(int(settings.worker_job_timeout) * 2, 1800)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=timeout_sec)

    async with async_session_factory() as session:
        stuck_ids = list(
            (
                await session.execute(
                    select(WikiPageDraft.id).where(
                        WikiPageDraft.ai_check_status == "running",
                        or_(
                            WikiPageDraft.updated_at < cutoff,
                            WikiPageDraft.updated_at.is_(None),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not stuck_ids:
            return

        result = cast(
            CursorResult[tuple[object, ...]],
            await session.execute(
                update(WikiPageDraft)
                .where(
                    WikiPageDraft.id.in_(stuck_ids),
                    WikiPageDraft.ai_check_status == "running",
                )
                .values(ai_check_status="skipped")
            ),
        )
        await session.execute(
            update(WikiDraftAiPreReviewDispatch)
            .where(
                WikiDraftAiPreReviewDispatch.draft_id.in_(stuck_ids),
                WikiDraftAiPreReviewDispatch.dispatch_status == "running",
            )
            .values(
                dispatch_status="failed",
                terminal_reason="worker_timeout",
                last_error="worker exceeded the AI pre-review timeout",
                lease_expires_at=None,
                completed_at=now,
            )
        )
        await session.commit()
        n = result.rowcount or 0
        if n:
            logger.warning(
                f"sweep_stuck_ai_review_cron: reset {n} draft(s) stuck in "
                f"'running' for >{timeout_sec}s"
            )


async def sweep_stuck_processing_cron(ctx: WorkerContext):
    """Periodic safety net: flip any Source stuck in status='processing' for
    longer than 2x the worker job_timeout back to 'error'.

    A source gets stuck when the worker process dies AFTER writing
    status='processing' but BEFORE finishing the pipeline — OOM, SIGKILL,
    container restart, hung LLM call. The in-worker try/except can't catch
    process death so the source row stays at 'processing' indefinitely with
    no recovery path (the retry endpoint only accepts 'error' / 'plan_ready').

    This sweep does NOT auto-enqueue a retry — it only marks the row 'error'
    so the user sees the Retry button. Auto-retrying here would loop forever
    if the failure is deterministic (bad provider key, malformed file).
    Source.auto_recover_count tracks consecutive sweeps; the retry API blocks
    once it crosses settings.max_auto_recover_attempts so even manual retries
    are gated against token-burning loops.

    Uses updated_at (bumped by ProgressTracker on every progress update) so
    legitimately slow MAP-phase LLM calls don't get swept while still
    producing progress.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source

    timeout_sec = max(int(settings.worker_job_timeout) * 2, 1800)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_sec)

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Source).where(
                        Source.status == "processing",
                        or_(Source.updated_at < cutoff, Source.updated_at.is_(None)),
                    )
                )
            )
            .scalars()
            .all()
        )

        if not rows:
            return

        for src in rows:
            src.auto_recover_count = (src.auto_recover_count or 0) + 1
            src.status = "error"
            attempts = src.auto_recover_count
            cap = settings.max_auto_recover_attempts
            if attempts >= cap:
                error_message = (
                    f"Worker died with no progress for >{timeout_sec // 60} min "
                    f"on {attempts} consecutive attempts (cap={cap}). Retry is "
                    f"blocked — check LLM provider config and source file, then "
                    f"ask an admin to reset auto_recover_count."
                )
            else:
                error_message = (
                    f"Worker died with no progress for >{timeout_sec // 60} min. "
                    f"Press Retry to try again ({attempts}/{cap} auto-recoveries used)."
                )
            mark_source_runtime_error(src, error_message=error_message)
            src.auto_recover_count = attempts

        await session.commit()
        logger.warning(
            f"sweep_stuck_processing_cron: flipped {len(rows)} source(s) "
            f"from 'processing' → 'error' (stuck >{timeout_sec}s)"
        )
        # CYG-142: bounded terminal-state telemetry (lazy, exception-swallowed).
        try:
            from cygnus.observability import record_queue

            record_queue(
                queue="arq:queue",
                terminal_state="error",
                attempts=len(rows),
            )
        except Exception as exc:  # pragma: no cover — telemetry must not break sweeps
            logger.debug("stuck-processing telemetry skipped: {}", type(exc).__name__)


async def sweep_source_dispatch_cron(ctx: WorkerContext) -> None:
    """Reconcile committed source dispatch executions on the worker schedule.

    Re-enqueues pending/expired-lease executions with their deterministic ARQ
    job ids and fences executions superseded by a newer generation or a source
    deletion.
    """
    _ = ctx
    try:
        from cygnus.runtime.source_dispatch import sweep_source_dispatches

        count = await sweep_source_dispatches()
    except Exception as exc:
        logger.warning("source dispatch cron sweep failed: {}", exc)
        return
    if count:
        logger.info("source dispatch cron sweep leased {} execution(s)", count)
    # CYG-142: bounded queue lifecycle telemetry (lazy, exception-swallowed).
    try:
        from cygnus.observability import record_queue

        record_queue(
            queue="arq:queue",
            terminal_state="reconciled",
            attempts=count,
        )
    except Exception as exc:  # pragma: no cover — telemetry must not break sweeps
        logger.debug("source dispatch sweep telemetry skipped: {}", type(exc).__name__)


async def sweep_source_deletions_cron(ctx: WorkerContext) -> None:
    """Drive database-led source deletions on the worker schedule."""
    _ = ctx
    try:
        from cygnus.runtime.source_deletion import sweep_source_deletions

        count = await sweep_source_deletions()
    except Exception as exc:
        logger.warning("source deletion cron sweep failed: {}", exc)
        return
    if count:
        logger.info("source deletion cron sweep processed {} intent(s)", count)
    # CYG-142: bounded queue lifecycle telemetry (lazy, exception-swallowed).
    try:
        from cygnus.observability import record_queue

        record_queue(
            queue="arq:queue",
            terminal_state="deleted",
            attempts=count,
        )
    except Exception as exc:  # pragma: no cover — telemetry must not break sweeps
        logger.debug("source deletion sweep telemetry skipped: {}", type(exc).__name__)


async def cleanup_orphan_awaiting_approval_cron(ctx: WorkerContext):
    """Delete sources stuck in status='awaiting_approval' longer than the TTL.

    A source enters this state after extraction when token count exceeds the
    auto-approve threshold. If a human never approves or cancels, the MinIO
    object + DB row become orphans. This sweep commits the database-led
    tombstone + cleanup intent for each stale source; the deletion sweeper
    removes the durable storage objects and the DB row with idempotent retries.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source
    from cygnus.runtime.source_deletion import request_source_deletion

    ttl_hours = max(1, int(settings.extraction_approval_ttl_hours))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Source).where(
                        Source.status == "awaiting_approval",
                        Source.updated_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )

        for src in rows:
            try:
                await request_source_deletion(session, src)
            except Exception as exc:
                logger.warning(
                    f"cleanup_orphan: deletion intent failed for {src.id}: {exc}"
                )

        if rows:
            await session.commit()
            logger.info(
                f"cleanup_orphan_awaiting_approval_cron: tombstoned {len(rows)} "
                f"source(s) older than {ttl_hours}h"
            )


async def daily_stats_rollup_cron(ctx: WorkerContext):
    """
    Cronjob: recompute admin Statistics rollups for yesterday (UTC).

    Idempotent — re-running overwrites previous rows via the unique constraint on
    (date, metric_key, dimensions_hash). Failures in one section don't stop the others.
    """
    from datetime import datetime, timedelta, timezone

    from cygnus.runtime.services.stats_aggregator import run_daily_rollup

    target = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    result = await run_daily_rollup(target)
    logger.info(f"daily_stats_rollup_cron: {target} -> {result}")


async def caption_images_task(ctx: WorkerContext, source_id: str):
    """
    arq task: vision-caption all SourceImage rows for a source.

    Runs independently from the MRP pipeline — enqueued by ingest_file_task
    immediately after images are persisted to DB. Updates each row's caption
    field as soon as the vision call returns, so captions are available by the
    time ingest_refine_task writes wiki pages.

    Each image opens its own DB session for the UPDATE so concurrent coroutines
    never share session state.
    """
    from sqlalchemy import update as sa_update

    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.database import async_session_factory
    from cygnus.runtime.database.models import Source, SourceImage
    from cygnus.runtime.services.storage_service import storage_service

    sid = uuid.UUID(source_id)

    # Load vision provider and image rows in a short-lived session, then close it.
    from cygnus.runtime.source_dispatch import (
        DISPATCH_STAGE_MAP_REDUCE,
        DISPATCH_STAGE_POST_EXTRACTION,
        SourceDispatchSuperseded,
        claim_source_dispatch,
        complete_source_dispatch,
        enqueue_dispatch_execution,
        record_source_dispatch,
        start_dispatch_lease_renewal,
    )

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            logger.warning(f"caption_images_task: source {source_id} not found")
            return
        if source.delete_requested_at is not None:
            logger.info(f"Source {source_id} is being deleted; skipping captions")
            return
        try:
            claim = await claim_source_dispatch(
                session,
                source,
                stage=DISPATCH_STAGE_POST_EXTRACTION,
                job_id=str(ctx.get("job_id") or ""),
            )
            await session.commit()
        except SourceDispatchSuperseded as exc:
            logger.info(f"Source {source_id} captioning fenced at entry: {exc}")
            await session.rollback()
            return

        renewal_task = None
        if claim is not None:
            renewal_task = await start_dispatch_lease_renewal(
                async_session_factory, claim
            )

        registry = ProviderRegistry(session)
        vision_provider = await registry.get_vision()
        if not vision_provider:
            logger.info("caption_images_task: no vision provider configured, skipping")
            if renewal_task is not None:
                renewal_task.cancel()
            return

        rows = (
            (
                await session.execute(
                    select(SourceImage).where(SourceImage.source_id == sid)
                )
            )
            .scalars()
            .all()
        )

        # Snapshot only the fields we need — session closes after this block.
        image_records = [(row.id, row.minio_key, row.content_type) for row in rows]

    if not image_records:
        return

    logger.info(
        f"caption_images_task: captioning {len(image_records)} images for {source_id}"
    )

    MAX_CONCURRENCY = 4
    PER_IMAGE_TIMEOUT = 120
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    total = len(image_records)

    async def _caption_one(
        image_id, minio_key: str, content_type: str, idx: int
    ) -> None:
        async with sem:
            try:
                img_bytes = storage_service.download_file(minio_key)
                vision_prompt = (
                    "Describe this image concisely in 1-3 sentences. "
                    "Focus on what is shown (diagrams, charts, photos, illustrations) "
                    "and what information it conveys. Be specific — mention key elements, "
                    "labels, numbers, or steps visible in the image. Do not start with "
                    "'Based on the image' or similar filler phrases."
                )
                caption = await asyncio.wait_for(
                    vision_provider.analyze_image(
                        img_bytes, content_type, prompt=vision_prompt
                    ),
                    timeout=PER_IMAGE_TIMEOUT,
                )
                # Each image gets its own session — no concurrent session access.
                async with async_session_factory() as upd_session:
                    await upd_session.execute(
                        sa_update(SourceImage)
                        .where(SourceImage.id == image_id)
                        .values(caption=caption)
                    )
                    await upd_session.commit()
                logger.info(
                    f"caption_images_task: image {idx}/{total} done for {source_id}"
                )
            except Exception as e:
                logger.warning(
                    f"caption_images_task: failed {minio_key}: {type(e).__name__}: {e}"
                )

    await asyncio.gather(
        *[
            _caption_one(img_id, mkey, ctype, idx)
            for idx, (img_id, mkey, ctype) in enumerate(image_records, 1)
        ]
    )
    logger.success(f"caption_images_task: {total} images processed for {source_id}")

    # Bake captions into source.full_text so MAP-phase LLM sees ![<caption>](image://uuid)
    # instead of the empty ![](image://uuid) marker, then chain into MRP.
    import re

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            return
        rows = (
            (
                await session.execute(
                    select(SourceImage).where(SourceImage.source_id == sid)
                )
            )
            .scalars()
            .all()
        )
        caption_by_id = {
            str(r.id): (r.caption or "").replace("\n", " ").strip() for r in rows
        }

        if source.full_text and caption_by_id:

            def _sub(match: re.Match[str]) -> str:
                uid = match.group(1)
                cap = caption_by_id.get(uid, "")
                return f"![{cap}](image://{uid})"

            # Replace any marker (empty or already-captioned) so re-runs are idempotent.
            new_text = re.sub(
                r"!\[[^\]]*\]\(image://([0-9a-fA-F-]+)\)", _sub, source.full_text
            )
            if new_text != source.full_text:
                source.full_text = new_text
                await session.commit()
                logger.info(
                    f"caption_images_task: refreshed full_text with {len(caption_by_id)} captions for {source_id}"
                )

    # Chain into MAP-REDUCE (only now that captions are baked in) through the
    # durable outbox so the handoff carries a deterministic ARQ job id.
    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source or source.delete_requested_at is not None:
            if renewal_task is not None:
                renewal_task.cancel()
            return
        dispatch_row, _generation, _job_id = await record_source_dispatch(
            session,
            source,
            stage=DISPATCH_STAGE_MAP_REDUCE,
            task_name="ingest_map_reduce_task",
            task_args=(source_id,),
            new_generation=False,
        )
        await session.flush()
        dispatch_ok = await enqueue_dispatch_execution(session, dispatch_row)
        job_id = dispatch_row.job_id if dispatch_ok else None
        mark_source_post_extraction_resume(
            source,
            has_images=False,
            job_id=job_id,
            progress=55,
        )
        if claim is not None:
            await complete_source_dispatch(session, claim, reason="captions_chained")
        await session.commit()
    if renewal_task is not None:
        renewal_task.cancel()
    logger.info(f"caption_images_task: enqueued ingest_map_reduce_task for {source_id}")


async def ai_pre_review_draft_task(
    ctx: WorkerContext,
    draft_id: str,
    expected_round: Optional[int] = None,
    expected_version: Optional[int] = None,
) -> None:
    """Run all four AI pre-review layers on one exact draft content revision.

    Jobs without both durable revision fields are rejected. Migration backfill
    and the durable sweep replay any still-active revision with its deterministic
    ARQ job ID rather than letting a legacy job write an unversioned verdict.
    """
    from cygnus.review.pre_review import run_async_checks

    _ = ctx
    await run_async_checks(
        draft_id,
        expected_round=expected_round,
        expected_version=expected_version,
    )


class WorkerSettings:
    """arq worker configuration."""

    functions = [
        _track_heartbeat_job(ingest_file_task),
        _track_heartbeat_job(ingest_url_task),
        arq_func(_track_heartbeat_job(caption_images_task), timeout=3600),
        _track_heartbeat_job(ingest_map_reduce_task),
        _track_heartbeat_job(ingest_refine_task),
        _track_heartbeat_job(regenerate_plan_task),
        _track_heartbeat_job(reembed_all_pages_task),
        _track_heartbeat_job(ai_pre_review_draft_task),
    ]
    redis_settings = _get_redis_settings()
    job_serializer = queue_serialize
    job_deserializer = queue_deserialize
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    max_tries = 3
    retry_delay = 10
    health_check_interval = 30
    # On SIGTERM/SIGINT: stop claiming new jobs, wait this long for in-flight
    # work to finish, then cancel.  Canceled jobs keep their leases and return
    # to the queue once the lease expires, so work is neither lost nor duped.
    job_completion_wait = settings.worker_drain_grace_seconds

    cron_jobs = [
        cron(daily_stats_rollup_cron, hour=2, minute=0),
        # Every 5 minutes — recover committed pre-review intents after an API
        # crash or an enqueue acknowledgement window.
        cron(
            sweep_ai_pre_review_dispatch_cron,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        # Every 5 minutes, offset from the pre-review outbox sweep so feedback
        # recovery remains bounded without competing for the same cron minute.
        cron(
            sweep_feedback_routes_cron,
            minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57},
        ),
        # Every 5 minutes — dispatch pending propagation deliveries with bounded
        # retries and dead-letter exhaustion.
        cron(
            sweep_propagation_deliveries_cron,
            minute={4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59},
        ),
        # Every 10 minutes — quick recovery from stuck 'running' AI reviews
        # caused by hard worker death (OOM, SIGKILL, container restart).
        cron(sweep_stuck_ai_review_cron, minute={0, 10, 20, 30, 40, 50}),
        # Every 10 minutes — recover sources stuck at 'processing' from the
        # same class of failures. Flips to 'error' only; no auto-retry.
        cron(sweep_stuck_processing_cron, minute={5, 15, 25, 35, 45, 55}),
        # Hourly: delete orphan sources stuck in awaiting_approval.
        cron(cleanup_orphan_awaiting_approval_cron, minute=15),
        # Every 5 minutes — recover source dispatch executions: re-enqueue
        # pending/expired-lease handoffs, fence superseded generations.
        cron(
            sweep_source_dispatch_cron,
            minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56},
        ),
        # Every 2 minutes — drive database-led source deletions to completion
        # (idempotent storage cleanup, then terminal DB removal).
        cron(
            sweep_source_deletions_cron,
            minute={
                0,
                2,
                4,
                6,
                8,
                10,
                12,
                14,
                16,
                18,
                20,
                22,
                24,
                26,
                28,
                30,
                32,
                34,
                36,
                38,
                40,
                42,
                44,
                46,
                48,
                50,
                52,
                54,
                56,
                58,
            },
        ),
    ]

    @staticmethod
    async def on_startup(ctx: WorkerContext):
        heartbeat = await start_worker_heartbeat(
            ctx,
            role=DEFAULT_WORKER_ROLE,
            queue=DEFAULT_WORKER_QUEUE,
            settings=settings,
        )
        logger.info("arq worker started — listening for ingestion jobs...")
        from cygnus.review.pre_review.dispatch import sweep_ai_pre_review_dispatches

        try:
            count = await sweep_ai_pre_review_dispatches()
        except Exception as exc:
            logger.warning("AI pre-review startup sweep failed: {}", exc)
        else:
            if count:
                logger.info("AI pre-review startup sweep leased {} intent(s)", count)

        try:
            count = await drain_feedback_routes()
        except Exception as exc:
            logger.warning(
                "Feedback route startup sweep failed class {}", type(exc).__name__
            )
        else:
            if count:
                logger.info("Feedback route startup sweep claimed {} route(s)", count)

        from cygnus.publish.delivery import (
            delivery_targets_ready,
            drain_propagation_deliveries,
        )

        try:
            delivery_route_ready = await delivery_targets_ready()
        except Exception as exc:
            logger.warning(
                "Propagation delivery startup readiness probe failed class {}",
                type(exc).__name__,
            )
        else:
            if not delivery_route_ready:
                logger.warning(
                    "Propagation delivery startup sweep skipped; route is unavailable"
                )
            else:
                try:
                    count = await drain_propagation_deliveries()
                except Exception as exc:
                    logger.warning(
                        "Propagation delivery startup sweep failed class {}",
                        type(exc).__name__,
                    )
                else:
                    if count:
                        logger.info(
                            "Propagation delivery startup sweep dispatched {} delivery(ies)",
                            count,
                        )

        await heartbeat.mark_ready()
        # CYG-142 telemetry: publish heartbeat freshness for the
        # cygnus_worker_heartbeat gauge (lazy, exception-swallowed).
        try:
            from cygnus.observability import record_worker_heartbeat

            record_worker_heartbeat(role=DEFAULT_WORKER_ROLE, fresh=True)
        except (
            Exception
        ) as exc:  # pragma: no cover — observability must not break startup
            logger.debug("worker heartbeat telemetry skipped: {}", type(exc).__name__)

    @staticmethod
    async def on_shutdown(ctx: WorkerContext):
        logger.info("arq worker shutting down...")
        try:
            from cygnus.observability import record_worker_drain

            record_worker_drain(role=DEFAULT_WORKER_ROLE)
        except (
            Exception
        ) as exc:  # pragma: no cover — observability must not break shutdown
            logger.debug("worker drain telemetry skipped: {}", type(exc).__name__)
        await stop_worker_heartbeat(ctx)


class SkillWorkerSettings:
    """arq worker configuration dedicated to Skills."""

    functions = [
        _track_heartbeat_job(ingest_skill_task),
        _track_heartbeat_job(delete_skill_task),
    ]
    queue_name = "skills_queue"
    redis_settings = _get_redis_settings()
    job_serializer = queue_serialize
    job_deserializer = queue_deserialize
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    max_tries = 3
    retry_delay = 10
    health_check_interval = 30
    # Same drain contract as WorkerSettings (see job_completion_wait there).
    job_completion_wait = settings.worker_drain_grace_seconds

    cron_jobs = [cron(cleanup_temp_uploads_cron, minute=0)]

    @staticmethod
    async def on_startup(ctx: WorkerContext):
        heartbeat = await start_worker_heartbeat(
            ctx,
            role=SKILLS_WORKER_ROLE,
            queue=SKILLS_WORKER_QUEUE,
            settings=settings,
        )
        logger.info("arq skills worker started — listening for skill jobs...")
        await heartbeat.mark_ready()
        # CYG-142 telemetry: publish heartbeat freshness for the
        # cygnus_worker_heartbeat gauge (lazy, exception-swallowed).
        try:
            from cygnus.observability import record_worker_heartbeat

            record_worker_heartbeat(role=SKILLS_WORKER_ROLE, fresh=True)
        except (
            Exception
        ) as exc:  # pragma: no cover — observability must not break startup
            logger.debug("skills heartbeat telemetry skipped: {}", type(exc).__name__)

    @staticmethod
    async def on_shutdown(ctx: WorkerContext):
        logger.info("arq skills worker shutting down...")
        try:
            from cygnus.observability import record_worker_drain

            record_worker_drain(role=SKILLS_WORKER_ROLE)
        except (
            Exception
        ) as exc:  # pragma: no cover — observability must not break shutdown
            logger.debug("skills drain telemetry skipped: {}", type(exc).__name__)
        await stop_worker_heartbeat(ctx)


_WORKER_SETTINGS = {
    "WorkerSettings": WorkerSettings,
    "SkillWorkerSettings": SkillWorkerSettings,
}


def run_worker(settings_name: str = "WorkerSettings") -> None:
    """Run one worker role under the graceful drain runner.

    This is the docker-compose entry point: SIGTERM publishes a ``draining``
    heartbeat, stops claiming new jobs, waits ``worker_drain_grace_seconds``
    for in-flight work, preserves recoverable leases, then closes resources.
    """
    from cygnus.runtime.drain import run_graceful_worker

    settings_cls = _WORKER_SETTINGS[settings_name]
    run_graceful_worker(settings_cls)


if __name__ == "__main__":
    import sys

    run_worker(sys.argv[1] if len(sys.argv) > 1 else "WorkerSettings")
