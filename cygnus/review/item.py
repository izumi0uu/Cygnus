from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from cygnus.domain.audience import AudienceFilter
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import FreshnessState, SupportEvidence
from cygnus.review.briefing import OwnerState, ReviewRiskItem, ReviewRiskType
from cygnus.substrate.compilation_plan import EvidenceSufficiency, UrgencyLevel



def _normalize(values: Iterable[str] | None, *, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    out: list[str] = []
    for raw in values:
        value = raw.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        out.append(value)
    return tuple(out)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceStrength:
    sufficiency: EvidenceSufficiency
    freshness_mix: tuple[str, ...]
    source_refs: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "freshness_mix", _normalize(self.freshness_mix, label="freshness mix"))
        object.__setattr__(self, "source_refs", _normalize(self.source_refs, label="source ref"))
        object.__setattr__(self, "evidence_ids", _normalize(self.evidence_ids, label="evidence id"))
        if not self.source_refs:
            raise ValueError("source_refs must not be empty")
        if not self.evidence_ids:
            raise ValueError("evidence_ids must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "sufficiency": self.sufficiency.value,
            "freshness_mix": list(self.freshness_mix),
            "source_refs": list(self.source_refs),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceImpact:
    affected_audiences: tuple[AudienceFilter, ...]
    audience_labels: tuple[str, ...]
    impacted_surfaces: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "affected_audiences", tuple(self.affected_audiences))
        object.__setattr__(self, "audience_labels", _normalize(self.audience_labels, label="audience label"))
        object.__setattr__(self, "impacted_surfaces", _normalize(self.impacted_surfaces, label="impacted surface"))
        if not self.affected_audiences:
            raise ValueError("affected_audiences must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "affected_audiences": [audience.to_dict() for audience in self.affected_audiences],
            "audience_labels": list(self.audience_labels),
            "impacted_surfaces": list(self.impacted_surfaces),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskFrame:
    risk_type: ReviewRiskType
    urgency: UrgencyLevel
    system_tension: str
    why_now_summary: str
    command_origin_tag: str
    owner_state: OwnerState
    queue_owner: str | None

    def __post_init__(self) -> None:
        if not self.system_tension.strip():
            raise ValueError("system_tension must not be blank")
        if not self.why_now_summary.strip():
            raise ValueError("why_now_summary must not be blank")
        if not self.command_origin_tag.strip():
            raise ValueError("command_origin_tag must not be blank")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_type": self.risk_type.value,
            "urgency": self.urgency.value,
            "system_tension": self.system_tension,
            "why_now_summary": self.why_now_summary,
            "command_origin_tag": self.command_origin_tag,
            "owner_state": self.owner_state.value,
            "queue_owner": self.queue_owner,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewItemDetailSurface:
    detail_id: str
    item_ref: str
    title: str
    object_type: KnowledgeObjectType
    risk_frame: RiskFrame
    evidence_strength: EvidenceStrength
    audience_impact: AudienceImpact
    command_actions: tuple[str, ...] = field(default_factory=tuple)
    context_notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.detail_id.strip():
            raise ValueError("detail_id must not be blank")
        if not self.item_ref.strip():
            raise ValueError("item_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        object.__setattr__(self, "command_actions", _normalize(self.command_actions, label="command action"))
        object.__setattr__(self, "context_notes", _normalize(self.context_notes, label="context note"))
        if not self.command_actions:
            raise ValueError("command_actions must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "detail_id": self.detail_id,
            "item_ref": self.item_ref,
            "title": self.title,
            "object_type": self.object_type.value,
            "risk_frame": self.risk_frame.to_dict(),
            "evidence_strength": self.evidence_strength.to_dict(),
            "audience_impact": self.audience_impact.to_dict(),
            "command_actions": list(self.command_actions),
            "context_notes": list(self.context_notes),
        }


def build_review_item_detail_surface(
    *,
    item: ReviewRiskItem,
    evidence: tuple[SupportEvidence, ...],
    evidence_sufficiency: EvidenceSufficiency,
) -> ReviewItemDetailSurface:
    return ReviewItemDetailSurface(
        detail_id=f"detail:{item.object_ref}",
        item_ref=item.object_ref,
        title=item.title,
        object_type=item.object_type,
        risk_frame=RiskFrame(
            risk_type=item.risk_type,
            urgency=item.urgency,
            system_tension=_system_tension(item.risk_type),
            why_now_summary=item.why_now.summary,
            command_origin_tag=_command_origin_tag(item),
            owner_state=item.owner_state,
            queue_owner=item.queue_owner,
        ),
        evidence_strength=EvidenceStrength(
            sufficiency=evidence_sufficiency,
            freshness_mix=_freshness_mix(evidence),
            source_refs=tuple(record.source_ref for record in evidence),
            evidence_ids=tuple(record.evidence_id for record in evidence),
        ),
        audience_impact=AudienceImpact(
            affected_audiences=item.affected_audiences,
            audience_labels=tuple(_audience_label(audience) for audience in item.affected_audiences),
            impacted_surfaces=item.why_now.affected_surfaces,
        ),
        command_actions=item.recommended_actions,
        context_notes=_context_notes(item=item, evidence=evidence, evidence_sufficiency=evidence_sufficiency),
    )


def _system_tension(risk_type: ReviewRiskType) -> str:
    mapping = {
        ReviewRiskType.SOURCE_BLINDNESS: "Governance blindness",
        ReviewRiskType.DRIFT: "Freshness drift",
        ReviewRiskType.AUDIENCE_MISMATCH: "Audience boundary conflict",
        ReviewRiskType.TICKET_PRESSURE: "Frontline pressure accumulation",
        ReviewRiskType.POLICY_CONFLICT: "Policy interpretation conflict",
        ReviewRiskType.OWNER_GAP: "Ownership gap",
    }
    return mapping[risk_type]


def _command_origin_tag(item: ReviewRiskItem) -> str:
    return f"{item.risk_type.value}:{item.urgency.value}"


def _freshness_mix(evidence: tuple[SupportEvidence, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for state in (FreshnessState.STALE, FreshnessState.UNKNOWN, FreshnessState.FRESH):
        count = sum(1 for record in evidence if record.freshness_state is state)
        if count:
            ordered.append(f"{state.value}:{count}")
    return tuple(ordered) or ("unknown:0",)


def _audience_label(audience: AudienceFilter) -> str:
    parts = [audience.visibility.value]
    for values in (
        audience.brands,
        audience.product_lines,
        audience.plans,
        audience.regions,
        audience.languages,
        audience.product_versions,
    ):
        if values:
            parts.append("/".join(values))
    if len(parts) == 1:
        parts.append("global")
    return " · ".join(parts)


def _context_notes(
    *,
    item: ReviewRiskItem,
    evidence: tuple[SupportEvidence, ...],
    evidence_sufficiency: EvidenceSufficiency,
) -> tuple[str, ...]:
    notes: list[str] = [
        f"This item is being prioritized as {item.risk_type.value} rather than a generic content edit.",
        f"Evidence sufficiency is currently {evidence_sufficiency.value}.",
    ]
    if any(record.freshness_state is FreshnessState.STALE for record in evidence):
        notes.append("At least one backing source is stale, increasing downstream answer contamination risk.")
    if item.owner_state is OwnerState.UNASSIGNED:
        notes.append("No stable queue owner is assigned yet, so this governance package may stall without intervention.")
    return tuple(notes)
