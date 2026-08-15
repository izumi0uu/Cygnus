from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.review_assignments import (
    REVIEW_ASSIGNMENT_REASON_MAX_LENGTH,
    REVIEW_ASSIGNMENT_REF_MAX_LENGTH,
    ReviewAssignmentAction,
    ReviewAssignmentCommand,
    ReviewAssignmentConflict,
    apply_review_assignment_command,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import require_admin

router = APIRouter()


class ReviewAssignmentCommandRequest(BaseModel):
    command_id: str = Field(
        min_length=1,
        max_length=REVIEW_ASSIGNMENT_REF_MAX_LENGTH,
    )
    action: ReviewAssignmentAction
    owner_ref: str | None = Field(
        default=None,
        max_length=REVIEW_ASSIGNMENT_REF_MAX_LENGTH,
    )
    reason: str = Field(
        min_length=1,
        max_length=REVIEW_ASSIGNMENT_REASON_MAX_LENGTH,
    )
    expected_version: int = Field(ge=1)

    def to_domain(self) -> ReviewAssignmentCommand:
        return ReviewAssignmentCommand(
            command_id=self.command_id,
            action=self.action,
            owner_ref=self.owner_ref,
            reason=self.reason,
            expected_version=self.expected_version,
        )


@router.post("/api/review-assignments/{signal_ref}/commands")
async def command_review_assignment(
    signal_ref: str,
    body: ReviewAssignmentCommandRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Employee, Depends(require_admin)],
) -> dict[str, object]:
    """Apply one idempotent, version-checked owner lifecycle transition."""
    try:
        result = await apply_review_assignment_command(
            db,
            signal_ref=signal_ref,
            command=body.to_domain(),
            actor_id=current_user.id,
        )
    except ReviewAssignmentConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review assignment not found",
        )
    return result.to_dict()
