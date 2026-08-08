from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance import event_to_dict, list_draft_events
from cygnus.publish import (
    DurablePublishCommand,
    DurablePublishConflict,
    DurablePublishDenied,
    DurablePublishNotFound,
    PropagationStatus,
    PropagationUpdateCommand,
    apply_durable_publish,
    apply_pressure_intake_publish_action,
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
    get_publication,
    list_draft_publications,
    list_publication_propagations,
    publication_to_dict,
    remember_publish_projection,
    update_propagation,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee, WikiPageDraft
from cygnus.runtime.services.auth_service import get_current_user, require_admin

router = APIRouter()


class PublishApplyRequest(BaseModel):
    object_ref: str | None = None
    action_key: str
    reason: str | None = None
    draft_id: uuid.UUID | None = None
    approval_ref: uuid.UUID | None = None
    command_id: str | None = None
    target_channels: list[str] | None = None


class PropagationUpdateRequest(BaseModel):
    status: PropagationStatus
    expected_version: int
    command_id: str
    reason: str
    follow_up_commands: list[str] = Field(default_factory=list)


@router.get("/api/publish-preview")
def publish_preview(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user: Employee = Depends(get_current_user),
) -> dict[str, object]:
    """Blast-radius-first publish surface compiled from the same pressure intake bundle set."""
    return get_pressure_intake_publish_preview_surface(
        selected_object_ref=object_ref,
        action_key=action_key,
    ).to_dict()


@router.post("/api/publish/apply")
async def publish_apply(
    body: PublishApplyRequest,
    current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Execute either a qualified durable command or an explicit fixture rehearsal."""
    if body.draft_id is not None:
        if body.object_ref is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="durable publish accepts draft_id, not object_ref",
            )
        missing = [
            field_name
            for field_name, value in (
                ("approval_ref", body.approval_ref),
                ("command_id", body.command_id),
                ("target_channels", body.target_channels),
            )
            if value is None
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"durable publish requires: {', '.join(missing)}",
            )
        try:
            command = DurablePublishCommand(
                draft_id=body.draft_id,
                approval_ref=cast(uuid.UUID, body.approval_ref),
                command_id=cast(str, body.command_id),
                action_key=body.action_key,
                target_channels=tuple(body.target_channels or ()),
                reason=body.reason,
            )
            return await apply_durable_publish(
                db,
                command=command,
                actor_id=current_user.id,
            )
        except DurablePublishNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except (DurablePublishConflict, DurablePublishDenied) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    if any(
        value is not None
        for value in (
            body.approval_ref,
            body.command_id,
            body.target_channels,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approval_ref, command_id, and target_channels require draft_id",
        )

    try:
        result = apply_pressure_intake_publish_action(
            selected_object_ref=body.object_ref,
            action_key=body.action_key,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    payload = result.to_dict()
    payload["rehearsal"] = True
    payload["persisted"] = False
    payload["selected_action"] = body.action_key
    _ = remember_publish_projection(
        result.updated_candidate.object_id,
        selected_action=body.action_key,
        result=result,
    )
    return payload


@router.get("/api/publish-propagation")
def publish_propagation(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user: Employee = Depends(get_current_user),
) -> dict[str, object]:
    """Supporting-surface propagation theater compiled from the current publish command rehearsal."""
    return get_pressure_intake_publish_propagation_surface(
        selected_object_ref=object_ref,
        action_key=action_key,
    ).to_dict()


@router.get("/api/governance-ledger/drafts/{draft_id}")
async def governance_draft_ledger(
    draft_id: uuid.UUID,
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    draft = await db.get(WikiPageDraft, draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"draft_id={draft_id} was not found",
        )
    events = await list_draft_events(db, draft_id)
    publications = await list_draft_publications(db, draft_id)
    publication_payloads: list[dict[str, object]] = []
    for publication in publications:
        propagations = await list_publication_propagations(db, publication.id)
        publication_payloads.append(
            publication_to_dict(publication, propagations=propagations)
        )
    return {
        "draft_id": str(draft.id),
        "draft_status": draft.status,
        "events": [event_to_dict(event) for event in events],
        "publications": publication_payloads,
    }


@router.get("/api/governance-publications/{publication_id}")
async def governance_publication(
    publication_id: uuid.UUID,
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    publication = await get_publication(db, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"publication_id={publication_id} was not found",
        )
    propagations = await list_publication_propagations(db, publication.id)
    return publication_to_dict(publication, propagations=propagations)


@router.post("/api/governance-publications/{publication_id}/propagation/{surface_id}")
async def update_governance_propagation(
    publication_id: uuid.UUID,
    surface_id: str,
    body: PropagationUpdateRequest,
    current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        command = PropagationUpdateCommand(
            publication_id=publication_id,
            surface_id=surface_id,
            status=body.status,
            expected_version=body.expected_version,
            command_id=body.command_id,
            reason=body.reason,
            follow_up_commands=tuple(body.follow_up_commands),
        )
        return await update_propagation(
            db,
            command=command,
            actor_id=current_user.id,
        )
    except DurablePublishNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DurablePublishConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
