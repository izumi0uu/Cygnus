from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.governance.audience_bindings import (
    AudienceBindingConflict,
    AudienceBindingCreate,
    AudienceBindingLifecycle,
    AudienceBindingNotFound,
    audience_binding_to_dict,
    create_audience_binding,
    detect_audience_binding_conflicts,
    list_audience_bindings,
    update_audience_binding_lifecycle,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import require_admin

router = APIRouter()


class AudienceBindingCreateRequest(BaseModel):
    page_id: uuid.UUID
    object_ref: str
    variant_ref: str
    channel: str
    visibility: Visibility
    brands: list[str] = Field(default_factory=list)
    product_lines: list[str] = Field(default_factory=list)
    plans: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    product_versions: list[str] = Field(default_factory=list)


class AudienceBindingLifecycleRequest(BaseModel):
    lifecycle_state: AudienceBindingLifecycle
    expected_version: int = Field(ge=1)


@router.post(
    "/api/governance/audience-bindings",
    status_code=status.HTTP_201_CREATED,
)
async def create_governance_audience_binding(
    body: AudienceBindingCreateRequest,
    current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        record, replayed = await create_audience_binding(
            db,
            command=AudienceBindingCreate(
                page_id=body.page_id,
                object_ref=body.object_ref,
                variant_ref=body.variant_ref,
                channel=body.channel,
                audience_filter=AudienceFilter(
                    visibility=body.visibility,
                    brands=tuple(body.brands),
                    product_lines=tuple(body.product_lines),
                    plans=tuple(body.plans),
                    regions=tuple(body.regions),
                    languages=tuple(body.languages),
                    product_versions=tuple(body.product_versions),
                ),
            ),
            actor_id=current_user.id,
        )
    except AudienceBindingNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except AudienceBindingConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return audience_binding_to_dict(record) | {"replayed": replayed}


@router.get("/api/governance/audience-bindings")
async def list_governance_audience_bindings(
    page_id: uuid.UUID | None = None,
    object_ref: str | None = None,
    channel: str | None = None,
    lifecycle_state: AudienceBindingLifecycle | None = None,
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    records = await list_audience_bindings(
        db,
        page_id=page_id,
        object_ref=object_ref,
        channel=channel,
        lifecycle_state=lifecycle_state,
    )
    conflicts = detect_audience_binding_conflicts(records)
    return {
        "bindings": [audience_binding_to_dict(record) for record in records],
        "conflicts": [conflict.to_dict() for conflict in conflicts],
        "covered_signals": ["audience_conflict"],
        "observed_count": len(conflicts),
    }


@router.post("/api/governance/audience-bindings/{binding_id}/lifecycle")
async def update_governance_audience_binding_lifecycle(
    binding_id: uuid.UUID,
    body: AudienceBindingLifecycleRequest,
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        record, replayed = await update_audience_binding_lifecycle(
            db,
            binding_id=binding_id,
            lifecycle_state=body.lifecycle_state,
            expected_version=body.expected_version,
        )
    except AudienceBindingNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except AudienceBindingConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return audience_binding_to_dict(record) | {"replayed": replayed}
