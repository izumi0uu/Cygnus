from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType, FreshnessState
from cygnus.governance.ledger import lock_governance_command
from cygnus.review.intake import (
    PressureIntakeRecord,
    PressureSignalType,
    compile_pressure_proposal_bundles,
)
from cygnus.review.service import ProposalBundle
from cygnus.runtime.database.models import (
    Employee,
    GovernanceSignal,
    Source,
    WikiPage,
)
from cygnus.runtime.services.permission_engine import (
    build_document_scope_clause,
    build_wiki_scope_clause,
)
from cygnus.substrate.compilation_plan import PlanAction


class GovernanceSignalStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class GovernanceSignalConflict(ValueError):
    """A signal reference was reused for a different durable fact."""


_DEFAULT_EVIDENCE_TYPE = {
    PressureSignalType.TICKET_CLUSTER: EvidenceSourceType.RESOLVED_TICKET,
    PressureSignalType.HUMAN_REWRITE: EvidenceSourceType.CHAT_TRANSCRIPT,
    PressureSignalType.RELEASE_DELTA: EvidenceSourceType.RELEASE_NOTE,
    PressureSignalType.INCIDENT_DELTA: EvidenceSourceType.INCIDENT_UPDATE,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceSignalInput:
    signal_ref: str
    signal_type: PressureSignalType
    object_ref: str
    title: str
    object_type: KnowledgeObjectType
    audience_filter: AudienceFilter | None
    affected_surfaces: tuple[str, ...]
    summary: str
    reason: str
    evidence_excerpt: str
    freshness: FreshnessState = FreshnessState.UNKNOWN
    page_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    audience_binding_ref: str | None = None
    trigger_signals: tuple[str, ...] = field(default_factory=tuple)
    evidence_source_type: EvidenceSourceType | None = None
    queue_owner: str | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        for label, raw_value in (
            ("signal_ref", self.signal_ref),
            ("object_ref", self.object_ref),
            ("title", self.title),
            ("summary", self.summary),
            ("reason", self.reason),
            ("evidence_excerpt", self.evidence_excerpt),
        ):
            if not raw_value.strip():
                raise ValueError(f"{label} must not be blank")
        if self.audience_filter is None and self.audience_binding_ref is None:
            raise ValueError(
                "audience_filter or audience_binding_ref must be provided"
            )
        if self.audience_binding_ref is not None and not self.audience_binding_ref.strip():
            raise ValueError("audience_binding_ref must not be blank when provided")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        if (
            self.audience_filter is None
            and self.audience_binding_ref is not None
            and self.page_id is None
        ):
            raise ValueError(
                "page_id is required when audience_binding_ref supplies the audience"
            )
        if not self.affected_surfaces:
            raise ValueError("affected_surfaces must not be empty")
        object.__setattr__(
            self,
            "affected_surfaces",
            _normalize_strings(self.affected_surfaces, label="affected surface"),
        )
        object.__setattr__(
            self,
            "trigger_signals",
            _normalize_strings(self.trigger_signals, label="trigger signal"),
        )
        evidence_type = self.evidence_source_type or _DEFAULT_EVIDENCE_TYPE.get(
            self.signal_type
        )
        if evidence_type is None:
            raise ValueError(
                "evidence_source_type is required for source_failure signals"
            )
        object.__setattr__(self, "evidence_source_type", evidence_type)
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")


async def create_governance_signal(
    session: AsyncSession,
    signal_input: GovernanceSignalInput,
    *,
    created_by_id: uuid.UUID,
) -> GovernanceSignal:
    """Persist a signal once, returning an exact idempotent replay."""
    await lock_governance_command(
        session, f"governance-signal:{signal_input.signal_ref}"
    )
    existing = await get_governance_signal(session, signal_input.signal_ref)
    if existing is not None:
        if not _matches_input(existing, signal_input):
            raise GovernanceSignalConflict(
                f"signal_ref={signal_input.signal_ref} is already bound to a different signal"
            )
        return existing
    evidence_source_type = signal_input.evidence_source_type
    if evidence_source_type is None:
        raise AssertionError("validated signal input is missing evidence_source_type")

    signal = GovernanceSignal(
        signal_ref=signal_input.signal_ref.strip(),
        signal_type=signal_input.signal_type.value,
        object_ref=signal_input.object_ref.strip(),
        title=signal_input.title.strip(),
        object_type=signal_input.object_type.value,
        page_id=signal_input.page_id,
        source_id=signal_input.source_id,
        audience_binding_ref=(
            signal_input.audience_binding_ref.strip()
            if signal_input.audience_binding_ref is not None
            else None
        ),
        audience_filter=(
            _audience_filter_payload(signal_input.audience_filter)
            if signal_input.audience_filter is not None
            else None
        ),
        affected_surfaces=list(signal_input.affected_surfaces),
        trigger_signals=list(signal_input.trigger_signals),
        evidence_source_type=evidence_source_type.value,
        freshness=signal_input.freshness.value,
        summary=signal_input.summary.strip(),
        reason=signal_input.reason.strip(),
        evidence_excerpt=signal_input.evidence_excerpt.strip(),
        queue_owner=(
            signal_input.queue_owner.strip()
            if signal_input.queue_owner is not None
            else None
        ),
        status=GovernanceSignalStatus.ACTIVE.value,
        created_by_id=created_by_id,
    )
    if signal_input.observed_at is not None:
        signal.observed_at = signal_input.observed_at
    session.add(signal)
    await session.flush()
    return signal


async def get_governance_signal(
    session: AsyncSession,
    signal_ref: str,
) -> GovernanceSignal | None:
    normalized_ref = signal_ref.strip()
    if not normalized_ref:
        raise ValueError("signal_ref must not be blank")
    return (
        await session.execute(
            select(GovernanceSignal).where(
                GovernanceSignal.signal_ref == normalized_ref
            )
        )
    ).scalar_one_or_none()


async def list_governance_signals(
    session: AsyncSession,
    *,
    current_user: Employee,
    status: GovernanceSignalStatus | None = GovernanceSignalStatus.ACTIVE,
    signal_types: Iterable[PressureSignalType] | None = None,
) -> tuple[GovernanceSignal, ...]:
    """List signals after applying Wiki/Source visibility inside SQL."""
    statement = select(GovernanceSignal)
    if status is not None:
        statement = statement.where(GovernanceSignal.status == status.value)
    if signal_types is not None:
        values = tuple(signal_type.value for signal_type in signal_types)
        if not values:
            return ()
        statement = statement.where(GovernanceSignal.signal_type.in_(values))

    scope_clause = _governance_signal_scope_clause(current_user)
    if scope_clause is not None:
        statement = statement.where(scope_clause)
    rows = (
        (
            await session.execute(
                statement.order_by(
                    GovernanceSignal.observed_at.desc(),
                    GovernanceSignal.signal_ref,
                )
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def resolve_governance_signal(
    session: AsyncSession,
    signal_ref: str,
    *,
    resolved_at: datetime | None = None,
) -> GovernanceSignal | None:
    """Resolve an active signal; exact retries preserve its first resolution."""
    normalized_ref = signal_ref.strip()
    if not normalized_ref:
        raise ValueError("signal_ref must not be blank")
    await lock_governance_command(session, f"governance-signal:{normalized_ref}")
    signal = (
        await session.execute(
            select(GovernanceSignal)
            .where(GovernanceSignal.signal_ref == normalized_ref)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if signal is None:
        return None
    if signal.status == GovernanceSignalStatus.RESOLVED.value:
        return signal
    if signal.status != GovernanceSignalStatus.ACTIVE.value:
        raise GovernanceSignalConflict(
            f"signal_ref={normalized_ref} cannot resolve from status={signal.status}"
        )
    resolved = resolved_at or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        raise ValueError("resolved_at must include a timezone")
    signal.status = GovernanceSignalStatus.RESOLVED.value
    signal.resolved_at = resolved
    signal.version += 1
    await session.flush()
    return signal


def compile_review_signal_bundles(
    signals: Iterable[GovernanceSignal],
) -> tuple[ProposalBundle, ...]:
    """Compile ticket, rewrite, and qualified source-failure facts."""
    records = (
        governance_signal_to_pressure_record(signal)
        for signal in signals
        if signal.signal_type
        in {
            PressureSignalType.TICKET_CLUSTER.value,
            PressureSignalType.HUMAN_REWRITE.value,
            PressureSignalType.SOURCE_FAILURE.value,
        }
    )
    return compile_pressure_proposal_bundles(records)


def governance_signal_to_pressure_record(
    signal: GovernanceSignal,
    audience_filter: AudienceFilter | None = None,
) -> PressureIntakeRecord:
    resolved_audience = audience_filter
    if resolved_audience is None and signal.audience_filter is not None:
        resolved_audience = _audience_filter_from_payload(signal.audience_filter)
    if resolved_audience is None:
        raise ValueError(
            f"signal_ref={signal.signal_ref} requires its audience binding to be resolved before compilation"
        )
    signal_type = PressureSignalType(signal.signal_type)
    source_ref = (
        f"source:{signal.source_id}"
        if signal.source_id is not None
        else f"governance-signal:{signal.signal_ref}"
    )
    return PressureIntakeRecord(
        signal_type=signal_type,
        signal_ref=signal.signal_ref,
        title=signal.title,
        summary=signal.summary,
        source_ref=source_ref,
        source_type=EvidenceSourceType(signal.evidence_source_type),
        audience_filter=resolved_audience,
        object_type=KnowledgeObjectType(signal.object_type),
        affected_surfaces=tuple(signal.affected_surfaces),
        trigger_signals=tuple(signal.trigger_signals),
        freshness_state=FreshnessState(signal.freshness),
        queue_owner=signal.queue_owner,
        reason=signal.reason,
        evidence_excerpt=signal.evidence_excerpt,
        proposal_id=signal.object_ref,
        proposal_action=(
            PlanAction.UPDATE if signal.page_id is not None else PlanAction.CREATE
        ),
    )


def governance_signal_to_dict(signal: GovernanceSignal) -> dict[str, object]:
    return {
        "id": str(signal.id),
        "signal_ref": signal.signal_ref,
        "signal_type": signal.signal_type,
        "object_ref": signal.object_ref,
        "title": signal.title,
        "object_type": signal.object_type,
        "page_id": str(signal.page_id) if signal.page_id is not None else None,
        "source_id": str(signal.source_id) if signal.source_id is not None else None,
        "audience_binding_ref": signal.audience_binding_ref,
        "audience_filter": signal.audience_filter,
        "affected_surfaces": list(signal.affected_surfaces),
        "trigger_signals": list(signal.trigger_signals),
        "evidence_source_type": signal.evidence_source_type,
        "freshness": signal.freshness,
        "summary": signal.summary,
        "reason": signal.reason,
        "evidence_excerpt": signal.evidence_excerpt,
        "queue_owner": signal.queue_owner,
        "status": signal.status,
        "observed_at": signal.observed_at.isoformat(),
        "resolved_at": (
            signal.resolved_at.isoformat() if signal.resolved_at is not None else None
        ),
        "created_by": str(signal.created_by_id),
        "created_at": signal.created_at.isoformat(),
        "updated_at": signal.updated_at.isoformat(),
        "version": signal.version,
    }


def _governance_signal_scope_clause(current_user: Employee):
    if current_user.role == "admin":
        return None

    page_scope = build_wiki_scope_clause(current_user)
    source_scope = build_document_scope_clause(current_user)
    page_visibility = exists(
        select(WikiPage.id).where(
            WikiPage.id == GovernanceSignal.page_id,
            *(() if page_scope is None else (page_scope,)),
        )
    )
    source_visibility = exists(
        select(Source.id).where(
            Source.id == GovernanceSignal.source_id,
            *(() if source_scope is None else (source_scope,)),
        )
    )
    return or_(
        and_(GovernanceSignal.page_id.is_not(None), page_visibility),
        and_(
            GovernanceSignal.page_id.is_(None),
            GovernanceSignal.source_id.is_not(None),
            source_visibility,
        ),
    )


def _matches_input(
    signal: GovernanceSignal,
    signal_input: GovernanceSignalInput,
) -> bool:
    expected_audience = (
        _audience_filter_payload(signal_input.audience_filter)
        if signal_input.audience_filter is not None
        else None
    )
    evidence_source_type = signal_input.evidence_source_type
    if evidence_source_type is None:
        raise AssertionError("validated signal input is missing evidence_source_type")
    identity_matches = (
        signal.signal_type == signal_input.signal_type.value
        and signal.object_ref == signal_input.object_ref.strip()
        and signal.title == signal_input.title.strip()
        and signal.object_type == signal_input.object_type.value
        and signal.page_id == signal_input.page_id
        and signal.source_id == signal_input.source_id
        and signal.audience_binding_ref
        == (
            signal_input.audience_binding_ref.strip()
            if signal_input.audience_binding_ref is not None
            else None
        )
        and signal.audience_filter == expected_audience
        and tuple(signal.affected_surfaces) == signal_input.affected_surfaces
        and tuple(signal.trigger_signals) == signal_input.trigger_signals
        and signal.evidence_source_type == evidence_source_type.value
        and signal.freshness == signal_input.freshness.value
        and signal.summary == signal_input.summary.strip()
        and signal.reason == signal_input.reason.strip()
        and signal.evidence_excerpt == signal_input.evidence_excerpt.strip()
        and signal.queue_owner
        == (
            signal_input.queue_owner.strip()
            if signal_input.queue_owner is not None
            else None
        )
    )
    return identity_matches and (
        signal_input.observed_at is None
        or signal.observed_at == signal_input.observed_at
    )


def _normalize_strings(
    values: Iterable[str],
    *,
    label: str,
) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _audience_filter_payload(
    audience_filter: AudienceFilter,
) -> dict[str, object]:
    return {
        "visibility": audience_filter.visibility.value,
        "brands": list(audience_filter.brands),
        "product_lines": list(audience_filter.product_lines),
        "plans": list(audience_filter.plans),
        "regions": list(audience_filter.regions),
        "languages": list(audience_filter.languages),
        "product_versions": list(audience_filter.product_versions),
    }


def _audience_filter_from_payload(payload: dict[str, object]) -> AudienceFilter:
    visibility = payload.get("visibility")
    if not isinstance(visibility, str):
        raise ValueError("audience_filter.visibility must be a string")
    dimensions: dict[str, tuple[str, ...]] = {}
    for field_name in (
        "brands",
        "product_lines",
        "plans",
        "regions",
        "languages",
        "product_versions",
    ):
        raw_values = payload.get(field_name, [])
        if not isinstance(raw_values, list) or not all(
            isinstance(item, str) for item in raw_values
        ):
            raise ValueError(f"audience_filter.{field_name} must be a string list")
        dimensions[field_name] = tuple(raw_values)
    return AudienceFilter(
        visibility=Visibility(visibility),
        brands=dimensions["brands"],
        product_lines=dimensions["product_lines"],
        plans=dimensions["plans"],
        regions=dimensions["regions"],
        languages=dimensions["languages"],
        product_versions=dimensions["product_versions"],
    )
