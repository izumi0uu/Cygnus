"""
Wiki Branch router — named contribution branches, batch reviews, and atomic merges.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.review import branches as branch_service
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    WikiBranch,
    WikiPageDraft,
    WikiPage,
)
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

    try:
        await branch_service.submit_wiki_branch(db, branch, user)
    except branch_service.InvalidTransition as e:
        message = str(e)
        status = 403 if "Only the branch author" in message else 400
        raise HTTPException(status, message)

    await db.commit()
    await db.refresh(branch)
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

    try:
        await branch_service.close_wiki_branch(
            db,
            branch,
            user,
            reviewer_override=is_reviewer,
        )
    except branch_service.InvalidTransition as e:
        message = str(e)
        status = 403 if "permission" in message.lower() else 400
        raise HTTPException(status, message)

    await db.commit()
    await db.refresh(branch)
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

    try:
        await branch_service.merge_wiki_branch(
            db,
            branch,
            user,
            reviewer_note=body.reviewer_note,
        )
        await db.commit()
    except branch_service.BranchMergeConflict as e:
        await db.commit()
        raise HTTPException(409, str(e))
    except branch_service.InvalidTransition as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, f"Branch merge failed: {str(e)}")

    await db.refresh(branch)
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

    draft = await db.get(WikiPageDraft, draft_id)
    if not draft or draft.branch_id != branch_id:
        raise HTTPException(404, "Draft not found in this branch")

    try:
        await branch_service.rebase_wiki_branch_draft(
            db,
            branch,
            draft,
            user,
            body.resolved_content_md,
        )
    except branch_service.InvalidTransition as e:
        message = str(e)
        if "Only the branch author" in message:
            raise HTTPException(403, message)
        raise HTTPException(400, message)
    except ValueError as e:
        raise HTTPException(404, str(e))

    await db.commit()
    await db.refresh(draft)
    return await _draft_response(db, draft)
