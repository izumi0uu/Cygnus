from __future__ import annotations
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.signals import GovernanceSignalConflict
from cygnus.governance.ticket_import import (
    MAX_IMPORT_BYTES,
    TicketExportFormat,
    TicketImportValidationError,
    import_resolved_ticket_export,
)
from cygnus.governance.ticket_pilot import (
    TicketPilotFunnelQuery,
    get_ticket_pilot_funnel,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import require_admin

router = APIRouter()


@router.post(
    "/api/governance/ticket-imports",
    status_code=status.HTTP_201_CREATED,
    summary="Import a sanitized resolved-ticket export",
)
async def write_resolved_ticket_import(
    file: Annotated[UploadFile, File()],
    source_ref: Annotated[str, Form(min_length=1, max_length=300)],
    export_format: Annotated[TicketExportFormat, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Employee, Depends(require_admin)],
    minimum_cluster_size: Annotated[int, Form(ge=2, le=100)] = 3,
) -> dict[str, object]:
    """Validate the full export, then create review-bound governance signals atomically.

    ``source_ref`` identifies an immutable, already-sanitized export snapshot. Replaying
    the same snapshot is idempotent; reusing the reference for different cluster facts
    returns a conflict. Non-qualifying candidates are returned but never persisted as
    review work. No path in this endpoint approves or publishes knowledge.
    """

    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        result = await import_resolved_ticket_export(
            db,
            content,
            export_format=export_format,
            source_ref=source_ref,
            minimum_cluster_size=minimum_cluster_size,
            created_by_id=current_user.id,
        )
    except TicketImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.to_dict(),
        ) from exc
    except GovernanceSignalConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return result.to_dict()


@router.get(
    "/api/governance/ticket-pilot",
    summary="Read source-scoped ticket-to-knowledge pilot truth",
)
async def ticket_pilot_funnel(
    source_ref: Annotated[str, Query(min_length=1, max_length=300)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[Employee, Depends(require_admin)],
) -> dict[str, object]:
    """Read durable funnel truth without changing any governance state."""
    try:
        query = TicketPilotFunnelQuery(source_ref=source_ref)
        result = await get_ticket_pilot_funnel(db, query=query)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return result.to_dict()
