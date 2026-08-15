"""
MRP Pipeline orchestrator.

Two entry points:
  run_mrp_pipeline()     — Phase 0-2 (MAP + REDUCE). Ends at plan_review status.
                           If mrp_auto_approve_plan=True, immediately enqueues
                           ingest_refine_task; otherwise waits for human approval.

  run_refine_pipeline()  — Phase 3-5 (REFINE + VERIFY + COMMIT).
                           Called from ingest_refine_task after plan approval.

Phase 5 validates complete compiler output and stages deterministic review
drafts. It never materialises, embeds, approves, or publishes WikiPage rows.
"""

import uuid
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.ai.mrp.mapper import run_map_phase
from cygnus.runtime.ai.mrp.reducer import run_reduce_phase
from cygnus.runtime.ai.mrp.verifier import run_verify_phase
from cygnus.runtime.ai.mrp.writer import PageWriteResult, run_refine_phase
from cygnus.runtime.source_state import mark_source_ready
from cygnus.runtime.utils.progress import ProgressTracker

# ---------------------------------------------------------------------------
# Compile completeness governance
# ---------------------------------------------------------------------------

# Marker substrings that identify a fabricated/placeholder draft body. The
# compiler never produces these anymore — they are recognized so stale drafts
# from older runs (or a resumed plan) are still rejected by the commit gate.
_PLACEHOLDER_MARKERS = (
    "(Page generation failed",
    "(content generation incomplete",
)


class CompileIncompleteError(Exception):
    """Raised when MRP compilation units failed or went missing.

    Carries ``failures``: a sorted list of machine-actionable failure dicts
    with keys ``unit`` / ``phase`` / ``status`` / ``error_type`` / ``message`` /
    ``retryable``. While any failure is present the compilation plan MUST NOT
    be marked done and the source MUST NOT be marked ready.
    """

    def __init__(self, failures: list[dict], *, summary: Optional[str] = None):
        self.failures = list(failures)
        super().__init__(summary or _summarize_failures(self.failures))


class SourceScopeResolutionError(RuntimeError):
    """Raised when persisted source scope cannot safely target compiler drafts."""


def _summarize_failures(failures: list[dict]) -> str:
    units = ", ".join(str(f.get("unit", "?")) for f in failures[:5])
    more = f" (+{len(failures) - 5} more)" if len(failures) > 5 else ""
    return (
        f"MRP compilation incomplete: {len(failures)} failed/missing unit(s)"
        f"{(': ' + units) if units else ''}{more}"
    )


def is_placeholder_content(content_md: str) -> bool:
    """True when a page body is empty or a placeholder draft.

    Placeholder drafts carry no real content and must never reach the wiki;
    the commit gate rejects them so "no incomplete/placeholder draft can exist".
    """
    body = (content_md or "").strip()
    if not body:
        return True
    return any(marker in body for marker in _PLACEHOLDER_MARKERS)


def _planned_pages(plan_dict: dict) -> list[dict]:
    """Return the plan's page specs sorted deterministically by slug/title."""
    pages = list(plan_dict.get("pages") or [])
    return sorted(
        pages, key=lambda p: (str(p.get("slug", "")), str(p.get("title", "")))
    )


