"""
Notifications REST router — in-app inbox for the current user.

Read-only inbox + mark-read endpoints. Writes happen elsewhere through
NotificationService (driven by ContributionService).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.database.models import Employee, Notification
from app.services.auth_service import get_current_user

router = APIRouter()


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: str
    subject: str
    body: str
    target_type: str
    target_id: str
    actor_id: Optional[uuid.UUID]
    read_at: Optional[str]
    created_at: str


def _to_response(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id,
        type=n.type,
        subject=n.subject,
        body=n.body or "",
        target_type=n.target_type,
        target_id=n.target_id,
        actor_id=n.actor_id,
        read_at=n.read_at.isoformat() if n.read_at else None,
        created_at=n.created_at.isoformat(),
    )


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    unread: bool = Query(False, description="Return only unread notifications"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """List notifications for the current user, newest first."""
    stmt = (
        select(Notification)
        .where(Notification.recipient_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_response(n) for n in rows]


@router.get("/notifications/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Return the unread count — cheap query for the header badge."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.recipient_id == user.id,
            Notification.read_at.is_(None),
        )
    )
    return {"count": int(result.scalar() or 0)}


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Mark one notification as read."""
    n = await db.get(Notification, notification_id)
    if not n or n.recipient_id != user.id:
        raise HTTPException(404, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(n)
    return _to_response(n)


@router.post("/notifications/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Mark every unread notification as read for the current user."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    await db.commit()
    return {"updated": result.rowcount or 0}
