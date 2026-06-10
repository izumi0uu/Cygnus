from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType
from cygnus.publish.actions import (
    PublishGovernanceAction,
    PublishGovernanceActionType,
    PublishGovernanceResult,
    apply_publish_governance_actions,
)
from cygnus.publish.preview import PublishActionType, PublishBinding, PublishPreviewCandidate
from cygnus.review.briefing import ReviewRiskType
from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.providers import build_review_command_surface_from_bundles
from cygnus.review.queue import ReviewQueueSurface, build_review_queue_surface
from cygnus.review.service import ProposalBundle
from cygnus.substrate.compilation_plan import UrgencyLevel


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


class DriftGovernanceCommandType(str, Enum):
    OPEN_URGENT_REVIEW = "open_urgent_review"
    FREEZE_EXTERNAL_PUBLISH = "freeze_external_publish"
    FORCE_AUDIENCE_RECHECK = "force_audience_recheck"


@dataclass(frozen=True, slots=True, kw_only=True)
class DriftContext:
    proposal_ref: str
    title: str
    risk_type: ReviewRiskType
    suggested_object_type: KnowledgeObjectType
    urgency: UrgencyLevel
    why_now: str
    evidence_ids: tuple[str, ...]
    event_refs: tuple[str, ...]
    event_types: tuple[str, ...]
    trigger_signals: tuple[str, ...]
    affected_audience_labels: tuple[str, ...]
    affected_surfaces: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.proposal_ref.strip():
            raise ValueError("proposal_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.why_now.strip():
            raise ValueError("why_now must not be blank")
        object.__setattr__(self, "evidence_ids", _normalize(self.evidence_ids, label="evidence id"))
        object.__setattr__(self, "event_refs", _normalize(self.event_refs, label="event ref"))
        object.__setattr__(self, "event_types", _normalize(self.event_types, label="event type"))
        object.__setattr__(self, "trigger_signals", _normalize(self.trigger_signals, label="trigger signal"))
        object.__setattr__(self, "affected_audience_labels", _normalize(self.affected_audience_labels, label="audience label"))
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_ref": self.proposal_ref,
            "title": self.title,
            "risk_type": self.risk_type.value,
            "suggested_object_type": self.suggested_object_type.value,
            "urgency": self.urgency.value,
            "why_now": self.why_now,
            "evidence_ids": list(self.evidence_ids),
            "event_refs": list(self.event_refs),
            "event_types": list(self.event_types),
            "trigger_signals": list(self.trigger_signals),
            "affected_audience_labels": list(self.affected_audience_labels),
            "affected_surfaces": list(self.affected_surfaces),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DriftGovernanceSurface:
    surface_id: str
    headline: str
    summary: str
    contexts: tuple[DriftContext, ...]
    available_commands: tuple[str, ...] = field(default_factory=tuple)
    proposal_lane: tuple[str, ...] = field(default_factory=tuple)
    bundles: tuple[ProposalBundle, ...] = field(default_factory=tuple, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        object.__setattr__(self, "contexts", tuple(self.contexts))
        object.__setattr__(self, "available_commands", _normalize(self.available_commands, label="available command"))
        object.__setattr__(self, "proposal_lane", _normalize(self.proposal_lane, label="proposal lane"))
        object.__setattr__(self, "bundles", tuple(self.bundles))
        if not self.contexts:
            raise ValueError("contexts must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "contexts": [context.to_dict() for context in self.contexts],
            "available_commands": list(self.available_commands),
            "proposal_lane": list(self.proposal_lane),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DriftGovernanceCommand:
    command_type: DriftGovernanceCommandType
    target_ref: str
    reason: str

    def __post_init__(self) -> None:
        if not self.target_ref.strip():
            raise ValueError("target_ref must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class DriftGovernanceResult:
    drift_surface: DriftGovernanceSurface
    urgent_review_queue: ReviewQueueSurface | None = None
    publish_freeze_result: PublishGovernanceResult | None = None
    audience_recheck_labels: tuple[str, ...] = field(default_factory=tuple)
    context_trail: tuple[dict[str, object], ...] = field(default_factory=tuple)
    command_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "audience_recheck_labels", _normalize(self.audience_recheck_labels, label="audience recheck label"))
        object.__setattr__(self, "command_log", _normalize(self.command_log, label="command log"))

    def to_dict(self) -> dict[str, object]:
        return {
            "drift_surface": self.drift_surface.to_dict(),
            "urgent_review_queue": self.urgent_review_queue.to_dict() if self.urgent_review_queue is not None else None,
            "publish_freeze_result": self.publish_freeze_result.to_dict() if self.publish_freeze_result is not None else None,
            "audience_recheck_labels": list(self.audience_recheck_labels),
            "context_trail": list(self.context_trail),
            "command_log": list(self.command_log),
        }


def get_drift_governance_surface(
    *,
    bundles: Iterable[ProposalBundle] | None = None,
) -> DriftGovernanceSurface:
    source_bundles = tuple(bundles) if bundles is not None else sample_review_bundles()
    return build_drift_governance_surface(source_bundles)


def build_drift_governance_surface(
    bundles: Iterable[ProposalBundle],
) -> DriftGovernanceSurface:
    drift_bundles = tuple(bundle for bundle in bundles if _is_drift_bundle(bundle))
    if not drift_bundles:
        raise ValueError("drift governance surface requires at least one release/incident drift bundle")
    contexts = tuple(_context_from_bundle(bundle) for bundle in drift_bundles)
    return DriftGovernanceSurface(
        surface_id="drift-governance",
        headline="Release and incident drift can now force a governance path",
        summary=_build_summary(contexts),
        contexts=contexts,
        available_commands=(
            DriftGovernanceCommandType.OPEN_URGENT_REVIEW.value,
            DriftGovernanceCommandType.FREEZE_EXTERNAL_PUBLISH.value,
            DriftGovernanceCommandType.FORCE_AUDIENCE_RECHECK.value,
        ),
        proposal_lane=tuple(context.proposal_ref for context in contexts),
        bundles=drift_bundles,
    )


def apply_drift_governance_commands(
    drift_surface: DriftGovernanceSurface,
    commands: Iterable[DriftGovernanceCommand],
) -> DriftGovernanceResult:
    current_bundles = drift_surface.bundles
    urgent_review_queue: ReviewQueueSurface | None = None
    publish_freeze_result: PublishGovernanceResult | None = None
    audience_recheck_labels: list[str] = []
    context_trail: list[dict[str, object]] = []
    command_log: list[str] = []

    for command in commands:
        bundle = _require_bundle(current_bundles, command.target_ref)
        context = _context_from_bundle(bundle)
        if command.command_type is DriftGovernanceCommandType.OPEN_URGENT_REVIEW:
            current_bundles = _replace_bundle(
                current_bundles,
                replace(bundle, proposal=replace(bundle.proposal, urgency=UrgencyLevel.URGENT)),
            )
            updated_bundle = _require_bundle(current_bundles, command.target_ref)
            urgent_review_queue = build_review_queue_surface(
                build_review_command_surface_from_bundles(
                    surface_id="drift-governance:urgent-review",
                    headline="Urgent review opened from release/incident drift",
                    briefing_note="Drift can now open an urgent review path before more downstream surfaces absorb stale guidance.",
                    bundles=(updated_bundle,),
                )
            )
            context_trail.append(_phase_context(phase="urgent_review", context=context, reason=command.reason))
            command_log.append(f"open_urgent_review:{command.target_ref}:{command.reason}")
            continue

        if command.command_type is DriftGovernanceCommandType.FREEZE_EXTERNAL_PUBLISH:
            publish_freeze_result = apply_publish_governance_actions(
                _build_freeze_candidate(bundle),
                (
                    PublishGovernanceAction(
                        action_type=PublishGovernanceActionType.HOLD_EXTERNAL,
                        audiences=tuple(
                            audience
                            for audience in bundle.signal.affected_audiences
                            if audience.visibility is Visibility.EXTERNAL
                        ),
                        channels=bundle.signal.affected_surfaces,
                        reason=command.reason,
                    ),
                ),
            )
            context_trail.append(_phase_context(phase="publish_freeze", context=context, reason=command.reason))
            command_log.append(f"freeze_external_publish:{command.target_ref}:{command.reason}")
            continue

        if command.command_type is DriftGovernanceCommandType.FORCE_AUDIENCE_RECHECK:
            audience_recheck_labels.extend(context.affected_audience_labels)
            context_trail.append(_phase_context(phase="audience_recheck", context=context, reason=command.reason))
            command_log.append(f"force_audience_recheck:{command.target_ref}:{command.reason}")
            continue

        raise ValueError(f"unsupported drift governance command: {command.command_type.value}")

    next_surface = build_drift_governance_surface(current_bundles)
    return DriftGovernanceResult(
        drift_surface=next_surface,
        urgent_review_queue=urgent_review_queue,
        publish_freeze_result=publish_freeze_result,
        audience_recheck_labels=_dedupe(audience_recheck_labels),
        context_trail=tuple(context_trail),
        command_log=tuple(command_log),
    )


def _is_drift_bundle(bundle: ProposalBundle) -> bool:
    if bundle.signal.risk_type is not ReviewRiskType.DRIFT:
        return False
    trigger_signals = set(bundle.signal.trigger_signals)
    event_types = {record.source_type for record in bundle.evidence}
    return (
        "release_delta" in trigger_signals
        or "active_incident" in trigger_signals
        or EvidenceSourceType.RELEASE_NOTE in event_types
        or EvidenceSourceType.INCIDENT_UPDATE in event_types
    )


def _context_from_bundle(bundle: ProposalBundle) -> DriftContext:
    event_records = tuple(
        record
        for record in bundle.evidence
        if record.source_type in (EvidenceSourceType.RELEASE_NOTE, EvidenceSourceType.INCIDENT_UPDATE)
    )
    return DriftContext(
        proposal_ref=bundle.proposal.proposal_id,
        title=bundle.proposal.title,
        risk_type=bundle.signal.risk_type,
        suggested_object_type=bundle.proposal.object_type,
        urgency=bundle.proposal.urgency,
        why_now=bundle.proposal.why_now,
        evidence_ids=bundle.proposal.evidence_ids,
        event_refs=_dedupe(record.source_ref for record in event_records),
        event_types=_dedupe(record.source_type.value for record in event_records),
        trigger_signals=bundle.signal.trigger_signals,
        affected_audience_labels=tuple(_audience_label(audience) for audience in bundle.signal.affected_audiences),
        affected_surfaces=_dedupe(bundle.signal.affected_surfaces),
    )


def _build_summary(contexts: tuple[DriftContext, ...]) -> str:
    release_events = sum(1 for context in contexts if "release_note" in context.event_types)
    incident_events = sum(1 for context in contexts if "incident_update" in context.event_types)
    return (
        f"{len(contexts)} drift path(s) can now force governance; "
        f"{release_events} release-linked and {incident_events} incident-linked path(s) "
        "can freeze spread before content repair is complete."
    )


def _build_freeze_candidate(bundle: ProposalBundle) -> PublishPreviewCandidate:
    target_bindings = tuple(
        PublishBinding(audience_filter=audience, channel=surface)
        for audience in bundle.signal.affected_audiences
        for surface in bundle.signal.affected_surfaces
    )
    return PublishPreviewCandidate(
        object_id=bundle.proposal.proposal_id,
        object_type=bundle.proposal.object_type,
        title=bundle.proposal.title,
        action_type=PublishActionType.REPUBLISH,
        target_audiences=bundle.signal.affected_audiences,
        target_channels=bundle.signal.affected_surfaces,
        target_bindings=target_bindings,
        current_bindings=target_bindings,
    )


def _phase_context(*, phase: str, context: DriftContext, reason: str) -> dict[str, object]:
    return {
        "phase": phase,
        "proposal_ref": context.proposal_ref,
        "event_refs": list(context.event_refs),
        "event_types": list(context.event_types),
        "evidence_ids": list(context.evidence_ids),
        "affected_surfaces": list(context.affected_surfaces),
        "reason": reason,
    }


def _require_bundle(bundles: tuple[ProposalBundle, ...], proposal_ref: str) -> ProposalBundle:
    for bundle in bundles:
        if bundle.proposal.proposal_id == proposal_ref:
            return bundle
    raise ValueError(f"proposal_ref={proposal_ref} is not present in drift governance")


def _replace_bundle(bundles: tuple[ProposalBundle, ...], updated_bundle: ProposalBundle) -> tuple[ProposalBundle, ...]:
    return tuple(
        updated_bundle if bundle.proposal.proposal_id == updated_bundle.proposal.proposal_id else bundle
        for bundle in bundles
    )


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


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)
