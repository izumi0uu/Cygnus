from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from cygnus.domain.audience import AudienceFilter
from cygnus.evidence.records import FreshnessState, SupportEvidence
from cygnus.review.briefing import (
    OwnerState,
    ReviewRiskItem,
    ReviewRiskType,
    WhyNowFrame,
    risk_item_from_proposal,
)
from cygnus.review.queries import build_review_command_brief
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    UrgencyLevel,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewSignal:
    proposal_id: str
    risk_type: ReviewRiskType
    affected_audiences: tuple[AudienceFilter, ...]
    affected_surfaces: tuple[str, ...]
    trigger_signals: tuple[str, ...] = field(default_factory=tuple)
    queue_owner: str | None = None
    recommended_actions: tuple[str, ...] = ("open_review", "assign_owner")
    title_override: str | None = None

    def __post_init__(self) -> None:
        if not self.proposal_id.strip():
            raise ValueError("proposal_id must not be blank")
        if not self.affected_audiences:
            raise ValueError("signal must include at least one affected audience")
        if not self.affected_surfaces:
            raise ValueError("signal must include at least one affected surface")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        if self.title_override is not None and not self.title_override.strip():
            raise ValueError("title_override must not be blank when provided")
        object.__setattr__(self, "affected_audiences", tuple(self.affected_audiences))
        object.__setattr__(self, "affected_surfaces", tuple(_normalize(self.affected_surfaces, label="affected surface")))
        object.__setattr__(self, "trigger_signals", tuple(_normalize(self.trigger_signals, label="trigger signal")))
        object.__setattr__(self, "recommended_actions", tuple(_normalize(self.recommended_actions, label="recommended action")))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposalBundle:
    proposal: CompilationProposal
    signal: ReviewSignal
    evidence: tuple[SupportEvidence, ...] = field(default_factory=tuple)
    owner_state: OwnerState | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))


RISK_PRIORITY = {
    ReviewRiskType.SOURCE_BLINDNESS: 0,
    ReviewRiskType.DRIFT: 1,
    ReviewRiskType.AUDIENCE_MISMATCH: 2,
    ReviewRiskType.TICKET_PRESSURE: 3,
    ReviewRiskType.POLICY_CONFLICT: 4,
    ReviewRiskType.OWNER_GAP: 5,
}

URGENCY_PRIORITY = {
    UrgencyLevel.URGENT: 0,
    UrgencyLevel.HIGH: 1,
    UrgencyLevel.MEDIUM: 2,
    UrgencyLevel.LOW: 3,
}

EVIDENCE_PRIORITY = {
    EvidenceSufficiency.INSUFFICIENT: 0,
    EvidenceSufficiency.PARTIAL: 1,
    EvidenceSufficiency.SUFFICIENT: 2,
}


def assemble_review_command_brief(
    *,
    brief_id: str,
    headline: str,
    bundles: Iterable[ProposalBundle],
) -> dict[str, object]:
    items = tuple(build_review_risk_item(bundle) for bundle in bundles)
    brief = build_review_command_brief(brief_id=brief_id, headline=headline, items=items)
    return brief.to_dict()


def build_review_risk_item(bundle: ProposalBundle) -> ReviewRiskItem:
    proposal = bundle.proposal
    signal = bundle.signal
    owner_state = bundle.owner_state or derive_owner_state(proposal=proposal, signal=signal)
    item = risk_item_from_proposal(
        proposal,
        risk_id=_risk_id(signal=signal, proposal=proposal),
        risk_type=signal.risk_type,
        affected_audiences=signal.affected_audiences,
        owner_state=owner_state,
        affected_surfaces=signal.affected_surfaces,
        trigger_signals=_merge_trigger_signals(signal=signal, evidence=bundle.evidence, owner_state=owner_state),
        queue_owner=signal.queue_owner,
        recommended_actions=_merge_recommended_actions(signal=signal, proposal=proposal, owner_state=owner_state, evidence=bundle.evidence),
    )
    why_now = WhyNowFrame(
        summary=_compose_why_now_summary(signal=signal, proposal=proposal, evidence=bundle.evidence, owner_state=owner_state),
        trigger_signals=item.why_now.trigger_signals,
        evidence_ids=item.why_now.evidence_ids,
        affected_surfaces=item.why_now.affected_surfaces,
    )
    title = signal.title_override or item.title
    return ReviewRiskItem(
        risk_id=item.risk_id,
        title=title,
        risk_type=item.risk_type,
        object_type=item.object_type,
        object_ref=item.object_ref,
        affected_audiences=item.affected_audiences,
        owner_state=item.owner_state,
        urgency=item.urgency,
        why_now=why_now,
        recommended_actions=item.recommended_actions,
        queue_owner=item.queue_owner,
    )


