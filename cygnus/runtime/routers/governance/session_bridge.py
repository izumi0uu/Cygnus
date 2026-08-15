from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain import AudienceContext, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import FreshnessState
from cygnus.integrations.governed_feedback_tools import GovernedFeedbackTools
from cygnus.integrations.session_bridge import (
    GovernanceDisposition,
    GovernedQueryRequest,
    GovernedSessionBridge,
    PriorGovernanceContext,
    session_bridge_capabilities,
    session_bridge_openapi_projection,
)
from cygnus.retrieval import SubstrateKnowledgeSnapshot
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.routers.governance.dependencies import (
    get_governance_knowledge_snapshot,
)
from cygnus.runtime.services.auth_service import get_current_user
from cygnus.runtime.services.permission_engine import get_effective_permissions
from cygnus.substrate.agent_protocol import (
    SESSION_CONTRACT_VERSION_HEADER,
    SessionActorScope,
    SessionContractVersionError,
    negotiate_session_contract_version,
    session_contract_error_envelope,
)
from cygnus.substrate.tool_runtime import (
    execute_governed_tool_call,
    session_tool_manifest,
)


router = APIRouter()


def _negotiate_contract_version(
    contract_version: str | None = Header(
        default=None, alias=SESSION_CONTRACT_VERSION_HEADER
    ),
) -> str:
    """Require the client contract major; incompatible versions fail before work."""
    try:
        return negotiate_session_contract_version(contract_version)
    except SessionContractVersionError as exc:
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if exc.code == "missing_contract_version"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail=session_contract_error_envelope(exc),
        ) from exc


def _actor_scope(current_user: Employee) -> SessionActorScope:
    """Truthful permission view for one authenticated employee."""
    return SessionActorScope(
        authenticated=True,
        is_admin=current_user.role == "admin",
        permissions=frozenset(get_effective_permissions(current_user)),
    )


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
    channel: str = Field(min_length=1, max_length=120)
    audience_context: SessionAudienceContextRequest
    object_types: list[KnowledgeObjectType] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=10)
    previous_governance_context: PriorGovernanceContextRequest | None = None

    def to_domain(self) -> GovernedQueryRequest:
        return GovernedQueryRequest(
            request_ref=self.request_ref,
            session_ref=self.session_ref,
            query=self.query,
            channel=self.channel,
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
    current_user: Employee = Depends(get_current_user),
    _contract_version: str = Depends(_negotiate_contract_version),
) -> dict[str, object]:
    return session_bridge_capabilities(snapshot, actor=_actor_scope(current_user))


@router.get("/api/session-bridge/manifest")
async def get_session_bridge_manifest(
    current_user: Employee = Depends(get_current_user),
    _contract_version: str = Depends(_negotiate_contract_version),
) -> dict[str, object]:
    """OpenAPI session-contract projection derived from the canonical manifest."""
    return session_bridge_openapi_projection()


@router.post("/api/session-bridge/query")
async def handoff_support_query(
    body: SessionQueryRequest,
    snapshot: SubstrateKnowledgeSnapshot = Depends(get_governance_knowledge_snapshot),
    _contract_version: str = Depends(_negotiate_contract_version),
) -> dict[str, object]:
    try:
        return GovernedSessionBridge(snapshot).query(body.to_domain())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


_FEEDBACK_SIGNAL_TYPES = Literal[
    "answer_accepted",
    "human_rewrite",
    "escalated",
    "low_rating",
    "unsupported_answer",
    "stale_answer",
]
_UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class FeedbackAudienceContextRequest(BaseModel):
    visibility: Literal["internal", "external"]
    brand: str | None = Field(default=None, min_length=1, max_length=200)
    product_line: str | None = Field(default=None, min_length=1, max_length=200)
    plan_tier: str | None = Field(default=None, min_length=1, max_length=200)
    region: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=1, max_length=200)
    product_version: str | None = Field(default=None, min_length=1, max_length=200)


class FeedbackSignalRequest(BaseModel):
    """Mirrors the canonical ``record_feedback_signal`` manifest input schema."""

    command_id: str = Field(min_length=1, max_length=220)
    signal_type: _FEEDBACK_SIGNAL_TYPES
    audience_context: FeedbackAudienceContextRequest
    object_id: str | None = Field(default=None, min_length=1, max_length=320)
    draft_id: str | None = Field(default=None, pattern=_UUID_PATTERN)
    notes: str | None = Field(default=None, min_length=1, max_length=10_000)
    source_context_ref: str | None = Field(default=None, min_length=1, max_length=500)


@router.post("/api/session-bridge/feedback")
async def record_feedback_signal(
    body: FeedbackSignalRequest,
    current_user: Annotated[Employee, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    contract_version: str = Depends(_negotiate_contract_version),
) -> dict[str, object]:
    """Authenticated REST bridge for the governed feedback tool (CYG-141).

    Uses the same canonical manifest schema, the actor-bound
    command_id/fingerprint service transaction, and the shared structured
    result envelope as the MCP and session surfaces — the business logic lives
    once in ``GovernedFeedbackTools`` and is never duplicated here.
    """
    tool = session_tool_manifest().tool("record_feedback_signal")

    async def _execute(**arguments: Any) -> dict[str, Any]:
        tools = GovernedFeedbackTools(db, actor=current_user)
        payload = await tools.record_feedback_signal(**arguments)
        if (
            payload.get("status") == "success"
            and payload.get("persisted") is True
            and payload.get("replayed") is not True
        ):
            await db.commit()
        return payload

    return await execute_governed_tool_call(
        tool=tool,
        arguments=body.model_dump(exclude_none=True),
        handler=_execute,
        actor_scope=_actor_scope(current_user),
        contract_version=contract_version,
    )
