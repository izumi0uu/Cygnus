from __future__ import annotations

from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType, FreshnessState
from cygnus.governance.signals import (
    GovernanceSignalConflict,
    GovernanceEvidenceRef,
    GovernanceSignalInput,
    GovernanceSignalStatus,
    create_governance_signal,
    governance_signal_to_dict,
    list_governance_signals,
    resolve_governance_signal,
)
from cygnus.governance.ticket_draft_promotions import (
    TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH,
    TICKET_DRAFT_PROMOTION_REF_MAX_LENGTH,
    TicketDraftPromotionCommand,
    TicketDraftPromotionConflict,
    promote_ticket_cluster_to_draft,
)
from cygnus.review.intake import (
    PressureSignalType,
    is_feedback_derived_signal_type,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import require_admin


router = APIRouter()


class GovernanceAudienceFilterRequest(BaseModel):
    visibility: Visibility
    brands: list[str] = Field(default_factory=list)
    product_lines: list[str] = Field(default_factory=list)
    plans: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    product_versions: list[str] = Field(default_factory=list)

    def to_domain(self) -> AudienceFilter:
        return AudienceFilter(
            visibility=self.visibility,
            brands=tuple(self.brands),
            product_lines=tuple(self.product_lines),
            plans=tuple(self.plans),
            regions=tuple(self.regions),
            languages=tuple(self.languages),
            product_versions=tuple(self.product_versions),
        )


class GovernanceEvidenceRefRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=320)
    source_ref: str = Field(min_length=1, max_length=1000)
    excerpt: str | None = Field(default=None, min_length=1, max_length=4000)
    observed_at: datetime | None = None

    def to_domain(self) -> GovernanceEvidenceRef:
        return GovernanceEvidenceRef(
            evidence_id=self.evidence_id,
            source_ref=self.source_ref,
            excerpt=self.excerpt,
            observed_at=self.observed_at,
        )


class GovernanceSignalCreateRequest(BaseModel):
    signal_ref: str
    signal_type: PressureSignalType
    object_ref: str
    title: str
    object_type: KnowledgeObjectType
    page_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    audience_binding_ref: str | None = None
    audience_filter: GovernanceAudienceFilterRequest | None = None
    affected_surfaces: list[str] = Field(min_length=1)
    trigger_signals: list[str] = Field(default_factory=list)
    evidence_source_type: EvidenceSourceType | None = None
    freshness: FreshnessState = FreshnessState.UNKNOWN
    summary: str
    reason: str
    evidence_excerpt: str
    observed_at: datetime | None = None
    evidence_refs: list[GovernanceEvidenceRefRequest] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def require_audience(self) -> GovernanceSignalCreateRequest:
        if self.audience_filter is None and self.audience_binding_ref is None:
            raise ValueError("audience_filter or audience_binding_ref must be provided")
        if (
            self.audience_filter is None
            and self.audience_binding_ref is not None
            and self.page_id is None
        ):
            raise ValueError(
                "page_id is required when audience_binding_ref supplies the audience"
            )
        return self

    def to_service_input(self) -> GovernanceSignalInput:
        return GovernanceSignalInput(
            signal_ref=self.signal_ref,
            signal_type=self.signal_type,
            object_ref=self.object_ref,
            title=self.title,
            object_type=self.object_type,
            page_id=self.page_id,
            source_id=self.source_id,
            audience_binding_ref=self.audience_binding_ref,
            audience_filter=(
                self.audience_filter.to_domain()
                if self.audience_filter is not None
                else None
            ),
            affected_surfaces=tuple(self.affected_surfaces),
            trigger_signals=tuple(self.trigger_signals),
            evidence_source_type=self.evidence_source_type,
            freshness=self.freshness,
            summary=self.summary,
            reason=self.reason,
            evidence_excerpt=self.evidence_excerpt,
            observed_at=self.observed_at,
            evidence_refs=tuple(item.to_domain() for item in self.evidence_refs),
        )


class TicketDraftPromotionRequest(BaseModel):
    command_id: str = Field(
        min_length=1,
        max_length=TICKET_DRAFT_PROMOTION_REF_MAX_LENGTH,
    )
    expected_assignment_version: int = Field(ge=1)
    reason: str = Field(
        min_length=1,
        max_length=TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH,
    )

    def to_domain(self) -> TicketDraftPromotionCommand:
        return TicketDraftPromotionCommand(
            command_id=self.command_id,
            expected_assignment_version=self.expected_assignment_version,
            reason=self.reason,
        )


@router.post("/api/governance-signals", status_code=status.HTTP_201_CREATED)
async def write_governance_signal(
    body: GovernanceSignalCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_admin),
) -> dict[str, object]:
    if is_feedback_derived_signal_type(body.signal_type):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{body.signal_type.value} is a worker-owned derived type and "
                "cannot be created through this endpoint"
            ),
        )

    try:
        signal = await create_governance_signal(
            db,
            body.to_service_input(),
            created_by_id=current_user.id,
        )
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
    return governance_signal_to_dict(signal)


@router.get("/api/governance-signals")
async def read_governance_signals(
    signal_status: GovernanceSignalStatus | None = Query(
        GovernanceSignalStatus.ACTIVE,
        alias="status",
    ),
    signal_type: list[PressureSignalType] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_admin),
) -> dict[str, object]:
    signals = await list_governance_signals(
        db,
        current_user=current_user,
        status=signal_status,
        signal_types=signal_type,
    )
    return {
        "signals": [governance_signal_to_dict(signal) for signal in signals],
        "count": len(signals),
        "provider_coverage": {
            "state": "ready",
            "covered_signals": [signal.value for signal in PressureSignalType],
        },
    }


@router.post("/api/governance-signals/{signal_ref}/resolve")
async def resolve_signal(
    signal_ref: str,
    db: AsyncSession = Depends(get_db),
    _current_user: Employee = Depends(require_admin),
) -> dict[str, object]:
    try:
        signal = await resolve_governance_signal(db, signal_ref)
    except GovernanceSignalConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Governance signal not found",
        )
    return governance_signal_to_dict(signal)


@router.post("/api/governance-signals/{signal_ref}/commands/promote-draft")
async def promote_signal_to_draft(
    signal_ref: str,
    body: TicketDraftPromotionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_admin),
) -> dict[str, object]:
    try:
        result = await promote_ticket_cluster_to_draft(
            db,
            signal_ref=signal_ref,
            command=body.to_domain(),
            actor_id=current_user.id,
        )
    except TicketDraftPromotionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Governance signal not found",
        )
    return result.to_dict()