def derive_owner_state(*, proposal: CompilationProposal, signal: ReviewSignal) -> OwnerState:
    if signal.queue_owner:
        return OwnerState.ASSIGNED
    if proposal.review_owner.strip():
        return OwnerState.ASSIGNED
    return OwnerState.UNASSIGNED


def rank_review_item(item: ReviewRiskItem) -> tuple[int, int, int, int, str]:
    freshness_penalty = 0
    if "source_sync_failed" in item.why_now.trigger_signals or "stale_evidence" in item.why_now.trigger_signals:
        freshness_penalty = -1
    owner_penalty = 0 if item.owner_state is OwnerState.UNASSIGNED else 1
    return (
        URGENCY_PRIORITY[item.urgency],
        freshness_penalty,
        RISK_PRIORITY[item.risk_type],
        owner_penalty,
        item.title.lower(),
    )


def _compose_why_now_summary(
    *,
    signal: ReviewSignal,
    proposal: CompilationProposal,
    evidence: tuple[SupportEvidence, ...],
    owner_state: OwnerState,
) -> str:
    parts = [proposal.why_now.rstrip("."), _risk_phrase(signal.risk_type)]
    stale_count = sum(1 for record in evidence if record.freshness_state is FreshnessState.STALE)
    unknown_count = sum(1 for record in evidence if record.freshness_state is FreshnessState.UNKNOWN)
    if stale_count:
        parts.append(f"{stale_count} stale evidence source(s) increase answer risk")
    elif unknown_count:
        parts.append(f"{unknown_count} evidence source(s) still have unknown freshness")
    if proposal.evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT:
        parts.append("evidence coverage is insufficient for direct publish")
    elif proposal.evidence_sufficiency is EvidenceSufficiency.PARTIAL:
        parts.append("evidence coverage is only partial")
    if owner_state is OwnerState.UNASSIGNED:
        parts.append("no queue owner is currently assigned")
    return "; ".join(parts) + "."


def _risk_phrase(risk_type: ReviewRiskType) -> str:
    mapping = {
        ReviewRiskType.SOURCE_BLINDNESS: "source coverage is degraded at the exact moment operators need confidence",
        ReviewRiskType.DRIFT: "published guidance is drifting away from current support reality",
        ReviewRiskType.AUDIENCE_MISMATCH: "the current answer path may hit the wrong audience boundary",
        ReviewRiskType.TICKET_PRESSURE: "ticket pressure is signaling a reusable knowledge gap",
        ReviewRiskType.POLICY_CONFLICT: "policy interpretation may now be inconsistent across surfaces",
        ReviewRiskType.OWNER_GAP: "review ownership is unclear for an active knowledge change",
    }
    return mapping[risk_type]


def _merge_trigger_signals(
    *,
    signal: ReviewSignal,
    evidence: tuple[SupportEvidence, ...],
    owner_state: OwnerState,
) -> tuple[str, ...]:
    merged = list(signal.trigger_signals)
    if any(record.freshness_state is FreshnessState.STALE for record in evidence):
        merged.append("stale_evidence")
    if any(record.freshness_state is FreshnessState.UNKNOWN for record in evidence):
        merged.append("unknown_freshness")
    if owner_state is OwnerState.UNASSIGNED:
        merged.append("owner_gap")
    return tuple(_dedupe(merged))


def _merge_recommended_actions(
    *,
    signal: ReviewSignal,
    proposal: CompilationProposal,
    owner_state: OwnerState,
    evidence: tuple[SupportEvidence, ...],
) -> tuple[str, ...]:
    actions = list(signal.recommended_actions)
    if owner_state is OwnerState.UNASSIGNED:
        actions.append("assign_owner")
    if proposal.evidence_sufficiency is not EvidenceSufficiency.SUFFICIENT:
        actions.append("request_more_evidence")
    if any(record.freshness_state is FreshnessState.STALE for record in evidence):
        actions.append("refresh_sources")
    if proposal.urgency is UrgencyLevel.URGENT:
        actions.append("mark_urgent")
    return tuple(_dedupe(actions))


def _risk_id(*, signal: ReviewSignal, proposal: CompilationProposal) -> str:
    return f"{signal.risk_type.value}:{proposal.proposal_id}"


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        if raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out


def _normalize(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    out: list[str] = []
    for raw in values:
        value = raw.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        out.append(value)
    return tuple(out)