def validate_compile_completeness(
    plan_dict: dict,
    page_results: list[PageWriteResult],
    *,
    full_text: str = "",
    chunk_failures: Optional[list[dict]] = None,
) -> list[dict]:
    """Validate that every planned page/scope has a non-placeholder,
    evidence-backed result.

    Returns a sorted list of structured failure dicts; an empty list means the
    compilation is complete and may be drafted via the shared write service.
    A failed or missing MAP / REFINE unit, a placeholder/empty body, or a page
    with no assembled source evidence all count as incomplete.
    """
    from cygnus.runtime.ai.mrp.writer import assemble_evidence

    failures: list[dict] = []

    for failure in chunk_failures or ():
        failures.append(dict(failure))

    results_by_slug = {pr.slug: pr for pr in page_results}
    claims = plan_dict.get("_claims") or []

    for page in _planned_pages(plan_dict):
        slug = str(page.get("slug", ""))
        if not slug:
            # Malformed plan entry without a slug cannot be verified; the plan
            # itself needs regeneration rather than a draft.
            failures.append(
                {
                    "unit": "refine:page:<missing-slug>",
                    "phase": "refine",
                    "status": "error",
                    "error_type": "missing_unit",
                    "message": "plan page entry has no slug",
                    "retryable": False,
                }
            )
            continue

        pr = results_by_slug.get(slug)
        if pr is None:
            failures.append(
                {
                    "unit": f"refine:page:{slug}",
                    "phase": "refine",
                    "status": "error",
                    "error_type": "missing_unit",
                    "message": f"planned page '{slug}' has no generation result",
                    "retryable": True,
                }
            )
            continue
        if pr.failure is not None:
            failures.append(dict(pr.failure))
            continue
        if is_placeholder_content(pr.content_md):
            failures.append(
                {
                    "unit": f"refine:page:{slug}",
                    "phase": "refine",
                    "status": "error",
                    "error_type": "placeholder_content",
                    "message": "generated page content is empty or a placeholder draft",
                    "retryable": True,
                }
            )
            continue

        evidence = assemble_evidence(page, claims, full_text)
        if not evidence:
            failures.append(
                {
                    "unit": f"refine:page:{slug}",
                    "phase": "refine",
                    "status": "error",
                    "error_type": "no_evidence",
                    "message": "planned page has no evidence-backed claims from the source",
                    "retryable": False,
                }
            )

    failures.sort(
        key=lambda f: (
            str(f.get("phase", "")),
            str(f.get("unit", "")),
            str(f.get("error_type", "")),
        )
    )
    return failures


async def _persist_plan_failures(
    session: AsyncSession,
    plan,
    failures: list[dict],
) -> None:
    """Persist structured failures onto the plan without completing it."""
    if plan is None:
        return
    plan_json = dict(plan.plan_json or {})
    plan_json["_failures"] = failures
    plan.plan_json = plan_json
    await session.commit()


async def _collect_map_failures(
    session: AsyncSession,
    source_id: uuid.UUID,
    full_text: str,
    *,
    outline_json: Optional[list],
    strategy: Optional[str],
) -> list[dict]:
    """Return structured failures for MAP units that failed or went missing.

    A unit is failed when its SourceChunkExtract row is not 'done' after MAP
    (status 'error' or 'pending'); it is missing when no row exists for an
    expected chunk index. Sorted by unit for determinism.
    """
    from cygnus.runtime.ai.mrp.mapper import build_chunks
    from cygnus.runtime.database.models import SourceChunkExtract

    rows = (
        (
            await session.execute(
                select(SourceChunkExtract).where(
                    SourceChunkExtract.source_id == source_id
                )
            )
        )
        .scalars()
        .all()
    )
    rows_by_idx = {r.chunk_index: r for r in rows}

    expected_chunks = []
    if strategy and full_text:
        expected_chunks = build_chunks(full_text, outline_json, strategy)

    failures: list[dict] = []
    for chunk in expected_chunks:
        row = rows_by_idx.get(chunk.index)
        if row is None:
            failures.append(
                {
                    "unit": f"map:chunk:{chunk.index}",
                    "phase": "map",
                    "status": "error",
                    "error_type": "missing_unit",
                    "message": "chunk row missing after MAP",
                    "retryable": True,
                }
            )
        elif row.status != "done":
            failures.append(
                {
                    "unit": f"map:chunk:{chunk.index}",
                    "phase": "map",
                    "status": "error",
                    "error_type": "generation_failed",
                    "message": (row.error_message or f"MAP chunk status={row.status}")[
                        :500
                    ],
                    "retryable": True,
                }
            )
    failures.sort(key=lambda f: f["unit"])
    return failures


