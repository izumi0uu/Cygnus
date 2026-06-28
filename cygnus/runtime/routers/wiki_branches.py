"""
Wiki Branch router — named contribution branches, batch reviews, and atomic merges.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    WikiBranch,
    WikiPageDraft,
    WikiPage,
    Department,
)
from cygnus.runtime.services import wiki_service
from cygnus.runtime.services.audit_service import log_audit
from cygnus.runtime.services.auth_service import get_current_user
from cygnus.runtime.services.permission_engine import (
    _get_user_permissions,
    has_any_permission,
)
from cygnus.runtime.routers.wiki_drafts import DraftResponse, _draft_response

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class BranchCreate(BaseModel):
    name: str
    description: Optional[str] = None
    scope_type: str = "global"
    scope_id: Optional[uuid.UUID] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Branch name cannot be empty")
        if len(v) > 100:
            raise ValueError("Branch name must not exceed 100 characters")
        return v

    @field_validator("scope_type")
    @classmethod
    def scope_known(cls, v: str) -> str:
        if v not in ("global", "department"):
            raise ValueError("scope_type must be either global or department")
        return v


class BranchResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    scope_type: str = "global"
    scope_id: Optional[uuid.UUID] = None
    author_id: uuid.UUID
    author_name: Optional[str] = None
    status: str
    has_conflict: bool = False
    reviewer_id: Optional[uuid.UUID] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewer_note: Optional[str] = None
    created_at: str
    updated_at: str
    draft_count: int = 0


class BranchDetailResponse(BranchResponse):
    drafts: list[DraftResponse] = []


class MergeBranchRequest(BaseModel):
    reviewer_note: Optional[str] = None


class ResolveConflictRequest(BaseModel):
    resolved_content_md: str


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

async def _can_create_branch(db: AsyncSession, user: Employee, scope_type: str, scope_id: Optional[uuid.UUID]) -> bool:
    if user.role == "admin":
        return True
    perms = _get_user_permissions(user)
    if scope_type == "department" and scope_id:
        if "wiki:write:all" in perms:
            return True
        if "wiki:write:own_dept" in perms and scope_id in user.department_ids:
            return True
        return False
    return has_any_permission(list(perms), "wiki", "write")


async def _can_review_branch(db: AsyncSession, user: Employee, scope_type: str, scope_id: Optional[uuid.UUID]) -> bool:
    if user.role == "admin":
        return True
    perms = _get_user_permissions(user)
    return "wiki:write:all" in perms


async def _to_branch_response(db: AsyncSession, branch: WikiBranch) -> BranchResponse:
    # Resolve author/reviewer names
    author = await db.get(Employee, branch.author_id)
    reviewer = await db.get(Employee, branch.reviewer_id) if branch.reviewer_id else None

    # Count drafts
    stmt = select(func.count(WikiPageDraft.id)).where(WikiPageDraft.branch_id == branch.id)
    count = (await db.execute(stmt)).scalar_one()

    return BranchResponse(
        id=branch.id,
        name=branch.name,
        description=branch.description,
        scope_type=branch.scope_type,
        scope_id=branch.scope_id,
        author_id=branch.author_id,
        author_name=author.name if author else None,
        status=branch.status,
        has_conflict=branch.has_conflict,
        reviewer_id=branch.reviewer_id,
        reviewer_name=reviewer.name if reviewer else None,
        reviewed_at=branch.reviewed_at.isoformat() if branch.reviewed_at else None,
        reviewer_note=branch.reviewer_note,
        created_at=branch.created_at.isoformat(),
        updated_at=branch.updated_at.isoformat(),
        draft_count=count,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/wiki/branches", response_model=BranchResponse, status_code=201)
async def create_branch(
    body: BranchCreate,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Create a new named contribution branch."""
    if not await _can_create_branch(db, user, body.scope_type, body.scope_id):
        raise HTTPException(403, "You do not have permission to contribute in this scope")

    branch = WikiBranch(
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        author_id=user.id,
        status="draft",
        has_conflict=False,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)

    await log_audit(db, user, "create_branch", "wiki_branch", str(branch.id))
    return await _to_branch_response(db, branch)


