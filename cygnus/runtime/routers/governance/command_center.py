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
    missing_signals = (
        ("audience_binding_resolution",)
        if snapshot.uncompiled_signal_count
        else ()
    )
    return SurfaceObservation(
        state=(
            ObservationState.PARTIAL
            if missing_signals
            else ObservationState.READY
        ),
        observed_count=(
            len(snapshot.governance_signals)
            + snapshot.audience_conflict_count
            + len(snapshot.source_observations)
        ),
        reason=(
            "persisted_governance_signal_provider_partial"
            if missing_signals
            else "persisted_governance_signal_provider_ready"
        ),
        covered_signals=(
            "ticket_cluster",
            "human_rewrite",
            "source_failure",
            "release_delta",
            "incident_delta",
            "audience_conflict",
            "review_assignment",
            "source_impact",
        ),
        missing_signals=missing_signals,
    )


def _drift_observation(snapshot: GovernanceReadSnapshot) -> SurfaceObservation:
    drift_count = sum(
        bundle.signal.risk_type.value == "drift" for bundle in snapshot.review_bundles
    )
    missing_signals = (
        ("audience_binding_resolution",)
        if any(
            signal_type in {"release_delta", "incident_delta"}
            for signal_type in snapshot.uncompiled_signal_types
        )
        else ()
    )
    return SurfaceObservation(
        state=(ObservationState.PARTIAL if missing_signals else ObservationState.READY),
        observed_count=drift_count,
        reason=(
            "persisted_drift_provider_partial"
            if missing_signals
            else "persisted_drift_provider_ready"
        ),
        covered_signals=("release_delta", "incident_delta"),
        missing_signals=missing_signals,
    )


def _source_observation(snapshot: GovernanceReadSnapshot) -> SurfaceObservation:
    source_risk_count = sum(
        bundle.signal.risk_type.value == "source_blindness"
        for bundle in snapshot.review_bundles
    )
    return SurfaceObservation(
        state=ObservationState.READY,
        observed_count=len(snapshot.source_observations) + source_risk_count,
        reason=(
            "source_impact_observed"
            if snapshot.source_observations
            else "persisted_source_failure_provider_ready"
        ),
        covered_signals=("source_status", "source_failure", "source_impact"),
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
        observation=_drift_observation(snapshot),
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