async def _resolve_wiki_scopes(
    session: AsyncSession, source
) -> list[tuple[str, Optional[uuid.UUID]]]:
    """Resolve source scope into exact draft targets without global fallback.

    An explicit department/project scope is authoritative and must be complete.
    A global source may fan out to its persisted department links; a malformed
    scoped source (missing scope id or required department link) fails closed
    so compiler output can never become a global draft by accident.
    """
    from cygnus.runtime.database.models import Source as SourceModel
    from cygnus.runtime.database.models import SourceDepartment

    row = (
        await session.execute(
            select(SourceModel.scope_type, SourceModel.scope_id).where(
                SourceModel.id == source.id
            )
        )
    ).one_or_none()
    if row is None:
        raise SourceScopeResolutionError(f"source_id={source.id} no longer exists")
    scope_type, scope_id = row
    department_ids = tuple(
        row[0]
        for row in (
            await session.execute(
                select(SourceDepartment.department_id)
                .where(SourceDepartment.source_id == source.id)
                .order_by(SourceDepartment.department_id)
            )
        ).all()
    )

    if scope_type == "department":
        if scope_id is None:
            raise SourceScopeResolutionError(
                f"source_id={source.id} has department scope without scope_id"
            )
        if scope_id not in department_ids:
            raise SourceScopeResolutionError(
                f"source_id={source.id} department scope is missing its SourceDepartment link"
            )
        return [("department", scope_id)]
    if scope_type == "project":
        if scope_id is None:
            raise SourceScopeResolutionError(
                f"source_id={source.id} has project scope without scope_id"
            )
        return [("project", scope_id)]
    if scope_type != "global" or scope_id is not None:
        raise SourceScopeResolutionError(
            f"source_id={source.id} has invalid scope identity {scope_type}:{scope_id}"
        )
    if department_ids:
        return [("department", department_id) for department_id in department_ids]
    return [("global", None)]


# ---------------------------------------------------------------------------
# Phase 5 — COMMIT
# ---------------------------------------------------------------------------


