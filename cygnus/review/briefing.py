from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.substrate.compilation_plan import CompilationProposal, UrgencyLevel


class ReviewRiskType(str, Enum):
    AUDIENCE_MISMATCH = "audience_mismatch"
    DRIFT = "drift"
    SOURCE_BLINDNESS = "source_blindness"
    TICKET_PRESSURE = "ticket_pressure"
    POLICY_CONFLICT = "policy_conflict"
    OWNER_GAP = "owner_gap"


class OwnerState(str, Enum):
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    ESCALATED = "escalated"



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
class WhyNowFrame:
    summary: str
    trigger_signals: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    affected_surfaces: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        object.__setattr__(self, "trigger_signals", _normalize(self.trigger_signals, label="trigger signal"))
        object.__setattr__(self, "evidence_ids", _normalize(self.evidence_ids, label="evidence id"))
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "trigger_signals": list(self.trigger_signals),
            "evidence_ids": list(self.evidence_ids),
            "affected_surfaces": list(self.affected_surfaces),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewRiskItem:
    risk_id: str
    title: str
    risk_type: ReviewRiskType
    object_type: KnowledgeObjectType
    object_ref: str
    affected_audiences: tuple[AudienceFilter, ...]
    owner_state: OwnerState
    urgency: UrgencyLevel
    why_now: WhyNowFrame
    recommended_actions: tuple[str, ...] = field(default_factory=tuple)
    queue_owner: str | None = None

    def __post_init__(self) -> None:
        if not self.risk_id.strip():
            raise ValueError("risk_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.object_ref.strip():
            raise ValueError("object_ref must not be blank")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        object.__setattr__(self, "affected_audiences", tuple(self.affected_audiences))
        object.__setattr__(self, "recommended_actions", _normalize(self.recommended_actions, label="recommended action"))
        if not self.affected_audiences:
            raise ValueError("review risk item must include at least one affected audience")

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_id": self.risk_id,
            "title": self.title,
            "risk_type": self.risk_type.value,
            "object_type": self.object_type.value,
            "object_ref": self.object_ref,
            "affected_audiences": [audience.to_dict() for audience in self.affected_audiences],
            "owner_state": self.owner_state.value,
            "urgency": self.urgency.value,
            "why_now": self.why_now.to_dict(),
            "recommended_actions": list(self.recommended_actions),
            "queue_owner": self.queue_owner,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewCommandBrief:
    brief_id: str
    headline: str
    priority_items: tuple[ReviewRiskItem, ...]
    summary_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.brief_id.strip():
            raise ValueError("brief_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        object.__setattr__(self, "priority_items", tuple(self.priority_items))
        if not self.priority_items:
            raise ValueError("command brief must contain at least one priority item")

    def to_dict(self) -> dict[str, object]:
        return {
            "brief_id": self.brief_id,
            "headline": self.headline,
            "priority_items": [item.to_dict() for item in self.priority_items],
            "summary_counts": dict(self.summary_counts),
        }



def risk_item_from_proposal(
    proposal: CompilationProposal,
    *,
    risk_id: str,
    risk_type: ReviewRiskType,
    affected_audiences: tuple[AudienceFilter, ...],
    owner_state: OwnerState,
    affected_surfaces: tuple[str, ...],
    trigger_signals: tuple[str, ...],
    queue_owner: str | None = None,
    recommended_actions: tuple[str, ...] = ("open_review", "assign_owner"),
) -> ReviewRiskItem:
    return ReviewRiskItem(
        risk_id=risk_id,
        title=proposal.title,
        risk_type=risk_type,
        object_type=proposal.object_type,
        object_ref=proposal.proposal_id,
        affected_audiences=affected_audiences,
        owner_state=owner_state,
        urgency=proposal.urgency,
        why_now=WhyNowFrame(
            summary=proposal.why_now,
            trigger_signals=trigger_signals,
            evidence_ids=proposal.evidence_ids,
            affected_surfaces=affected_surfaces,
        ),
        recommended_actions=recommended_actions,
        queue_owner=queue_owner or proposal.review_owner,
    )
