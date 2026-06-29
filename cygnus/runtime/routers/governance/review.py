from __future__ import annotations

from fastapi import APIRouter, Depends

from cygnus.runtime.services.auth_service import get_current_user
from cygnus.review import OwnerState, ReviewHomeQuery, get_pressure_intake_review_queue_drilldown, sample_pressure_intake_records

router = APIRouter()


@router.get("/api/review-queue/{object_ref}")
def review_queue_item(
    object_ref: str,
    owner_state: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Queue-preserving governance drilldown compiled from the pressure intake bundle set."""
    review_query = (
        ReviewHomeQuery(owner_state=OwnerState(owner_state))
        if owner_state is not None
        else None
    )
    return get_pressure_intake_review_queue_drilldown(
        object_ref,
        records=sample_pressure_intake_records(),
        review_query=review_query,
    ).to_dict()
