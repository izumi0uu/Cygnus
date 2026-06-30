"""Wiki branch lifecycle governance for review-owned contribution branches.

This module owns the branch-level state machine for grouped wiki draft
contributions. The runtime router remains the app-shell adapter, while review
owns submit / close / merge / rebase semantics for governed branch changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.review.contributions import (
    InvalidTransition,
    _enqueue_ai_review,
    approve_wiki_draft,
    notify_approved,
    notify_submitted,
    wiki_draft_adapter,
    withdraw,
)
from cygnus.runtime.database.models import Employee, WikiBranch, WikiPage, WikiPageDraft
from cygnus.runtime.services.audit_service import log_audit


class BranchMergeConflict(Exception):
    """Raised when a branch merge sees a stale draft against a newer live page."""

    def __init__(self, page_title: str, page_slug: str, current_version: int, base_version: int):
        self.page_title = page_title
        self.page_slug = page_slug
        self.current_version = current_version
        self.base_version = base_version
        super().__init__(
            f"Conflict detected on page '{page_title}' ({page_slug}). "
            f"This page has newer updates (v{current_version}) since the author started editing (v{base_version}). "
            "The author must rebase the branch before merge approval."
        )


async def _load_branch_drafts(db: AsyncSession, branch_id) -> list[WikiPageDraft]:
    stmt = select(WikiPageDraft).where(WikiPageDraft.branch_id == branch_id)
    return list((await db.execute(stmt)).scalars().all())


async def _has_branch_conflict(db: AsyncSession, branch_id) -> bool:
    for draft in await _load_branch_drafts(db, branch_id):
        if draft.draft_kind != "edit" or not draft.page_id:
            continue
        page = await db.get(WikiPage, draft.page_id)
        if page and draft.base_version is not None and draft.base_version < page.version:
            return True
    return False


async def submit_wiki_branch(db: AsyncSession, branch: WikiBranch, actor: Employee) -> list[WikiPageDraft]:
    """Submit a draft branch into pending_merge and notify reviewers."""
    if branch.author_id != actor.id and actor.role != "admin":
        raise InvalidTransition("Only the branch author may submit this request")
    if branch.status != "draft":
        raise InvalidTransition(f"Cannot submit for merge while the branch is in '{branch.status}' state")

    count_stmt = select(func.count(WikiPageDraft.id)).where(WikiPageDraft.branch_id == branch.id)
    count = (await db.execute(count_stmt)).scalar_one()
    if count == 0:
        raise InvalidTransition("Your contribution branch is empty. Add a page draft before submitting.")

    drafts = await _load_branch_drafts(db, branch.id)
    for draft in drafts:
        if draft.status != "pending":
            draft.status = "pending"
        await notify_submitted(db, wiki_draft_adapter, draft, actor)

    branch.status = "pending_merge"
    await log_audit(db, actor, "submit_branch", "wiki_branch", str(branch.id))
    return drafts


async def close_wiki_branch(
    db: AsyncSession,
    branch: WikiBranch,
    actor: Employee,
    *,
    reviewer_override: bool = False,
) -> list[WikiPageDraft]:
    """Close a branch and withdraw its still-open drafts."""
    is_author = branch.author_id == actor.id
    if not is_author and actor.role != "admin" and not reviewer_override:
        raise InvalidTransition("You do not have permission to close or cancel this branch")
    if branch.status in ("merged", "closed"):
        raise InvalidTransition("The branch is already closed or merged")

    drafts = await _load_branch_drafts(db, branch.id)
    for draft in drafts:
        if draft.status not in ("pending", "needs_revision"):
            continue
        if actor.role == "admin" or is_author:
            await withdraw(db, wiki_draft_adapter, draft, actor)
        else:
            draft.status = "withdrawn"

    branch.status = "closed"
    await log_audit(db, actor, "close_branch", "wiki_branch", str(branch.id))
    return drafts


async def merge_wiki_branch(
    db: AsyncSession,
    branch: WikiBranch,
    reviewer: Employee,
    reviewer_note: Optional[str] = None,
) -> list[WikiPageDraft]:
    """Approve every draft in a pending_merge branch and mark the branch merged."""
    if branch.status != "pending_merge":
        raise InvalidTransition("A branch can only be merged while it is in 'pending_merge' state")

    drafts = await _load_branch_drafts(db, branch.id)
    for draft in drafts:
        if draft.draft_kind != "edit" or not draft.page_id:
            continue
        page = await db.get(WikiPage, draft.page_id)
        if page and draft.base_version is not None and draft.base_version < page.version:
            branch.has_conflict = True
            raise BranchMergeConflict(page.title, page.slug, page.version, draft.base_version)

    async with db.begin_nested():
        for draft in drafts:
            page = await approve_wiki_draft(
                db,
                draft,
                reviewer_id=reviewer.id,
                reviewer_note=reviewer_note,
            )
            draft.page = page
            await notify_approved(
                db,
                wiki_draft_adapter,
                draft,
                reviewer,
                version_label=f"v{page.version}",
            )

        branch.status = "merged"
        branch.reviewer_id = reviewer.id
        branch.reviewed_at = datetime.now(timezone.utc)
        branch.reviewer_note = reviewer_note
        branch.has_conflict = False

    await log_audit(db, reviewer, "merge_branch", "wiki_branch", str(branch.id))
    return drafts


async def rebase_wiki_branch_draft(
    db: AsyncSession,
    branch: WikiBranch,
    draft: WikiPageDraft,
    author: Employee,
    resolved_content_md: str,
) -> WikiPageDraft:
    """Resolve one conflicted branch draft against the latest live page state."""
    if branch.author_id != author.id and author.role != "admin":
        raise InvalidTransition("Only the branch author may resolve conflicts")
    if draft.branch_id != branch.id:
        raise InvalidTransition("Draft not found in this branch")
    if not draft.page_id:
        raise InvalidTransition("New-page drafts do not need rebase")

    page = await db.get(WikiPage, draft.page_id)
    if not page:
        raise ValueError("Original wiki page not found")

    draft.content_md = resolved_content_md
    draft.base_version = page.version
    draft.status = "pending"
    await _enqueue_ai_review(db, draft)

    branch.has_conflict = await _has_branch_conflict(db, branch.id)
    await log_audit(db, author, "rebase_draft", "wiki_page_draft", str(draft.id))
    return draft
