from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.audit import (
    GovernanceAuditPhase,
    GovernanceAuditQuery,
    get_governance_audit_event,
    list_governance_audit_events,
)
from cygnus.governance.ledger import GovernanceEventType
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import get_current_user

router = APIRouter()


@router.get("/api/governance/audit")
async def governance_audit(
    current_user: Annotated[Employee, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    phase: GovernanceAuditPhase | None = None,
    event_type: GovernanceEventType | None = None,
    draft_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    """List durable governance transitions inside the current Wiki read scope."""
    result = await list_governance_audit_events(
        db,
        current_user=current_user,
        query=GovernanceAuditQuery(
            phase=phase,
            event_type=event_type,
            draft_id=draft_id,
            page_id=page_id,
            actor_id=actor_id,
            page=page,
            page_size=page_size,
        ),
    )
    return result.to_dict()


@router.get("/api/governance/audit/{event_id}")
async def governance_audit_event(
    current_user: Annotated[Employee, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    event_id: uuid.UUID,
) -> dict[str, object]:
    """Read one durable governance transition without revealing hidden IDs."""
    event = await get_governance_audit_event(
        db,
        current_user=current_user,
        event_id=event_id,
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="governance audit event not found",
        )
    return event.to_dict()
