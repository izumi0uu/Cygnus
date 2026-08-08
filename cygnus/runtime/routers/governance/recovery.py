from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.recovery import (
    DurableRecoveryNotFound,
    DurableRecoveryUnavailable,
    get_durable_governance_overview,
    get_durable_downstream_reality_check,
    get_durable_recovery_proof,
    get_durable_recovery_window,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import get_current_user
from cygnus.runtime.services.permission_engine import build_wiki_scope_clause

router = APIRouter()


@router.get("/api/recovery/downstream-reality-check/{command_id}")
async def downstream_reality_check(
    command_id: str,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Frontline recovery feedback persisted after a governance command."""
    try:
        surface = await get_durable_downstream_reality_check(
            db,
            command_id=command_id,
            page_scope_clause=build_wiki_scope_clause(current_user),
        )
    except (DurableRecoveryNotFound, DurableRecoveryUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return surface.to_dict() | {"persisted": True, "rehearsal": False}


@router.get("/api/recovery/window/{command_id}")
async def recovery_window(
    command_id: str,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Before/after recovery proof compiled from durable governance truth."""
    try:
        surface = await get_durable_recovery_window(
            db,
            command_id=command_id,
            page_scope_clause=build_wiki_scope_clause(current_user),
        )
    except (DurableRecoveryNotFound, DurableRecoveryUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return surface.to_dict() | {"persisted": True, "rehearsal": False}


@router.get("/api/recovery/overview")
async def governance_overview(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Compare persisted visible recovery loops by governance leverage."""
    try:
        surface = await get_durable_governance_overview(
            db,
            page_scope_clause=build_wiki_scope_clause(current_user),
        )
    except DurableRecoveryUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return surface.to_dict() | {"persisted": True, "rehearsal": False}

@router.get("/api/recovery/{command_id}")
async def durable_recovery(
    command_id: str,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Canonical durable recovery lookup for one publication command."""
    return await recovery_window(
        command_id=command_id,
        current_user=current_user,
        db=db,
    )


@router.get("/api/recovery-proof")
async def recovery_proof(
    object_ref: str | None = None,
    action_key: str | None = None,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Resolve the latest durable recovery window for an object/action selection."""
    try:
        return await get_durable_recovery_proof(
            db,
            object_ref=object_ref,
            action_key=action_key,
            page_scope_clause=build_wiki_scope_clause(current_user),
        )
    except (DurableRecoveryNotFound, DurableRecoveryUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
