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
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import WikiPage, WikiPageDraft
from app.services.ai_review import regex_checks, structural_checks


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
    checks.extend(await structural_checks.run(
        db, content_md, self_slug=self_slug,
        scope_type=scope_type, scope_id=scope_id,
    ))
    return _build(checks)


# ---------------------------------------------------------------------------
# Async entrypoint — invoked by the arq worker. Loads the draft, runs L3+L4,
# merges results with whatever L1+L2 stored already, writes back.
# ---------------------------------------------------------------------------

async def run_async_checks(draft_id: str, expected_round: Optional[int] = None) -> None:
    """Worker entry. Self-contained — opens its own session.

    Runs ALL four layers (L1 regex, L2 structural, L3 semantic, L4 LLM). The
    submit path no longer runs anything synchronously, so this is the only
    place AI checks execute.

    `expected_round` is the draft's `revision_round` at enqueue time. If the
    draft has been resubmitted by the time we finish (round bumped), we drop
    our stale verdict — a newer job is already queued for the new content.
    """
    from app.database import async_session_factory
    from app.services.ai_review import llm_checks, regex_checks, semantic_checks, structural_checks

    try:
        did = uuid.UUID(draft_id)
    except (ValueError, TypeError):
        logger.warning(f"ai_pre_review_draft: invalid draft id {draft_id!r}")
        return

    async with async_session_factory() as db:
        draft = await db.get(WikiPageDraft, did)
        if draft is None:
            logger.info(f"ai_pre_review_draft: draft {did} not found (deleted?)")
            return
        # Don't re-run on terminal states — by the time we got picked up
        # the draft may have been approved/withdrawn.
        if draft.status not in ("pending",):
            logger.info(f"ai_pre_review_draft: draft {did} status={draft.status}, skipping")
            return

        draft.ai_check_status = "running"
        await db.commit()

        page = await db.get(WikiPage, draft.page_id) if draft.page_id else None
        self_slug = page.slug if page else (draft.suggested_metadata or {}).get("slug")
        scope_type = page.scope_type if page else (
            (draft.suggested_metadata or {}).get("scope_type") or "global"
        )
        scope_id = page.scope_id if page else None
        title = page.title if page else (draft.suggested_metadata or {}).get("title", "")
        page_type = page.page_type if page else (
            (draft.suggested_metadata or {}).get("page_type") or "concept"
        )

        new_checks: list[dict] = []
        # L1 + L2 — cheap, always succeed. Run them first so even if L3/L4
        # crashes the draft still has regex/structural verdicts attached.
        try:
            new_checks.extend(regex_checks.run(draft.content_md))
            new_checks.extend(await structural_checks.run(
                db, draft.content_md, self_slug=self_slug,
                scope_type=scope_type, scope_id=scope_id,
            ))
        except Exception as e:
            logger.exception(f"ai_pre_review_draft: L1/L2 failure: {e}")
            new_checks.append({
                "id": "runner.l12_error",
                "layer": "L2",
                "severity": "warn",
                "status": "skipped",
                "message": f"L1/L2 checks crashed: {e}",
                "matches": [],
            })

        try:
            new_checks.extend(await semantic_checks.run(
                db, content_md=draft.content_md,
                self_page_id=draft.page_id,
                scope_type=scope_type, scope_id=scope_id,
                draft_kind=draft.draft_kind or "edit",
            ))
            new_checks.extend(await llm_checks.run(
                db, content_md=draft.content_md, title=title, page_type=page_type,
            ))
        except Exception as e:
            logger.exception(f"ai_pre_review_draft: unexpected failure: {e}")
            new_checks.append({
                "id": "runner.error",
                "layer": "L4",
                "severity": "warn",
                "status": "skipped",
                "message": f"AI review crashed: {e}",
                "matches": [],
            })

        # Resubmit race guard: if the author resubmitted while we were running,
        # `revision_round` will have bumped. Our verdict is for OLD content, so
        # drop it — a newer job is already queued for the new content.
        if expected_round is not None:
            await db.refresh(draft, ["revision_round", "status"])
            current_round = int(draft.revision_round or 0)
            if current_round != expected_round:
                logger.info(
                    f"ai_pre_review_draft: draft={did} round changed "
                    f"({expected_round} → {current_round}), dropping stale verdict"
                )
                return
            if draft.status != "pending":
                logger.info(
                    f"ai_pre_review_draft: draft={did} no longer pending "
                    f"(status={draft.status}), dropping verdict"
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
