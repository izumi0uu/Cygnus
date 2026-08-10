"""
AI pre-review runner — orchestrates L1-L4 checks and produces a single JSON
verdict written to wiki_page_drafts.ai_check_results.

JSON shape (version 1):
{
  "version": 1,
  "summary": {"pass": int, "warn": int, "fail": int, "skipped": int},
  "checks": [
    {
      "id": str,            # stable identifier e.g. "pii.email"
      "layer": "L1"|"L2"|"L3"|"L4",
      "severity": "block"|"warn",
      "status": "pass"|"warn"|"fail"|"skipped",
      "message": str|null,
      "matches": list,       # list of strings or {slug, score, ...}
      ...layer-specific fields
    },
    ...
  ]
}

Permissive mode: nothing in this module blocks submission. Even a "fail"
status only annotates the draft so the human reviewer sees the flag.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import (
    WikiDraftAiPreReviewDispatch,
    WikiPage,
    WikiPageDraft,
)
from cygnus.review.pre_review import regex_checks, structural_checks


@dataclass
class CheckResult:
    id: str
    layer: str
    severity: str
    status: str
    message: Optional[str] = None
    matches: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "layer": self.layer,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "matches": self.matches,
        }
        d.update(self.extra)
        return d


AiReviewResults = dict  # the JSONB shape documented above


def _mark_dispatch_stale(dispatch: WikiDraftAiPreReviewDispatch) -> None:
    dispatch.dispatch_status = "stale"
    dispatch.terminal_reason = "stale_or_superseded"
    dispatch.last_error = "worker guard rejected a stale draft revision"
    dispatch.lease_expires_at = None
    dispatch.next_attempt_at = None
    dispatch.completed_at = datetime.now(timezone.utc)


async def _load_expected_dispatch(
    db: AsyncSession,
    draft_id: uuid.UUID,
    expected_round: int,
    expected_version: int,
) -> WikiDraftAiPreReviewDispatch | None:
    statement = (
        select(WikiDraftAiPreReviewDispatch)
        .where(
            WikiDraftAiPreReviewDispatch.draft_id == draft_id,
            WikiDraftAiPreReviewDispatch.revision_round == expected_round,
            WikiDraftAiPreReviewDispatch.draft_version == expected_version,
        )
        .with_for_update()
    )
    return (await db.execute(statement)).scalar_one_or_none()


def _clear_stale_queued_draft(
    draft: WikiPageDraft,
    *,
    expected_round: int,
    expected_version: int,
) -> None:
    if (
        int(draft.revision_round or 0) == expected_round
        and draft.version == expected_version
        and draft.ai_check_status == "queued"
    ):
        draft.ai_check_status = "skipped"
        draft.ai_check_results = None
        draft.ai_checked_at = None


def _summarise(checks: list[dict]) -> dict:
    counts = {"pass": 0, "warn": 0, "fail": 0, "skipped": 0}
    for c in checks:
        status = c.get("status", "pass")
        if status in counts:
            counts[status] += 1
    return counts


def _build(checks: list[dict]) -> AiReviewResults:
    return {
        "version": 1,
        "summary": _summarise(checks),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Sync entrypoint — called from request handlers right after the draft is
# persisted. Runs L1 + L2 only; cheap and DB-light.
# ---------------------------------------------------------------------------


async def run_sync_checks(
    db: AsyncSession,
    content_md: str,
    self_slug: Optional[str] = None,
    self_page_id: Optional[uuid.UUID] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> AiReviewResults:
    _ = self_page_id  # currently unused at L1/L2, reserved for future checks
    checks: list[dict] = []
    checks.extend(regex_checks.run(content_md))
    checks.extend(
        await structural_checks.run(
            db,
            content_md,
            self_slug=self_slug,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    )
    return _build(checks)


# ---------------------------------------------------------------------------
# Async entrypoint — invoked by the arq worker. Loads the draft, runs L3+L4,
# merges results with whatever L1+L2 stored already, writes back.
# ---------------------------------------------------------------------------


async def run_async_checks(
    draft_id: str,
    expected_round: Optional[int] = None,
    expected_version: Optional[int] = None,
) -> None:
    """Worker entry. Self-contained — opens its own session.

    Runs ALL four layers (L1 regex, L2 structural, L3 semantic, L4 LLM). The
    submit path no longer runs anything synchronously, so this is the only
    place AI checks execute.

    Every accepted job carries the exact round and draft-content version staged
    for review. A resubmit changes the round; a branch rebase can change only
    the draft version, so both are checked before and after expensive work.
    """
    from cygnus.runtime.database import async_session_factory
    from cygnus.review.pre_review import (
        llm_checks,
        regex_checks,
        semantic_checks,
        structural_checks,
    )

    try:
        did = uuid.UUID(draft_id)
    except (ValueError, TypeError):
        logger.warning(f"ai_pre_review_draft: invalid draft id {draft_id!r}")
        return

    if expected_round is None or expected_version is None:
        logger.warning(
            "ai_pre_review_draft: refusing job without durable revision identity"
        )
        return

    async with async_session_factory() as db:
        draft = await db.get(
            WikiPageDraft,
            did,
            with_for_update=True,
            populate_existing=True,
        )
        if draft is None:
            logger.info(f"ai_pre_review_draft: draft {did} not found (deleted?)")
            return

        dispatch = await _load_expected_dispatch(
            db,
            did,
            expected_round,
            expected_version,
        )
        if dispatch is None or dispatch.dispatch_status not in {
            "dispatching",
            "enqueued",
        }:
            logger.info(
                f"ai_pre_review_draft: draft={did} has no active durable "
                "dispatch claim, skipping"
            )
            return

        # Don't re-run on terminal states — by the time we got picked up the
        # draft may have been approved, withdrawn, or superseded.
        if draft.status != "pending":
            _clear_stale_queued_draft(
                draft,
                expected_round=expected_round,
                expected_version=expected_version,
            )
            _mark_dispatch_stale(dispatch)
            await db.commit()
            logger.info(
                f"ai_pre_review_draft: draft {did} status={draft.status}, skipping"
            )
            return
        if int(draft.revision_round or 0) != expected_round:
            _mark_dispatch_stale(dispatch)
            await db.commit()
            logger.info(
                f"ai_pre_review_draft: draft={did} round changed "
                f"({expected_round} → {draft.revision_round}), skipping"
            )
            return
        if draft.version != expected_version:
            _mark_dispatch_stale(dispatch)
            await db.commit()
            logger.info(
                f"ai_pre_review_draft: draft={did} version changed "
                f"({expected_version} → {draft.version}), skipping"
            )
            return
        if draft.ai_check_status != "queued":
            if draft.ai_check_status in {"passed", "warned", "failed", "skipped"}:
                dispatch.dispatch_status = "completed"
                dispatch.terminal_reason = f"draft_terminal_{draft.ai_check_status}"
                dispatch.completed_at = datetime.now(timezone.utc)
                dispatch.lease_expires_at = None
                dispatch.next_attempt_at = None
            else:
                _mark_dispatch_stale(dispatch)
            await db.commit()
            logger.info(
                f"ai_pre_review_draft: draft={did} AI status="
                f"{draft.ai_check_status}, skipping unclaimed job"
            )
            return

        draft.ai_check_status = "running"
        dispatch.dispatch_status = "running"
        dispatch.lease_expires_at = None
        dispatch.next_attempt_at = None
        await db.commit()

        page = await db.get(WikiPage, draft.page_id) if draft.page_id else None
        self_slug = page.slug if page else (draft.suggested_metadata or {}).get("slug")
        scope_type = (
            page.scope_type
            if page
            else ((draft.suggested_metadata or {}).get("scope_type") or "global")
        )
        scope_id = page.scope_id if page else None
        title = (
            page.title if page else (draft.suggested_metadata or {}).get("title", "")
        )
        page_type = (
            page.page_type
            if page
            else ((draft.suggested_metadata or {}).get("page_type") or "concept")
        )

        new_checks: list[dict] = []
        # L1 + L2 — cheap, always succeed. Run them first so even if L3/L4
        # crashes the draft still has regex/structural verdicts attached.
        try:
            new_checks.extend(regex_checks.run(draft.content_md))
            new_checks.extend(
                await structural_checks.run(
                    db,
                    draft.content_md,
                    self_slug=self_slug,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
            )
        except Exception as e:
            logger.exception(f"ai_pre_review_draft: L1/L2 failure: {e}")
            new_checks.append(
                {
                    "id": "runner.l12_error",
                    "layer": "L2",
                    "severity": "warn",
                    "status": "skipped",
                    "message": f"L1/L2 checks crashed: {e}",
                    "matches": [],
                }
            )

        try:
            new_checks.extend(
                await semantic_checks.run(
                    db,
                    content_md=draft.content_md,
                    self_page_id=draft.page_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    draft_kind=draft.draft_kind or "edit",
                )
            )
            new_checks.extend(
                await llm_checks.run(
                    db,
                    content_md=draft.content_md,
                    title=title,
                    page_type=page_type,
                )
            )
        except Exception as e:
            logger.exception(f"ai_pre_review_draft: unexpected failure: {e}")
            new_checks.append(
                {
                    "id": "runner.error",
                    "layer": "L4",
                    "severity": "warn",
                    "status": "skipped",
                    "message": f"AI review crashed: {e}",
                    "matches": [],
                }
            )

        # A resubmit changes ``revision_round`` while a branch rebase can change
        # only ``version``. Either makes this verdict stale for the current
        # content and must leave the newer staged job as the sole writer.
        draft = await db.get(
            WikiPageDraft,
            did,
            with_for_update=True,
            populate_existing=True,
        )
        if draft is None:
            logger.info(f"ai_pre_review_draft: draft {did} not found (deleted?)")
            return
        dispatch = await _load_expected_dispatch(
            db,
            did,
            expected_round,
            expected_version,
        )
        if dispatch is None or dispatch.dispatch_status != "running":
            logger.info(
                f"ai_pre_review_draft: draft={did} dispatch claim is no "
                "longer running, dropping verdict"
            )
            return
        stale = (
            int(draft.revision_round or 0) != expected_round
            or draft.version != expected_version
            or draft.status != "pending"
        )
        if stale:
            _clear_stale_queued_draft(
                draft,
                expected_round=expected_round,
                expected_version=expected_version,
            )
            _mark_dispatch_stale(dispatch)
            await db.commit()
            logger.info(
                f"ai_pre_review_draft: draft={did} revision changed, "
                "dropping stale verdict"
            )
            return
        if draft.ai_check_status != "running":
            if draft.ai_check_status in {"passed", "warned", "failed", "skipped"}:
                dispatch.dispatch_status = "completed"
                dispatch.terminal_reason = f"draft_terminal_{draft.ai_check_status}"
                dispatch.completed_at = datetime.now(timezone.utc)
                dispatch.lease_expires_at = None
                dispatch.next_attempt_at = None
            else:
                _mark_dispatch_stale(dispatch)
            await db.commit()
            logger.info(
                f"ai_pre_review_draft: draft={did} AI status="
                f"{draft.ai_check_status}, dropping unclaimed verdict"
            )
            return

        # Worker is now the sole writer of ai_check_results — replace, don't merge.
        results = _build(new_checks)
        draft.ai_check_results = results
        summary = results["summary"]
        if summary["fail"] > 0:
            draft.ai_check_status = "failed"
        elif summary["warn"] > 0:
            draft.ai_check_status = "warned"
        else:
            draft.ai_check_status = "passed"
        draft.ai_checked_at = datetime.now(timezone.utc)
        if dispatch is not None:
            dispatch.dispatch_status = "completed"
            dispatch.terminal_reason = "verdict_written"
            dispatch.completed_at = draft.ai_checked_at
            dispatch.lease_expires_at = None
            dispatch.next_attempt_at = None
        await db.commit()

        logger.info(
            f"ai_pre_review_draft: draft={did} → {draft.ai_check_status} "
            f"({summary['pass']} pass / {summary['warn']} warn / {summary['fail']} fail)"
        )


# ---------------------------------------------------------------------------
# Helper used when we already have sync results and want to merge in async.
# ---------------------------------------------------------------------------


def merge_results(base: Optional[dict], extra_checks: list[dict]) -> AiReviewResults:
    """Combine a previously-stored verdict with new checks, replacing matching ids."""
    existing = (base or {}).get("checks", [])
    merged: list[dict[str, Any]] = list(existing)
    existing_ids = {c.get("id") for c in merged}
    for c in extra_checks:
        if c.get("id") in existing_ids:
            merged = [m for m in merged if m.get("id") != c.get("id")]
        merged.append(c)
    return _build(merged)
