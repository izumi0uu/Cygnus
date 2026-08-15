from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance import (
    GovernanceSignalStatus,
    audience_filter_from_binding,
    event_to_dict,
    governance_signal_to_pressure_record,
    list_draft_events,
    list_governance_signals,
)
from cygnus.publish import (
    DurablePublishCommand,
    DurablePublishConflict,
    DurablePublishDenied,
    DurablePublishNotFound,
    PropagationStatus,
    PropagationUpdateCommand,
    apply_durable_publish,
    apply_pressure_intake_publish_action,
    durable_publish_command_for_signal,
    persisted_publish_candidate_for_signal,
    get_publication,
    list_draft_publications,
    list_publication_propagations,
    propagation_to_dict,
    publication_to_dict,
    remember_publish_projection,
    update_propagation,
)
from cygnus.publish.delivery import (
    DeliveryAckConflict,
    DeliveryReceiptNotFound,
    DeliveryStatus,
    DeliveryVerificationError,
    acknowledge_propagation_delivery,
    delivery_to_dict,
    list_propagation_deliveries,
)
from cygnus.publish.surface import get_pressure_intake_publish_preview_surface
from cygnus.review import (
    get_pressure_intake_review_brief_surface,
    is_feedback_derived_signal_type,
)
from cygnus.runtime.config import get_settings
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    GovernanceAudienceBinding,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
    WikiPage,
    WikiPageDraft,
)
from cygnus.runtime.services.auth_service import get_current_user, require_admin
from cygnus.runtime.services.permission_engine import build_wiki_scope_clause

router = APIRouter()

_ACK_BODY_LIMIT = 1024 * 1024
_DELIVERY_QUERY_LIMIT_MAX = 200


class PublishApplyRequest(BaseModel):
    object_ref: str | None = None
    action_key: str
    reason: str | None = None
    draft_id: uuid.UUID | None = None
    approval_ref: uuid.UUID | None = None
    approval_digest: str | None = None
    scope_digest: str | None = None
    signal_id: uuid.UUID | None = None
    signal_freshness: str | None = None
    command_id: str | None = None
    target_channels: list[str] | None = None
    expected_version: int | None = Field(default=None, ge=1)


class PropagationUpdateRequest(BaseModel):
    status: PropagationStatus
    expected_version: int
    command_id: str
    reason: str
    follow_up_commands: list[str] = Field(default_factory=list)


