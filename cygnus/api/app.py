from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cygnus.publish import (
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
    get_pressure_intake_recovery_proof_surface,
)
from cygnus.recovery import (
    DownstreamRealityCheckQuery,
    GovernanceOverviewQuery,
    RecoveryWindowQuery,
    get_downstream_reality_check_surface,
    get_governance_overview_surface,
    get_recovery_window_surface,
    sample_recovery_command_refs,
)
from cygnus.review import (
    OwnerState,
    ReviewHomeQuery,
    build_pressure_intake_surfaces,
    get_pressure_intake_review_queue_drilldown,
    get_review_home_surface,
    sample_pressure_intake_records,
)

app = FastAPI(
    title="Cygnus API",
    version="0.1.0",
    description="HTTP surface over the Cygnus domain kernel.",
)

# Dev-open CORS: restrict to the real frontend origin before any non-local deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/command-center")
def command_center() -> dict[str, object]:
    """Risk-ranked morning command brief for the Command Center surface."""
    return get_review_home_surface().to_dict()


@app.get("/api/review-intake")
def review_intake() -> dict[str, object]:
    """Surface-ready review intake compiled from support pressure and source-loss signals."""
    return build_pressure_intake_surfaces(sample_pressure_intake_records()).to_dict()


@app.get("/api/review-queue/{object_ref}")
def review_queue_item(object_ref: str, owner_state: str | None = None) -> dict[str, object]:
    """Queue-preserving governance drilldown compiled from the pressure intake bundle set."""
    review_query = ReviewHomeQuery(owner_state=OwnerState(owner_state)) if owner_state is not None else None
    return get_pressure_intake_review_queue_drilldown(
        object_ref,
        records=sample_pressure_intake_records(),
        review_query=review_query,
    ).to_dict()


@app.get("/api/publish-preview")
def publish_preview(object_ref: str | None = None, action_key: str | None = None) -> dict[str, object]:
    """Blast-radius-first publish surface compiled from the same pressure intake bundle set."""
    return get_pressure_intake_publish_preview_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@app.get("/api/publish-propagation")
def publish_propagation(object_ref: str | None = None, action_key: str | None = None) -> dict[str, object]:
    """Supporting-surface propagation theater compiled from the current publish command rehearsal."""
    return get_pressure_intake_publish_propagation_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@app.get("/api/recovery-proof")
def recovery_proof(object_ref: str | None = None, action_key: str | None = None) -> dict[str, object]:
    """Frontline reality-check surface proving whether a governance command changed support behavior."""
    return get_pressure_intake_recovery_proof_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@app.get("/api/recovery/downstream-reality-check/{command_id}")
def downstream_reality_check(command_id: str) -> dict[str, object]:
    """Frontline recovery feedback for a specific governance command."""
    return get_downstream_reality_check_surface(
        DownstreamRealityCheckQuery(command_id=command_id)
    ).to_dict()


@app.get("/api/recovery/window/{command_id}")
def recovery_window(command_id: str) -> dict[str, object]:
    """Before/after recovery proof for a specific governance command."""
    return get_recovery_window_surface(
        RecoveryWindowQuery(command_id=command_id)
    ).to_dict()


@app.get("/api/recovery/overview")
def governance_overview() -> dict[str, object]:
    """Compare open loops to choose the next highest-leverage command."""
    return get_governance_overview_surface(
        GovernanceOverviewQuery(
            command_ids=tuple(ref.command_id for ref in sample_recovery_command_refs())
        )
    ).to_dict()
