from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cygnus.recovery import (
    DownstreamRealityCheckQuery,
    RecoveryWindowQuery,
    get_downstream_reality_check_surface,
    get_recovery_window_surface,
)
from cygnus.review import get_review_home_surface

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
