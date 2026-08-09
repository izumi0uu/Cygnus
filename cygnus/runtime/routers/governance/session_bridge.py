from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from cygnus.domain import AudienceContext, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import FreshnessState
from cygnus.integrations.session_bridge import (
    GovernanceDisposition,
    GovernedQueryRequest,
    GovernedSessionBridge,
    PriorGovernanceContext,
    session_bridge_capabilities,
)
from cygnus.retrieval import SubstrateKnowledgeSnapshot
from cygnus.runtime.routers.governance.dependencies import (
    get_governance_knowledge_snapshot,
)


router = APIRouter()


class SessionAudienceContextRequest(BaseModel):
    visibility: Visibility
    brand: str | None = None
    product_line: str | None = None
    plan_tier: str | None = None
    region: str | None = None
    language: str | None = None
    product_version: str | None = None

    def to_domain(self) -> AudienceContext:
        return AudienceContext(
            visibility=self.visibility,
            brand=self.brand,
            product_line=self.product_line,
            plan=self.plan_tier,
            region=self.region,
            language=self.language,
            product_version=self.product_version,
        )


class PriorGovernanceContextRequest(BaseModel):
    governance_state: GovernanceDisposition
    audience_context: SessionAudienceContextRequest
    object_id: str | None = None
    object_version: int | None = None
    trace_ref: str | None = None
    freshness: FreshnessState | None = None

    def to_domain(self) -> PriorGovernanceContext:
        return PriorGovernanceContext(
            governance_state=self.governance_state,
            audience_context=self.audience_context.to_domain(),
            object_id=self.object_id,
            object_version=self.object_version,
            trace_ref=self.trace_ref,
            freshness=self.freshness,
        )


class SessionQueryRequest(BaseModel):
    request_ref: str = Field(min_length=1, max_length=200)
    session_ref: str | None = Field(default=None, min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=4000)
    audience_context: SessionAudienceContextRequest
    object_types: list[KnowledgeObjectType] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=10)
    previous_governance_context: PriorGovernanceContextRequest | None = None

    def to_domain(self) -> GovernedQueryRequest:
        return GovernedQueryRequest(
            request_ref=self.request_ref,
            session_ref=self.session_ref,
            query=self.query,
            audience_context=self.audience_context.to_domain(),
            object_types=tuple(object_type.value for object_type in self.object_types),
            limit=self.limit,
            previous_governance_context=(
                self.previous_governance_context.to_domain()
                if self.previous_governance_context is not None
                else None
            ),
        )


@router.get("/api/session-bridge/capabilities")
async def get_session_bridge_capabilities(
    snapshot: SubstrateKnowledgeSnapshot = Depends(get_governance_knowledge_snapshot),
) -> dict[str, object]:
    return session_bridge_capabilities(snapshot)


@router.post("/api/session-bridge/query")
async def handoff_support_query(
    body: SessionQueryRequest,
    snapshot: SubstrateKnowledgeSnapshot = Depends(get_governance_knowledge_snapshot),
) -> dict[str, object]:
    try:
        return GovernedSessionBridge(snapshot).query(body.to_domain())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
