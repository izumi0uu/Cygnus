from __future__ import annotations

from fastapi import APIRouter, Depends

from cygnus.runtime.services.auth_service import get_current_user
from cygnus.review import build_pressure_intake_surfaces, get_review_home_surface, sample_pressure_intake_records
from cygnus.review.drift import get_drift_governance_surface
from cygnus.review.source_blindness import get_source_blindness_surface

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/command-center")
def command_center(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Risk-ranked morning command brief for the Command Center surface."""
    return get_review_home_surface().to_dict()


@router.get("/api/drift")
def drift(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Release/incident drift governance surface — freshness loss forcing a governance path."""
    return get_drift_governance_surface().to_dict()


@router.get("/api/source-blindness")
def source_blindness(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Source-blindness governance surface — sync loss expressed as governance loss, not noise."""
    return get_source_blindness_surface().to_dict()


@router.get("/api/review-intake")
def review_intake(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Surface-ready review intake compiled from support pressure and source-loss signals."""
    return build_pressure_intake_surfaces(sample_pressure_intake_records()).to_dict()