@router.get("/wiki/branches", response_model=list[BranchResponse])
async def list_branches(
    status: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None),
    scope_id: Optional[uuid.UUID] = Query(None),
    mine: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """List contribution branches with filters."""
    stmt = select(WikiBranch)
    filters = []

    if status:
        filters.append(WikiBranch.status == status)
    if scope_type:
        filters.append(WikiBranch.scope_type == scope_type)
    if scope_id:
        filters.append(WikiBranch.scope_id == scope_id)
    if mine:
        filters.append(WikiBranch.author_id == user.id)

    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = stmt.order_by(WikiBranch.updated_at.desc())
    branches = (await db.execute(stmt)).scalars().all()

    # Map responses
    res = []
    for b in branches:
        res.append(await _to_branch_response(db, b))
    return res


@router.get("/wiki/branches/{branch_id}", response_model=BranchDetailResponse)
async def get_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Retrieve detailed branch information with associated page drafts."""
    branch = await db.get(WikiBranch, branch_id)
    if not branch:
        raise HTTPException(404, "Contribution branch not found")

    base = await _to_branch_response(db, branch)

    # Fetch associated drafts
    stmt = (
        select(WikiPageDraft)
        .where(WikiPageDraft.branch_id == branch_id)
        .order_by(WikiPageDraft.created_at.desc())
    )
    drafts = (await db.execute(stmt)).scalars().all()

    draft_responses = []
    for d in drafts:
        draft_responses.append(await _draft_response(db, d))

    return BranchDetailResponse(**base.model_dump(), drafts=draft_responses)


@router.post("/wiki/branches/{branch_id}/submit", response_model=BranchResponse)
async def submit_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Submit branch for merge review (draft -> pending_merge)."""
    branch = await db.get(WikiBranch, branch_id)
    if not branch:
        raise HTTPException(404, "Contribution branch not found")

    if branch.author_id != user.id and user.role != "admin":
        raise HTTPException(403, "Only the branch author may submit this request")

    if branch.status != "draft":
        raise HTTPException(400, f"Cannot submit for merge while the branch is in '{branch.status}' state")

    # Verify branch is not empty
    stmt = select(func.count(WikiPageDraft.id)).where(WikiPageDraft.branch_id == branch.id)
    count = (await db.execute(stmt)).scalar_one()
    if count == 0:
        raise HTTPException(400, "Your contribution branch is empty. Add a page draft before submitting.")

    # Get associated drafts
    stmt = select(WikiPageDraft).where(WikiPageDraft.branch_id == branch_id)
    drafts = (await db.execute(stmt)).scalars().all()

    # Enqueue AI review for all drafts & trigger notifications
    from cygnus.runtime.services.contribution_service import notify_submitted, wiki_draft_adapter
    for d in drafts:
        if d.status != "pending":
            d.status = "pending"
        # Trigger AI check & notify reviewers
        await notify_submitted(db, wiki_draft_adapter, d, user)

    branch.status = "pending_merge"
    await db.commit()
    await db.refresh(branch)

    await log_audit(db, user, "submit_branch", "wiki_branch", str(branch.id))
    return await _to_branch_response(db, branch)


