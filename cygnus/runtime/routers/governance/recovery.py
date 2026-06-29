from __future__ import annotations

from fastapi import APIRouter, Depends

from cygnus.recovery import (
    DownstreamRealityCheckQuery,
    GovernanceOverviewQuery,
    RecoveryWindowQuery,
    get_downstream_reality_check_surface,
    get_governance_overview_surface,
    get_recovery_window_surface,
    sample_recovery_command_refs,
)
from cygnus.runtime.services.auth_service import get_current_user

router = APIRouter()


@router.get("/api/recovery/downstream-reality-check/{command_id}")
def downstream_reality_check(
    command_id: str,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Frontline recovery feedback for a specific governance command."""
    return get_downstream_reality_check_surface(
        DownstreamRealityCheckQuery(command_id=command_id)
    ).to_dict()


@router.get("/api/recovery/window/{command_id}")
def recovery_window(
    command_id: str,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Before/after recovery proof for a specific governance command."""
    return get_recovery_window_surface(
        RecoveryWindowQuery(command_id=command_id)
    ).to_dict()


@router.get("/api/recovery/overview")
def governance_overview(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Compare open loops to choose the next highest-leverage command."""
    return get_governance_overview_surface(
        GovernanceOverviewQuery(
            command_ids=tuple(ref.command_id for ref in sample_recovery_command_refs())
        )
    ).to_dict()
