from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from cygnus.review import (
    OwnerState,
    ReviewHomeQuery,
    ReviewQueueDrilldownQuery,
    get_review_queue_drilldown,
)
from cygnus.runtime.routers.governance.dependencies import (
    GovernanceReadSnapshot,
    get_governance_read_snapshot,
)

router = APIRouter()


@router.get("/api/review-queue/{object_ref}")
async def review_queue_item(
    object_ref: str,
    owner_state: str | None = None,
    snapshot: GovernanceReadSnapshot = Depends(get_governance_read_snapshot),
) -> dict[str, object]:
    """Queue-preserving drilldown compiled only from persisted signal rows."""
    try:
        review_query = (
            ReviewHomeQuery(owner_state=OwnerState(owner_state))
            if owner_state is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        return get_review_queue_drilldown(
            ReviewQueueDrilldownQuery(
                selected_object_ref=object_ref,
                home_query=review_query,
            ),
            bundles=snapshot.review_bundles,
        ).to_dict()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