@router.post("/wiki/branches/{branch_id}/close", response_model=BranchResponse)
async def close_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Close/withdraw a branch and withdraw all its drafts."""
    branch = await db.get(WikiBranch, branch_id)
    if not branch:
        raise HTTPException(404, "Contribution branch not found")

    is_author = branch.author_id == user.id
    is_reviewer = await _can_review_branch(db, user, branch.scope_type, branch.scope_id)

    if not is_author and not is_reviewer:
        raise HTTPException(403, "You do not have permission to close or cancel this branch")

    if branch.status in ("merged", "closed"):
        raise HTTPException(400, "The branch is already closed or merged")

    # Withdraw all drafts
    stmt = select(WikiPageDraft).where(WikiPageDraft.branch_id == branch_id)
    drafts = (await db.execute(stmt)).scalars().all()

    from cygnus.runtime.services.contribution_service import withdraw, wiki_draft_adapter
    for d in drafts:
        if d.status in ("pending", "needs_revision"):
            await withdraw(db, wiki_draft_adapter, d, user)

    branch.status = "closed"
    await db.commit()
    await db.refresh(branch)

    await log_audit(db, user, "close_branch", "wiki_branch", str(branch.id))
    return await _to_branch_response(db, branch)


@router.post("/wiki/branches/{branch_id}/merge", response_model=BranchResponse)
async def merge_branch(
    branch_id: uuid.UUID,
    body: MergeBranchRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Atomically merge the branch (approve all drafts sequentially in a transaction)."""
    branch = await db.get(WikiBranch, branch_id)
    if not branch:
        raise HTTPException(404, "Contribution branch not found")

    if not await _can_review_branch(db, user, branch.scope_type, branch.scope_id):
        raise HTTPException(403, "You do not have permission to merge documents in this scope")

    if branch.status != "pending_merge":
        raise HTTPException(400, "A branch can only be merged while it is in 'pending_merge' state")

    # Fetch drafts in branch
    stmt = select(WikiPageDraft).where(WikiPageDraft.branch_id == branch_id)
    drafts = (await db.execute(stmt)).scalars().all()

    # Step 1: Pre-merge concurrency check (Detect mid-air collisions before executing writing)
    for d in drafts:
        if d.draft_kind == "edit" and d.page_id:
            page = await db.get(WikiPage, d.page_id)
            if page and d.base_version is not None and d.base_version < page.version:
                branch.has_conflict = True
                await db.commit()
                raise HTTPException(
                    409,
                    f"Conflict detected on page '{page.title}' ({page.slug}). "
                    f"This page has newer updates (v{page.version}) since the author started editing (v{d.base_version}). "
                    "The author must rebase the branch before merge approval."
                )

    # Step 2: Atomic approval of all drafts
    try:
        async with db.begin_nested():
            for d in drafts:
                # Batch approve
                await wiki_service.approve_draft(
                    db,
                    d,
                    reviewer_id=user.id,
                    reviewer_note=body.reviewer_note,
                )
                # Fire approved notifications
                from cygnus.runtime.services.contribution_service import notify_approved, wiki_draft_adapter
                await notify_approved(db, wiki_draft_adapter, d, user)

            branch.status = "merged"
            branch.reviewer_id = user.id
            branch.reviewed_at = datetime.now(timezone.utc)
            branch.reviewer_note = body.reviewer_note
            branch.has_conflict = False

        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, f"Branch merge failed: {str(e)}")

    await db.refresh(branch)
    await log_audit(db, user, "merge_branch", "wiki_branch", str(branch.id))
    return await _to_branch_response(db, branch)


@router.post("/wiki/branches/{branch_id}/rebase/{draft_id}", response_model=DraftResponse)
async def rebase_draft(
    branch_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: ResolveConflictRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Resolve a conflict on a draft by applying resolved content and bumping base_version to current."""
    branch = await db.get(WikiBranch, branch_id)
    if not branch:
        raise HTTPException(404, "Contribution branch not found")

    if branch.author_id != user.id and user.role != "admin":
        raise HTTPException(403, "Only the branch author may resolve conflicts")

    draft = await db.get(WikiPageDraft, draft_id)
    if not draft or draft.branch_id != branch_id:
        raise HTTPException(404, "Draft not found in this branch")

    if not draft.page_id:
        raise HTTPException(400, "New-page drafts do not need rebase")

    page = await db.get(WikiPage, draft.page_id)
    if not page:
        raise HTTPException(404, "Original wiki page not found")

    # Apply conflict resolution
    draft.content_md = body.resolved_content_md
    draft.base_version = page.version  # Align to latest live version!
    draft.status = "pending"

    # Enqueue new AI review round
    from cygnus.runtime.services.contribution_service import _enqueue_ai_review
    await _enqueue_ai_review(db, draft)

    # Re-calculate branch conflict state
    stmt = select(WikiPageDraft).where(WikiPageDraft.branch_id == branch_id)
    all_drafts = (await db.execute(stmt)).scalars().all()

    still_conflict = False
    for d in all_drafts:
        if d.draft_kind == "edit" and d.page_id:
            p = await db.get(WikiPage, d.page_id)
            if p and d.base_version is not None and d.base_version < p.version:
                still_conflict = True
                break

    branch.has_conflict = still_conflict
    await db.commit()
    await db.refresh(draft)

    await log_audit(db, user, "rebase_draft", "wiki_page_draft", str(draft.id))
    return await _draft_response(db, draft)