@router.get("/api/publish-preview")
async def publish_preview(
    object_ref: str | None = None,
    action_key: str | None = None,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Compile preview only from persisted, request-scoped governance signals."""
    signals = await list_governance_signals(
        db,
        current_user=current_user,
        status=GovernanceSignalStatus.ACTIVE,
    )
    wiki_scope = build_wiki_scope_clause(current_user)
    records = []
    record_signals = []
    for signal in signals:
        if is_feedback_derived_signal_type(signal.signal_type):
            continue
        audience_override = None
        if signal.audience_filter is None and signal.audience_binding_ref is not None:
            binding_statement = (
                select(GovernanceAudienceBinding)
                .join(
                    WikiPage,
                    WikiPage.id == GovernanceAudienceBinding.page_id,
                )
                .where(
                    GovernanceAudienceBinding.binding_key
                    == signal.audience_binding_ref,
                    GovernanceAudienceBinding.page_id == signal.page_id,
                    GovernanceAudienceBinding.object_ref == signal.object_ref,
                )
            )
            if wiki_scope is not None:
                binding_statement = binding_statement.where(wiki_scope)
            binding = (await db.execute(binding_statement)).scalar_one_or_none()
            if binding is None:
                continue
            audience_override = audience_filter_from_binding(binding)
        records.append(
            governance_signal_to_pressure_record(
                signal,
                audience_filter=audience_override,
            )
        )
        record_signals.append(signal)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no persisted publish intake records are available in this scope",
        )

    queue_surface = get_pressure_intake_review_brief_surface(records=tuple(records))
    selected_object_ref = (
        object_ref
        if object_ref is not None
        else queue_surface.priority_stack[0].object_ref
        if queue_surface.priority_stack
        else None
    )
    selected_signal = next(
        (
            signal
            for signal in record_signals
            if signal.object_ref == selected_object_ref
        ),
        None,
    )
    if selected_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"object_ref={selected_object_ref} has no persisted signal",
        )
    candidate = await persisted_publish_candidate_for_signal(
        db,
        signal=selected_signal,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"object_ref={selected_object_ref} has no explicit active audience "
                "binding truth"
            ),
        )

    try:
        surface = get_pressure_intake_publish_preview_surface(
            selected_object_ref=selected_object_ref,
            records=tuple(records),
            action_key=action_key,
            candidate_override=candidate,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if action_key is not None and "action" in str(exc).lower()
                else status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    payload = surface.to_dict()
    payload["persisted"] = True
    payload["rehearsal"] = False
    durable_command = await durable_publish_command_for_signal(
        db,
        signal=selected_signal,
        action_key=action_key,
    )
    if durable_command is not None:
        payload["durable_command"] = durable_command
    return payload


@router.post("/api/publish/apply")
async def publish_apply(
    body: PublishApplyRequest,
    request: Request,
    current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Execute either a qualified durable command or an explicit fixture rehearsal."""
    correlation_id, traceparent = _request_correlation(request)
    if body.draft_id is not None:
        if body.object_ref is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="durable publish accepts draft_id, not object_ref",
            )
        missing = [
            field_name
            for field_name, value in (
                ("approval_ref", body.approval_ref),
                ("approval_digest", body.approval_digest),
                ("scope_digest", body.scope_digest),
                ("signal_id", body.signal_id),
                ("signal_freshness", body.signal_freshness),
                ("command_id", body.command_id),
                ("target_channels", body.target_channels),
                ("expected_version", body.expected_version),
            )
            if value is None
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"durable publish requires: {', '.join(missing)}",
            )
        try:
            command = DurablePublishCommand(
                draft_id=body.draft_id,
                approval_ref=cast(uuid.UUID, body.approval_ref),
                approval_digest=cast(str, body.approval_digest),
                scope_digest=cast(str, body.scope_digest),
                signal_id=cast(uuid.UUID, body.signal_id),
                signal_freshness=cast(str, body.signal_freshness),
                command_id=cast(str, body.command_id),
                action_key=body.action_key,
                target_channels=tuple(body.target_channels or ()),
                reason=body.reason,
                expected_version=cast(int, body.expected_version),
            )
            return await apply_durable_publish(
                db,
                command=command,
                actor_id=current_user.id,
                correlation_id=correlation_id,
                traceparent=traceparent,
            )
        except DurablePublishNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except (DurablePublishConflict, DurablePublishDenied) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    if any(
        value is not None
        for value in (
            body.approval_ref,
            body.command_id,
            body.target_channels,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approval_ref, command_id, and target_channels require draft_id",
        )

    try:
        result = apply_pressure_intake_publish_action(
            selected_object_ref=body.object_ref,
            action_key=body.action_key,
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
    _ = remember_publish_projection(
        result.updated_candidate.object_id,
        selected_action=body.action_key,
        result=result,
    )
    return payload


@router.get("/api/publish-propagation")
async def publish_propagation(
    publication_id: uuid.UUID | None = None,
    object_ref: str | None = None,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return durable publication and propagation truth; never synthesize rehearsal rows."""
    if publication_id is None and object_ref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="publication_id or object_ref is required for durable propagation",
        )
    wiki_scope = build_wiki_scope_clause(current_user)
    statement = select(GovernancePublication).join(
        WikiPage, WikiPage.id == GovernancePublication.page_id
    )
    if publication_id is not None:
        statement = statement.where(GovernancePublication.id == publication_id)
    else:
        statement = statement.where(GovernancePublication.object_ref == object_ref)
    if wiki_scope is not None:
        statement = statement.where(wiki_scope)
    statement = statement.order_by(
        GovernancePublication.published_at.desc(),
        GovernancePublication.id.desc(),
    ).limit(1)
    publication = (await db.execute(statement)).scalar_one_or_none()
    if publication is None:
        selector = (
            f"publication_id={publication_id}"
            if publication_id is not None
            else f"object_ref={object_ref}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{selector} has no visible durable publication",
        )
    propagations = await list_publication_propagations(db, publication.id)
    deliveries = await list_propagation_deliveries(
        db, tuple(item.id for item in propagations)
    )
    delivery_by_propagation = {
        delivery.propagation_id: delivery for delivery in deliveries
    }
    records = [
        propagation_to_dict(
            record,
            delivery=delivery_by_propagation.get(record.id),
        )
        for record in propagations
    ]
    summary = {item.value: 0 for item in PropagationStatus}
    for record in propagations:
        summary[record.status] = summary.get(record.status, 0) + 1
    unresolved = [
        record.surface_id
        for record in propagations
        if record.status != PropagationStatus.SYNCED.value
    ]
    continue_commands = list(
        dict.fromkeys(
            command
            for record in propagations
            if record.status != PropagationStatus.SYNCED.value
            for command in record.follow_up_commands
        )
    )
    title = str(publication.candidate.get("title") or publication.object_ref)
    lane_notes = {
        PropagationStatus.SYNCED: "Downstream confirmation is recorded.",
        PropagationStatus.PENDING: "Downstream confirmation is still pending.",
        PropagationStatus.FAILED: "The persisted propagation attempt failed.",
        PropagationStatus.MANUAL_ACTION_REQUIRED: "A persisted manual action is required.",
    }
    status_lanes = [
        {
            "status": lane.value,
            "headline": lane.value.replace("_", " ").title(),
            "note": lane_notes[lane],
            "count": summary[lane.value],
            "surface_ids": [
                record.surface_id
                for record in propagations
                if record.status == lane.value
            ],
        }
        for lane in PropagationStatus
    ]
    return {
        "surface_id": "publish-propagation",
        "headline": f"Durable propagation for {title}",
        "summary": "Persisted downstream propagation state for this publication.",
        "propagation_ledger": {
            "object_id": publication.object_ref,
            "title": title,
            "action_log": list(publication.action_log),
            "summary": summary,
            "records": records,
            "unresolved_surfaces": unresolved,
            "continue_commands": continue_commands,
        },
        "status_lanes": status_lanes,
        "selected_position": 0,
        "total_items": 1,
        "action_presets": [],
        "selected_action": publication.action_key,
        "action_echo": {
            "selected_action": publication.action_key,
            "summary": "Persisted action result for this publication.",
            "action_log": list(publication.action_log),
            "opened_bindings": list(publication.opened_bindings),
            "removed_bindings": list(publication.removed_bindings),
            "held_bindings": list(publication.held_bindings),
        },
        "previous_object_ref": None,
        "next_object_ref": None,
        "context_notes": [],
        "persisted": True,
        "rehearsal": False,
        "publication_record_id": str(publication.id),
        "command_id": publication.command_id,
    }


@router.get("/api/governance-ledger/drafts/{draft_id}")
async def governance_draft_ledger(
    draft_id: uuid.UUID,
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    draft = await db.get(WikiPageDraft, draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"draft_id={draft_id} was not found",
        )
    events = await list_draft_events(db, draft_id)
    publications = await list_draft_publications(db, draft_id)
    publication_payloads: list[dict[str, object]] = []
    for publication in publications:
        propagations = await list_publication_propagations(db, publication.id)
        publication_payloads.append(
            publication_to_dict(publication, propagations=propagations)
        )
    return {
        "draft_id": str(draft.id),
        "draft_status": draft.status,
        "events": [event_to_dict(event) for event in events],
        "publications": publication_payloads,
    }


@router.get("/api/governance-publications/{publication_id}")
async def governance_publication(
    publication_id: uuid.UUID,
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    publication = await get_publication(db, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"publication_id={publication_id} was not found",
        )
    propagations = await list_publication_propagations(db, publication.id)
    return publication_to_dict(publication, propagations=propagations)


@router.post("/api/governance-publications/{publication_id}/propagation/{surface_id}")
async def update_governance_propagation(
    publication_id: uuid.UUID,
    surface_id: str,
    body: PropagationUpdateRequest,
    current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        command = PropagationUpdateCommand(
            publication_id=publication_id,
            surface_id=surface_id,
            status=body.status,
            expected_version=body.expected_version,
            command_id=body.command_id,
            reason=body.reason,
            follow_up_commands=tuple(body.follow_up_commands),
        )
        return await update_propagation(
            db,
            command=command,
            actor_id=current_user.id,
        )
    except DurablePublishNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DurablePublishConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except DurablePublishDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/api/internal/propagation-ack")
async def propagation_ack(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Accept one signed downstream acknowledgment for a durable delivery.

    Authentication is the HMAC-SHA256 signature over the exact request body
    (``X-Cygnus-Ack-Signature: sha256=<hex>``) using the shared delivery
    secret — no employee session is involved. Only this path may set a
    propagation to ``synced``; a wrong, stale, or forged ack is denied.
    """
    body = await request.body()
    if len(body) > _ACK_BODY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="ack body exceeds the bounded size limit",
        )
    raw_delivery_id = request.headers.get("X-Cygnus-Delivery-Id")
    if not raw_delivery_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Cygnus-Delivery-Id header is required",
        )
    try:
        delivery_id = uuid.UUID(raw_delivery_id.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Cygnus-Delivery-Id must be a UUID",
        ) from exc
    correlation_id, traceparent = _request_correlation(request)
    secret = get_settings().delivery_hmac_secret
    try:
        return await acknowledge_propagation_delivery(
            db,
            delivery_id=delivery_id,
            ack_body=body,
            signature=request.headers.get("X-Cygnus-Ack-Signature", ""),
            secret=secret,
            correlation_id=correlation_id,
            traceparent=traceparent,
        )
    except DeliveryReceiptNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DeliveryVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except DeliveryAckConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("/api/propagation-deliveries")
async def propagation_deliveries(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Delivery status: pending, in_flight, synced, failed, dead_letter",
    ),
    publication_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=_DELIVERY_QUERY_LIMIT_MAX),
    _current_user: Employee = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Admin reconciliation truth for outbound propagation deliveries.

    Surfaces pending, mismatched (delivery vs propagation state disagreement),
    and dead-lettered deliveries with durable attempt evidence. Never
    fabricates rows: every record is persisted outbox/receipt truth.
    """
    statement = select(GovernancePropagationDelivery)
    if status_filter is not None:
        normalized_status = status_filter.strip()
        if not normalized_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status filter must not be blank",
            )
        statement = statement.where(
            GovernancePropagationDelivery.status == normalized_status
        )
    if publication_id is not None:
        statement = statement.where(
            GovernancePropagationDelivery.publication_id == publication_id
        )
    statement = statement.order_by(
        GovernancePropagationDelivery.created_at.desc(),
        GovernancePropagationDelivery.id.desc(),
    ).limit(limit)
    rows = tuple((await db.execute(statement)).scalars().all())

    propagation_ids = tuple(row.propagation_id for row in rows)
    propagation_status_by_id: dict[uuid.UUID, str | None] = {}
    if propagation_ids:
        propagation_rows = tuple(
            (
                await db.execute(
                    select(GovernancePropagation).where(
                        GovernancePropagation.id.in_(propagation_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        propagation_status_by_id = {row.id: row.status for row in propagation_rows}

    records: list[dict[str, object]] = []
    for row in rows:
        payload = delivery_to_dict(row, include_payload=True)
        propagation_status = propagation_status_by_id.get(row.propagation_id)
        payload["propagation_status"] = propagation_status
        payload["mismatch"] = (
            (row.status == DeliveryStatus.SYNCED.value)
            != (propagation_status == PropagationStatus.SYNCED.value)
            if propagation_status is not None
            else None
        )
        records.append(payload)

    summary: dict[str, int] = {}
    for row in rows:
        summary[row.status] = summary.get(row.status, 0) + 1
    return {
        "persisted": True,
        "rehearsal": False,
        "summary": summary,
        "records": records,
        "total": len(rows),
        "limit": limit,
        "filters": {
            "status": status_filter,
            "publication_id": (
                str(publication_id) if publication_id is not None else None
            ),
        },
    }


def _request_correlation(request: Request) -> tuple[str | None, str | None]:
    """Bounded correlation metadata from request headers (never in digests)."""
    correlation_id = request.headers.get("X-Cygnus-Correlation-Id")
    traceparent = request.headers.get("traceparent")
    if correlation_id is not None:
        correlation_id = correlation_id.strip()[:_BOUNDED_CORRELATION_CHARS] or None
    if traceparent is not None:
        traceparent = traceparent.strip()[:_BOUNDED_CORRELATION_CHARS] or None
    return correlation_id, traceparent


_BOUNDED_CORRELATION_CHARS = 200
