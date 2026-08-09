"""
Notifications REST router — in-app inbox for the current user.

Read-only inbox + mark-read endpoints. Writes happen elsewhere through
NotificationService (driven by ContributionService).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee, Notification
from cygnus.runtime.services.auth_service import get_current_user

router = APIRouter()


class NotificationLifecycle(str, Enum):
    UNREAD = "unread"
    READ = "read"


class NotificationResponse(BaseModel):
    id: uuid.UUID
    trace_ref: str
    type: str
    subject: str
    body: str
    target_type: str
    target_id: str
    actor_id: uuid.UUID | None
    lifecycle_state: NotificationLifecycle
    read_at: str | None
    created_at: str
    persisted: bool


def _to_response(notification: Notification) -> NotificationResponse:
    lifecycle = (
        NotificationLifecycle.READ
        if notification.read_at is not None
        else NotificationLifecycle.UNREAD
    )
    return NotificationResponse(
        id=notification.id,
        trace_ref=f"notification:{notification.id}",
        type=notification.type,
        subject=notification.subject,
        body=notification.body or "",
        target_type=notification.target_type,
        target_id=notification.target_id,
        actor_id=notification.actor_id,
        lifecycle_state=lifecycle,
        read_at=(notification.read_at.isoformat() if notification.read_at else None),
        created_at=notification.created_at.isoformat(),
        persisted=True,
    )


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[Employee, Depends(get_current_user)],
    lifecycle_state: NotificationLifecycle | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationResponse]:
    """List durable notifications inside the current recipient scope."""
    statement = (
        select(Notification)
        .where(Notification.recipient_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if lifecycle_state is NotificationLifecycle.UNREAD:
        statement = statement.where(Notification.read_at.is_(None))
    elif lifecycle_state is NotificationLifecycle.READ:
        statement = statement.where(Notification.read_at.is_not(None))
    rows = (await db.execute(statement)).scalars().all()
    return [_to_response(notification) for notification in rows]


@router.get("/notifications/unread-count")
async def unread_count(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[Employee, Depends(get_current_user)],
) -> dict[str, object]:
    """Return the durable unread count inside the current recipient scope."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.recipient_id == user.id,
            Notification.read_at.is_(None),
        )
    )
    return {
        "count": int(result.scalar() or 0),
        "lifecycle_state": NotificationLifecycle.UNREAD.value,
        "persisted": True,
    }


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[Employee, Depends(get_current_user)],
) -> NotificationResponse:
    """Idempotently transition one recipient-owned notification to read."""
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if notification is None:
        raise HTTPException(404, "Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(notification)
    return _to_response(notification)


@router.post("/notifications/read-all")
async def mark_all_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[Employee, Depends(get_current_user)],
) -> dict[str, object]:
    """Transition every unread record in the current recipient scope to read."""
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
    return {
        "updated": int(getattr(result, "rowcount", 0) or 0),
        "lifecycle_state": NotificationLifecycle.READ.value,
        "persisted": True,
    }
