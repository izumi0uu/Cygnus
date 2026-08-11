from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.feedback_operations import (
    FeedbackRouteOperationsQuery,
    get_feedback_route_operation,
    list_feedback_route_operations,
)
from cygnus.governance.feedback_routing import FeedbackRouteKind, FeedbackRouteState
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import get_current_user


router = APIRouter()


@router.get("/api/governance/feedback-routes")
async def feedback_route_operations(
    current_user: Annotated[Employee, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    route_state: FeedbackRouteState | None = None,
    route_kind: FeedbackRouteKind | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    """List durable feedback-route operations truth inside the current Wiki scope."""

    result = await list_feedback_route_operations(
        db,
        current_user=current_user,
        query=FeedbackRouteOperationsQuery(
            route_state=route_state,
            route_kind=route_kind,
            page=page,
            page_size=page_size,
        ),
    )
    return result.to_dict()


@router.get("/api/governance/feedback-routes/{route_id}")
async def feedback_route_operation(
    route_id: uuid.UUID,
    current_user: Annotated[Employee, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Read one visible route without distinguishing hidden and absent IDs."""

    result = await get_feedback_route_operation(
        db,
        current_user=current_user,
        route_id=route_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="feedback route not found",
        )
    return result.to_dict()
