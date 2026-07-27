from __future__ import annotations

from fastapi import APIRouter, Depends

from cygnus.review import build_pressure_intake_surfaces, get_review_home_surface
from cygnus.review.drift import build_drift_governance_surface
from cygnus.review.source_blindness import build_source_blindness_surface
from cygnus.review.surface import ObservationState, SurfaceObservation
from cygnus.runtime.routers.governance.dependencies import (
    GovernanceReadSnapshot,
    get_governance_read_snapshot,
)

router = APIRouter()

def _review_observation(snapshot: GovernanceReadSnapshot) -> SurfaceObservation:
    return SurfaceObservation(
        state=ObservationState.PARTIAL,
        observed_count=snapshot.visible_source_count,
        reason="review_signal_coverage_partial",
        covered_signals=("source_status",),
        missing_signals=(
            "ticket_pressure",
            "release_delta",
            "incident_delta",
            "audience_conflict",
            "review_assignment",
            "source_impact",
        ),
    )


def _drift_observation() -> SurfaceObservation:
    return SurfaceObservation(
        state=ObservationState.UNAVAILABLE,
        observed_count=0,
        reason="drift_detectors_unavailable",
        missing_signals=("release_delta", "incident_delta", "ticket_pressure"),
    )


def _source_observation(snapshot: GovernanceReadSnapshot) -> SurfaceObservation:
    return SurfaceObservation(
        state=ObservationState.PARTIAL,
        observed_count=snapshot.visible_source_count,
        reason="source_impact_coverage_partial",
        covered_signals=("source_status",),
        missing_signals=("source_impact",),
    )


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/command-center")
async def command_center(
    snapshot: GovernanceReadSnapshot = Depends(get_governance_read_snapshot),
) -> dict[str, object]:
    """Request-scoped governed command surface without rehearsal bundles."""
    return get_review_home_surface(
        bundles=snapshot.review_bundles,
        observation=_review_observation(snapshot),
    ).to_dict()


@router.get("/api/drift")
async def drift(
    snapshot: GovernanceReadSnapshot = Depends(get_governance_read_snapshot),
) -> dict[str, object]:
    """Release/incident detector coverage, never a fabricated no-risk result."""
    return build_drift_governance_surface(
        snapshot.review_bundles,
        observation=_drift_observation(),
    ).to_dict()


@router.get("/api/source-blindness")
async def source_blindness(
    snapshot: GovernanceReadSnapshot = Depends(get_governance_read_snapshot),
) -> dict[str, object]:
    """Scoped source failures separated from unavailable impact inference."""
    return build_source_blindness_surface(
        snapshot.review_bundles,
        observation=_source_observation(snapshot),
        source_observations=snapshot.source_observations,
    ).to_dict()


@router.get("/api/review-intake")
async def review_intake(
    snapshot: GovernanceReadSnapshot = Depends(get_governance_read_snapshot),
) -> dict[str, object]:
    """Sparse governed intake preserving source facts without synthetic proposals."""
    return build_pressure_intake_surfaces(
        bundles=snapshot.review_bundles,
        review_observation=_review_observation(snapshot),
        source_observation=_source_observation(snapshot),
        source_observations=snapshot.source_observations,
    ).to_dict()