async def run_commit_phase(
    session: AsyncSession,
    source,
    page_results: list[PageWriteResult],
    plan,
    embedding_provider,
    embedding_spec,
    kt_slug: Optional[str],
    tracker: ProgressTracker,
    full_text: str = "",
) -> dict:
    """Persist complete compiler output as reviewable drafts, never wiki pages.

    The compile plan is complete only when every result has been staged as a
    deterministic draft. Approval materialises/updates the page later; a
    separate governed publish action is still required before retrieval can
    see the approved version. Any staging failure rolls back every draft from
    this attempt and leaves both plan and source non-ready.
    """
    from cygnus.review.contributions import stage_compilation_wiki_draft
    from cygnus.runtime.ai.mrp.merger import merge_page_content
    from cygnus.runtime.database.models import Source
    from cygnus.runtime.services import wiki_service
    from cygnus.substrate.source_language import resolve_source_language

    # Keep the established signature while intentionally removing direct page
    # embedding: no page exists until a reviewer approves the draft.
    _ = embedding_provider, embedding_spec

    failures = validate_compile_completeness(
        plan.plan_json if plan is not None else {},
        page_results,
        full_text=full_text,
    )
    if failures:
        logger.error(
            f"MRP draft staging blocked: {len(failures)} failed/missing unit(s) "
            f"for source={source.id} — plan stays non-done, source stays non-ready"
        )
        await _persist_plan_failures(session, plan, failures)
        raise CompileIncompleteError(failures)

    source_language = resolve_source_language(source)
    wiki_scopes = await _resolve_wiki_scopes(session, source)
    commit_failures: list[dict] = []
    draft_ids: list[str] = []
    create_drafts = 0
    edit_drafts = 0
    replayed_drafts = 0

    merge_llm = None
    try:
        from cygnus.runtime.ai.registry import ProviderRegistry

        merge_llm = await ProviderRegistry(session).get_llm()
    except Exception as exc:
        logger.warning(f"MRP draft staging: could not load merge LLM: {exc}")

    await tracker.update(
        95,
        f"Staging {len(page_results)} compiler drafts ({len(wiki_scopes)} scope(s))...",
    )

    for scope_type, scope_id in wiki_scopes:
        for result in page_results:
            try:
                existing_page = await wiki_service.get_page_by_slug(
                    session,
                    result.slug,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    language=source_language,
                )
                final_content = result.content_md
                if (
                    existing_page is not None
                    and existing_page.content_md
                    and merge_llm is not None
                    and str(source.id)
                    not in {str(item) for item in (existing_page.source_ids or ())}
                    and len(existing_page.content_md.strip()) > 100
                ):
                    final_content = await merge_page_content(
                        merge_llm,
                        existing_page.content_md,
                        result.content_md,
                        result.slug,
                    )

                draft, created = await stage_compilation_wiki_draft(
                    session,
                    source=source,
                    page=existing_page,
                    slug=result.slug,
                    title=result.title,
                    page_type=result.page_type,
                    content_md=final_content,
                    summary=result.summary,
                    knowledge_type_slug=kt_slug,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    language=source_language,
                    compiler="mrp",
                )
                draft_ids.append(str(draft.id))
                if not created:
                    replayed_drafts += 1
                elif existing_page is None:
                    create_drafts += 1
                else:
                    edit_drafts += 1
            except Exception as exc:
                logger.error(
                    f"MRP draft staging failed for '{result.slug}' "
                    f"scope={scope_type}: {exc}"
                )
                commit_failures.append(
                    {
                        "unit": f"commit:page:{result.slug}",
                        "phase": "commit",
                        "status": "error",
                        "error_type": "draft_staging_failed",
                        "message": f"scope={scope_type}: {type(exc).__name__}: {str(exc)}"[
                            :500
                        ],
                        "retryable": True,
                    }
                )

    if commit_failures:
        await session.rollback()
        await _persist_plan_failures(session, plan, commit_failures)
        raise CompileIncompleteError(commit_failures)

    if plan is not None:
        plan_json = dict(plan.plan_json or {})
        plan_json["_compiler_draft_ids"] = sorted(set(draft_ids))
        plan.plan_json = plan_json
        plan.status = "done"

    src = await session.get(Source, source.id)
    if src:
        src.pipeline_phase = "commit"
        mark_source_ready(src)

    await session.commit()
    logger.success(
        f"MRP draft staging complete: +{create_drafts} create drafts, "
        f"+{edit_drafts} edit drafts, {replayed_drafts} replayed "
        f"for source={source.id}"
    )
    return {
        "drafts_created": create_drafts,
        "edit_drafts_created": edit_drafts,
        "drafts_replayed": replayed_drafts,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_plan(session: AsyncSession, source_id: uuid.UUID):
    """Load SourceCompilationPlan for a source."""
    from cygnus.runtime.database.models import SourceCompilationPlan

    return (
        await session.execute(
            select(SourceCompilationPlan).where(
                SourceCompilationPlan.source_id == source_id
            )
        )
    ).scalar_one_or_none()


async def _load_chunk_extracts(session: AsyncSession, source_id: uuid.UUID) -> list:
    """Load all done SourceChunkExtract rows for a source."""
    from cygnus.runtime.database.models import SourceChunkExtract

    rows = (
        (
            await session.execute(
                select(SourceChunkExtract).where(
                    SourceChunkExtract.source_id == source_id,
                    SourceChunkExtract.status == "done",
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _get_embedding_spec(registry):
    """Resolve the active document embedder used by REFINE and VERIFY."""
    try:
        spec_id = await registry.get_active_embedding_spec_id()
        if not spec_id:
            return None, None
        from cygnus.runtime.ai.embedding_catalog import get_spec

        spec = get_spec(spec_id)
        provider = await registry.get_embedding(task="document", spec_id=spec_id)
        return provider, spec
    except Exception as exc:
        logger.warning(f"MRP: could not load embedding spec: {exc}")
        return None, None


# ---------------------------------------------------------------------------
# Entry point 1: Phase 0-2
# ---------------------------------------------------------------------------


async def run_mrp_pipeline(
    session: AsyncSession,
    source,
    full_text: str,
    tracker: ProgressTracker,
    registry,
    kt_slug: Optional[str],
    kt_name: Optional[str],
    kt_desc: Optional[str],
) -> dict:
    """
    Orchestrate Phase 0 (Triage) → Phase 1 (MAP) → Phase 2 (REDUCE).

    Saves plan to DB with status 'pending_review'. If mrp_auto_approve_plan=True,
    immediately enqueues ingest_refine_task; otherwise returns {"status": "plan_ready"}.

    Resume: if source.pipeline_phase == 'plan_review' and plan already exists
    (e.g. after a crash in MAP/REDUCE), re-enter at REDUCE rather than re-doing MAP.
    """
    from cygnus.runtime.config import settings
    from cygnus.runtime.database.models import Source

    source_id = source.id

    # Resume check: if already at plan_review or beyond, don't re-run MAP+REDUCE
    current_phase = source.pipeline_phase
    if current_phase == "plan_review":
        plan = await _load_plan(session, source_id)
        if plan and plan.status in ("pending_review", "approved"):
            logger.info(
                f"MRP: source={source_id} already at plan_review, skipping MAP+REDUCE"
            )
            if plan.status == "approved" or settings.mrp_auto_approve_plan:
                return await _auto_trigger_refine(source_id, plan)
            return {"status": "plan_ready", "plan_id": str(plan.id)}

    if current_phase in ("refine", "verify", "commit"):
        logger.info(
            f"MRP: source={source_id} already in {current_phase} phase, skipping"
        )
        return {"status": f"already_in_{current_phase}"}

    # Provision LLM + embedding
    llm = await registry.get_llm()
    embedding_provider = None
    try:
        embedding_provider = await registry.get_embedding(task="document")
    except Exception:
        logger.warning(f"MRP: no embedding provider for source={source_id}")

    # Phase 0 + 1: MAP
    strategy, chunk_extracts = await run_map_phase(
        session=session,
        source_id=source_id,
        full_text=full_text,
        outline_json=source.outline_json,
        tracker=tracker,
        llm=llm,
    )

    # Compile-completeness gate: any failed or missing MAP unit keeps the plan
    # non-done and the source non-ready. Structured failures are persisted on
    # the source so operators can act on them without guessing.
    chunk_failures = await _collect_map_failures(
        session,
        source_id,
        full_text,
        outline_json=source.outline_json,
        strategy=strategy,
    )
    if chunk_failures:
        src = await session.get(Source, source_id)
        if src is not None:
            metadata = dict(src.metadata_ or {})
            metadata["mrp_failures"] = chunk_failures
            src.metadata_ = metadata
            await session.commit()
        raise CompileIncompleteError(chunk_failures)

    if not chunk_extracts:
        raise ValueError(
            f"MAP phase produced no successful chunks for source={source_id}"
        )

    # Phase 2: REDUCE
    src = await session.get(Source, source_id)
    if src:
        src.pipeline_phase = "reduce"
        # A successful MAP supersedes any structured failures recorded by an
        # earlier incomplete attempt.
        if (src.metadata_ or {}).get("mrp_failures"):
            metadata = dict(src.metadata_ or {})
            metadata.pop("mrp_failures", None)
            src.metadata_ = metadata
        await session.commit()

    plan = await run_reduce_phase(
        session=session,
        source=source,
        chunk_extracts=chunk_extracts,
        llm=llm,
        embedding_provider=embedding_provider,
        kt_name=kt_name,
        kt_desc=kt_desc,
        tracker=tracker,
    )

    await tracker.update(80, "Compilation plan ready")

    if settings.mrp_auto_approve_plan:
        return await _auto_trigger_refine(source_id, plan)

    return {"status": "plan_ready", "plan_id": str(plan.id)}


async def _auto_trigger_refine(source_id: uuid.UUID, plan) -> dict:
    """Auto-approve plan and enqueue ingest_refine_task."""
    from cygnus.review import auto_approve_source_compilation_plan
    from cygnus.runtime.worker import get_arq_pool

    job_id: Optional[str] = None
    recorded = False
    # Mark plan as approved and record the refine handoff transactionally.
    try:
        from cygnus.runtime.database import async_session_factory

        async with async_session_factory() as sess:
            from cygnus.runtime.database.models import Source, SourceCompilationPlan
            from cygnus.runtime.source_dispatch import (
                DISPATCH_STAGE_REFINE,
                enqueue_dispatch_execution,
                record_source_dispatch,
            )

            p = await sess.get(SourceCompilationPlan, plan.id)
            src = await sess.get(Source, source_id)
            if p:
                auto_approve_source_compilation_plan(p, src)
            if src is not None:
                # Record the refine execution with its deterministic job id in
                # the SAME transaction as the plan approval; enqueue only after
                # commit so the refine task never observes an uncommitted plan.
                # A lost enqueue is recovered by sweep_source_dispatches.
                row, _gen, _jid = await record_source_dispatch(
                    sess,
                    src,
                    stage=DISPATCH_STAGE_REFINE,
                    task_name="ingest_refine_task",
                    task_args=(str(source_id),),
                    new_generation=False,
                )
                await sess.commit()
                recorded = True
                ok = await enqueue_dispatch_execution(sess, row)
                await sess.commit()
                job_id = row.job_id if ok else None
            else:
                await sess.commit()
    except Exception as exc:
        logger.warning(f"MRP auto-approve state update failed: {exc}")

    if not recorded:
        # Fallback for a tombstoned/missing source or an outbox failure before
        # anything was recorded: keep the plain enqueue so the refine task
        # still gets a chance to run (and fail fast on a missing plan).
        pool = await get_arq_pool()
        job = await pool.enqueue_job("ingest_refine_task", str(source_id))
        job_id = job.job_id if job else None

    return {"status": "plan_auto_approved", "job_id": job_id}


# ---------------------------------------------------------------------------
# Entry point 2: Phase 3-5
# ---------------------------------------------------------------------------


async def run_refine_pipeline(
    session: AsyncSession,
    source,
    full_text: str,
    tracker: ProgressTracker,
    registry,
    kt_slug: Optional[str],
    kt_name: Optional[str],
    kt_desc: Optional[str],
) -> dict:
    """
    Orchestrate Phase 3 (REFINE) → Phase 4 (VERIFY) → Phase 5 (COMMIT).

    Called from ingest_refine_task after the plan is approved.
    Resumes from 'verify' or 'commit' phase if interrupted.
    """
    from cygnus.runtime.database.models import Source

    source_id = source.id
    current_phase = source.pipeline_phase

    # Load plan — fail fast if not approved
    plan = await _load_plan(session, source_id)
    if plan is None:
        raise ValueError(f"No compilation plan found for source={source_id}")
    if plan.status not in ("approved", "in_progress", "done"):
        raise ValueError(
            f"Plan for source={source_id} is not approved (status={plan.status}). "
            "Approve the plan before running REFINE."
        )

    # Load chunk extracts (needed for evidence assembly and coverage check)
    chunk_extracts = await _load_chunk_extracts(session, source_id)

    # Provision providers
    llm = await registry.get_llm()
    embedding_provider = None
    embedding_spec = None
    try:
        embedding_provider, embedding_spec = await _get_embedding_spec(registry)
    except Exception:
        pass

    page_results: list[PageWriteResult] = []

    if current_phase not in ("verify", "commit"):
        # Phase 3: REFINE
        src = await session.get(Source, source_id)
        if src:
            src.pipeline_phase = "refine"
        plan.status = "in_progress"
        await session.commit()

        page_results = await run_refine_phase(
            session=session,
            source=source,
            plan=plan,
            chunk_extracts=chunk_extracts,
            full_text=full_text,
            llm=llm,
            embedding_provider=embedding_provider,
            kt_slug=kt_slug,
            tracker=tracker,
        )

        src = await session.get(Source, source_id)
        if src:
            src.pipeline_phase = "verify"
        await session.commit()
    else:
        logger.info(
            f"MRP: source={source_id} resuming at {current_phase} phase — loading persisted drafts"
        )
        drafts = (plan.plan_json or {}).get("_page_drafts") or []
        has_failed_drafts = any(
            isinstance(d, dict) and d.get("failure") for d in drafts
        )
        if drafts and not has_failed_drafts:
            page_results = [PageWriteResult.from_dict(d) for d in drafts]
            logger.info(
                f"MRP: loaded {len(page_results)} persisted page drafts for source={source_id}"
            )
        else:
            if has_failed_drafts:
                # Persisted drafts include failed writer units: treat them as
                # incomplete and re-run REFINE so a transient failure can recover
                # on retry. Persistent failures keep the plan non-done and the
                # source non-ready with structured failures at the commit gate.
                logger.warning(
                    f"MRP: source={source_id} has failed page drafts — re-running REFINE to recover"
                )
            else:
                logger.warning(
                    f"MRP: source={source_id} at {current_phase} phase but no drafts persisted — re-running REFINE"
                )
            src = await session.get(Source, source_id)
            if src:
                src.pipeline_phase = "refine"
            await session.commit()

            page_results = await run_refine_phase(
                session=session,
                source=source,
                plan=plan,
                chunk_extracts=chunk_extracts,
                full_text=full_text,
                llm=llm,
                embedding_provider=embedding_provider,
                kt_slug=kt_slug,
                tracker=tracker,
            )

        src = await session.get(Source, source_id)
        if src:
            src.pipeline_phase = "verify"
        await session.commit()

    # Phase 4: VERIFY
    page_results = await run_verify_phase(
        session=session,
        source=source,
        page_results=page_results,
        chunk_extracts=chunk_extracts,
        full_text=full_text,
        llm=llm,
        embedding_provider=embedding_provider,
        tracker=tracker,
    )

    # Phase 5: COMMIT
    return await run_commit_phase(
        session=session,
        source=source,
        page_results=page_results,
        plan=plan,
        embedding_provider=embedding_provider,
        embedding_spec=embedding_spec,
        kt_slug=kt_slug,
        tracker=tracker,
        full_text=full_text,
    )
