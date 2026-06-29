from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from cygnus.publish import (
    apply_pressure_intake_publish_action,
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
    get_pressure_intake_recovery_proof_surface,
    projection_store,
)
from cygnus.runtime.services.auth_service import get_current_user, require_admin
from cygnus.review import sample_pressure_intake_records

router = APIRouter()


class PublishApplyRequest(BaseModel):
    object_ref: str | None = None
    action_key: str
    reason: str | None = None


@router.get("/api/publish-preview")
def publish_preview(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Blast-radius-first publish surface compiled from the same pressure intake bundle set."""
    return get_pressure_intake_publish_preview_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@router.post("/api/publish/apply")
def publish_apply(
    body: PublishApplyRequest,
    _current_user=Depends(require_admin),
) -> dict[str, object]:
    """Execute a real publish governance command and return the full result."""
    try:
        result = apply_pressure_intake_publish_action(
            selected_object_ref=body.object_ref,
            action_key=body.action_key,
            records=sample_pressure_intake_records(),
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
    projection_store.remember(
        payload["updated_candidate"]["object_id"],
        selected_action=body.action_key,
        result=result,
    )
    return payload


@router.get("/api/publish-propagation")
def publish_propagation(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Supporting-surface propagation theater compiled from the current publish command rehearsal."""
    return get_pressure_intake_publish_propagation_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@router.get("/api/recovery-proof")
def recovery_proof(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Frontline reality-check surface proving whether a governance command changed support behavior."""
    return get_pressure_intake_recovery_proof_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()
