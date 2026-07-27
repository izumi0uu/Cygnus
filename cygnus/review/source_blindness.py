from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import FreshnessState, SupportEvidence
from cygnus.retrieval.substrate_provider import resolve_object_type
from cygnus.publish.actions import (
    PublishGovernanceAction,
    PublishGovernanceActionType,
    PublishGovernanceResult,
    apply_publish_governance_actions,
)
from cygnus.publish.preview import PublishActionType, PublishBinding, PublishPreviewCandidate
from cygnus.publish.propagation import PublishPropagationLedger, build_publish_propagation_ledger
from cygnus.review.briefing import OwnerState, ReviewRiskType
from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.providers import build_review_command_surface_from_bundles
from cygnus.review.queue import ReviewQueueSurface, build_review_queue_surface
from cygnus.review.service import ProposalBundle
from cygnus.review.surface import ObservationState, SurfaceObservation

if TYPE_CHECKING:
    from cygnus.runtime.database.models import Source, WikiPage


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
class SourceFailureObservation:
    source_id: str
    title: str
    source_ref: str
    status: str
    error_message: str
    linked_wiki_refs: tuple[str, ...] = field(default_factory=tuple)
    linked_object_refs: tuple[str, ...] = field(default_factory=tuple)
    observed_at: str | None = None
    impact_state: str = "unknown"

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_id, "source_id"),
            (self.title, "title"),
            (self.source_ref, "source_ref"),
            (self.error_message, "error_message"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be blank")
        if self.status != "error":
            raise ValueError("source failure observation status must be error")
        if self.impact_state != "unknown":
            raise ValueError("source failure impact_state must remain unknown")
        if self.observed_at is not None and not self.observed_at.strip():
            raise ValueError("observed_at must not be blank when provided")
        object.__setattr__(
            self,
            "linked_wiki_refs",
            tuple(dict.fromkeys(_normalize(self.linked_wiki_refs, label="linked wiki ref"))),
        )
        object.__setattr__(
            self,
            "linked_object_refs",
            tuple(dict.fromkeys(_normalize(self.linked_object_refs, label="linked object ref"))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "source_ref": self.source_ref,
            "status": self.status,
            "error_message": self.error_message,
            "linked_wiki_refs": list(self.linked_wiki_refs),
            "linked_object_refs": list(self.linked_object_refs),
            "observed_at": self.observed_at,
            "impact_state": self.impact_state,
        }


def build_source_failure_observations(
    sources: Iterable["Source"],
    linked_pages: Iterable["WikiPage"],
) -> tuple[SourceFailureObservation, ...]:
    page_refs_by_source: dict[object, list[tuple[str, str | None]]] = {}
    for page in linked_pages:
        object_ref = f"ko-{page.slug}" if resolve_object_type(page.knowledge_type_slugs) is not None else None
        for source_id in page.source_ids or ():
            page_refs_by_source.setdefault(source_id, []).append((page.slug, object_ref))

    observations: list[SourceFailureObservation] = []
    for source in sorted(sources, key=lambda row: str(row.id)):
        if source.status != "error":
            continue
        linked_refs = page_refs_by_source.get(source.id, ())
        observations.append(
            SourceFailureObservation(
                source_id=str(source.id),
                title=(source.title or "").strip() or source.file_name or f"source:{source.id}",
                source_ref=source.url or source.file_name or f"source:{source.id}",
                status=source.status,
                error_message=(source.error_message or "").strip() or "source_error_detail_unavailable",
                linked_wiki_refs=tuple(sorted({slug for slug, _object_ref in linked_refs})),
                linked_object_refs=tuple(sorted({object_ref for _slug, object_ref in linked_refs if object_ref is not None})),
                observed_at=source.updated_at.isoformat() if source.updated_at else None,
            )
        )
    return tuple(observations)


class SourceBlindnessCommandType(str, Enum):
    REPAIR_SOURCE = "repair_source"
    RESTRICT_PROPAGATION = "restrict_propagation"
    ROUTE_TO_HUMAN_REVIEW = "route_to_human_review"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceBlindnessContext:
    proposal_ref: str
    title: str
    risk_type: ReviewRiskType
    suggested_object_type: KnowledgeObjectType
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    source_types: tuple[str, ...]
    freshness_states: tuple[str, ...]
    affected_audience_labels: tuple[str, ...]
    affected_surfaces: tuple[str, ...]
    business_consequence: str
    propagation_risk_summary: str
    signal_loss_summary: str

    def __post_init__(self) -> None:
        if not self.proposal_ref.strip():
            raise ValueError("proposal_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.business_consequence.strip():
            raise ValueError("business_consequence must not be blank")
        if not self.propagation_risk_summary.strip():
            raise ValueError("propagation_risk_summary must not be blank")
        if not self.signal_loss_summary.strip():
            raise ValueError("signal_loss_summary must not be blank")
        object.__setattr__(self, "evidence_ids", _normalize(self.evidence_ids, label="evidence id"))
        object.__setattr__(self, "source_refs", _normalize(self.source_refs, label="source ref"))
        object.__setattr__(self, "source_types", _normalize(self.source_types, label="source type"))
        object.__setattr__(self, "freshness_states", _normalize(self.freshness_states, label="freshness state"))
        object.__setattr__(self, "affected_audience_labels", _normalize(self.affected_audience_labels, label="audience label"))
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_ref": self.proposal_ref,
            "title": self.title,
            "risk_type": self.risk_type.value,
            "suggested_object_type": self.suggested_object_type.value,
            "evidence_ids": list(self.evidence_ids),
            "source_refs": list(self.source_refs),
            "source_types": list(self.source_types),
            "freshness_states": list(self.freshness_states),
            "affected_audience_labels": list(self.affected_audience_labels),
            "affected_surfaces": list(self.affected_surfaces),
            "business_consequence": self.business_consequence,
            "propagation_risk_summary": self.propagation_risk_summary,
            "signal_loss_summary": self.signal_loss_summary,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceBlindnessSurface:
    surface_id: str
    headline: str
    summary: str
    observation: SurfaceObservation
    contexts: tuple[SourceBlindnessContext, ...]
    source_observations: tuple[SourceFailureObservation, ...] = field(default_factory=tuple)
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
        object.__setattr__(self, "source_observations", tuple(self.source_observations))
        object.__setattr__(self, "available_commands", _normalize(self.available_commands, label="available command"))
        object.__setattr__(self, "proposal_lane", _normalize(self.proposal_lane, label="proposal lane"))
        object.__setattr__(self, "bundles", tuple(self.bundles))

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "observation": self.observation.to_dict(),
            "contexts": [context.to_dict() for context in self.contexts],
            "source_observations": [item.to_dict() for item in self.source_observations],
            "available_commands": list(self.available_commands),
            "proposal_lane": list(self.proposal_lane),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceBlindnessCommand:
    command_type: SourceBlindnessCommandType
    target_ref: str
    reason: str

    def __post_init__(self) -> None:
        if not self.target_ref.strip():
            raise ValueError("target_ref must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRepairDirective:
    proposal_ref: str
    source_refs: tuple[str, ...]
    source_types: tuple[str, ...]
    affected_audience_labels: tuple[str, ...]
    affected_surfaces: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not self.proposal_ref.strip():
            raise ValueError("proposal_ref must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        object.__setattr__(self, "source_refs", _normalize(self.source_refs, label="source ref"))
        object.__setattr__(self, "source_types", _normalize(self.source_types, label="source type"))
        object.__setattr__(self, "affected_audience_labels", _normalize(self.affected_audience_labels, label="audience label"))
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_ref": self.proposal_ref,
            "source_refs": list(self.source_refs),
            "source_types": list(self.source_types),
            "affected_audience_labels": list(self.affected_audience_labels),
            "affected_surfaces": list(self.affected_surfaces),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceBlindnessResult:
    source_surface: SourceBlindnessSurface
    repair_directives: tuple[SourceRepairDirective, ...] = field(default_factory=tuple)
    publish_restriction_result: PublishGovernanceResult | None = None
    propagation_ledger: PublishPropagationLedger | None = None
    human_review_queue: ReviewQueueSurface | None = None
    context_trail: tuple[dict[str, object], ...] = field(default_factory=tuple)
    command_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repair_directives", tuple(self.repair_directives))
        object.__setattr__(self, "command_log", _normalize(self.command_log, label="command log"))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_surface": self.source_surface.to_dict(),
            "repair_directives": [directive.to_dict() for directive in self.repair_directives],
            "publish_restriction_result": self.publish_restriction_result.to_dict() if self.publish_restriction_result is not None else None,
            "propagation_ledger": self.propagation_ledger.to_dict() if self.propagation_ledger is not None else None,
            "human_review_queue": self.human_review_queue.to_dict() if self.human_review_queue is not None else None,
            "context_trail": list(self.context_trail),
            "command_log": list(self.command_log),
        }


def get_source_blindness_surface(
    *,
    bundles: Iterable[ProposalBundle] | None = None,
    observation: SurfaceObservation | None = None,
    source_observations: Iterable[SourceFailureObservation] = (),
) -> SourceBlindnessSurface:
    source_bundles = tuple(bundles) if bundles is not None else sample_review_bundles()
    return build_source_blindness_surface(
        source_bundles,
        observation=observation,
        source_observations=source_observations,
    )


def build_source_blindness_surface(
    bundles: Iterable[ProposalBundle],
    *,
    observation: SurfaceObservation | None = None,
    source_observations: Iterable[SourceFailureObservation] = (),
) -> SourceBlindnessSurface:
    blindness_bundles = tuple(bundle for bundle in bundles if _is_source_blindness_bundle(bundle))
    if not blindness_bundles and observation is None:
        raise ValueError("empty source blindness surfaces require an explicit observation")
    contexts = tuple(_context_from_bundle(bundle) for bundle in blindness_bundles)
    resolved_observation = observation or SurfaceObservation(
        state=ObservationState.READY,
        observed_count=len(blindness_bundles),
        reason="source_impact_observed",
        covered_signals=("source_status", "source_impact"),
    )
    return SourceBlindnessSurface(
        surface_id="source-health",
        headline="Source health governance",
        summary=(
            _build_summary(contexts)
            if contexts
            else "Source failures are observable; downstream impact is not yet modeled."
        ),
        observation=resolved_observation,
        contexts=contexts,
        source_observations=tuple(source_observations),
        available_commands=(
            (
                SourceBlindnessCommandType.REPAIR_SOURCE.value,
                SourceBlindnessCommandType.RESTRICT_PROPAGATION.value,
                SourceBlindnessCommandType.ROUTE_TO_HUMAN_REVIEW.value,
            )
            if contexts
            else ()
        ),
        proposal_lane=tuple(context.proposal_ref for context in contexts),
        bundles=blindness_bundles,
    )


def apply_source_blindness_commands(
    source_surface: SourceBlindnessSurface,
    commands: Iterable[SourceBlindnessCommand],
) -> SourceBlindnessResult:
    current_bundles = source_surface.bundles
    repair_directives: list[SourceRepairDirective] = []
    publish_restriction_result: PublishGovernanceResult | None = None
    propagation_ledger: PublishPropagationLedger | None = None
    human_review_queue: ReviewQueueSurface | None = None
    context_trail: list[dict[str, object]] = []
    command_log: list[str] = []

    for command in commands:
        bundle = _require_bundle(current_bundles, command.target_ref)
        context = _context_from_bundle(bundle)

        if command.command_type is SourceBlindnessCommandType.REPAIR_SOURCE:
            current_bundles, directive = _request_source_repair(
                current_bundles,
                proposal_ref=command.target_ref,
                reason=command.reason,
            )
            repair_directives.append(directive)
            context_trail.append(_phase_context(phase="source_repair", context=context, reason=command.reason))
            command_log.append(f"repair_source:{command.target_ref}:{command.reason}")
            continue

        if command.command_type is SourceBlindnessCommandType.RESTRICT_PROPAGATION:
            publish_restriction_result = apply_publish_governance_actions(
                _build_restriction_candidate(bundle),
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
            propagation_ledger = build_publish_propagation_ledger(
                publish_restriction_result,
                supporting_surfaces=("review_queue", "source_health"),
            )
            context_trail.append(_phase_context(phase="restrict_propagation", context=context, reason=command.reason))
            command_log.append(f"restrict_propagation:{command.target_ref}:{command.reason}")
            continue

        if command.command_type is SourceBlindnessCommandType.ROUTE_TO_HUMAN_REVIEW:
            current_bundles = _route_to_human_review(
                current_bundles,
                proposal_ref=command.target_ref,
                reason=command.reason,
            )
            updated_bundle = _require_bundle(current_bundles, command.target_ref)
            human_review_queue = build_review_queue_surface(
                build_review_command_surface_from_bundles(
                    surface_id="source-blindness:human-review",
                    headline="Source blindness routed into human review before trust degrades further",
                    briefing_note="This path preserves the business consequence of source loss while routing the object into an explicit human review lane.",
                    bundles=(updated_bundle,),
                )
            )
            context_trail.append(_phase_context(phase="human_review", context=context, reason=command.reason))
            command_log.append(f"route_to_human_review:{command.target_ref}:{command.reason}")
            continue

        raise ValueError(f"unsupported source blindness command: {command.command_type.value}")

    next_surface = build_source_blindness_surface(current_bundles)
    return SourceBlindnessResult(
        source_surface=next_surface,
        repair_directives=tuple(repair_directives),
        publish_restriction_result=publish_restriction_result,
        propagation_ledger=propagation_ledger,
        human_review_queue=human_review_queue,
        context_trail=tuple(context_trail),
        command_log=tuple(command_log),
    )


def _is_source_blindness_bundle(bundle: ProposalBundle) -> bool:
    return bundle.signal.risk_type is ReviewRiskType.SOURCE_BLINDNESS


def _context_from_bundle(bundle: ProposalBundle) -> SourceBlindnessContext:
    evidence = bundle.evidence
    source_refs = _dedupe(record.source_ref for record in evidence)
    source_types = _dedupe(record.source_type.value for record in evidence)
    freshness_states = _dedupe(record.freshness_state.value for record in evidence)
    audience_labels = tuple(_audience_label(audience) for audience in bundle.signal.affected_audiences)
    affected_surfaces = _dedupe(bundle.signal.affected_surfaces)
    business_consequence = _business_consequence(
        object_type=bundle.proposal.object_type,
        audiences=audience_labels,
        surfaces=affected_surfaces,
    )
    propagation_risk_summary = _propagation_risk_summary(
        evidence=evidence,
        surfaces=affected_surfaces,
        audiences=bundle.signal.affected_audiences,
    )
    return SourceBlindnessContext(
        proposal_ref=bundle.proposal.proposal_id,
        title=bundle.proposal.title,
        risk_type=bundle.signal.risk_type,
        suggested_object_type=bundle.proposal.object_type,
        evidence_ids=bundle.proposal.evidence_ids,
        source_refs=source_refs,
        source_types=source_types,
        freshness_states=freshness_states,
        affected_audience_labels=audience_labels,
        affected_surfaces=affected_surfaces,
        business_consequence=business_consequence,
        propagation_risk_summary=propagation_risk_summary,
        signal_loss_summary=(
            f"{len(source_refs)} degraded source path(s) now weaken confidence for "
            f"{bundle.proposal.object_type.value} decisions tied to this object."
        ),
    )


def _build_summary(contexts: tuple[SourceBlindnessContext, ...]) -> str:
    external_paths = sum(
        1
        for context in contexts
        if any(label.startswith("external") for label in context.affected_audience_labels)
    )
    return (
        f"{len(contexts)} source-blind governance path(s) are active; "
        f"{external_paths} path(s) currently threaten customer-facing propagation if teams do not contain spread."
    )


def _request_source_repair(
    bundles: tuple[ProposalBundle, ...],
    *,
    proposal_ref: str,
    reason: str,
) -> tuple[tuple[ProposalBundle, ...], SourceRepairDirective]:
    updated: list[ProposalBundle] = []
    directive: SourceRepairDirective | None = None
    found = False
    for bundle in bundles:
        if bundle.proposal.proposal_id != proposal_ref:
            updated.append(bundle)
            continue
        found = True
        context = _context_from_bundle(bundle)
        directive = SourceRepairDirective(
            proposal_ref=context.proposal_ref,
            source_refs=context.source_refs,
            source_types=context.source_types,
            affected_audience_labels=context.affected_audience_labels,
            affected_surfaces=context.affected_surfaces,
            reason=reason,
        )
        updated.append(
            replace(
                bundle,
                proposal=replace(
                    bundle.proposal,
                    why_now=_append_reason(
                        bundle.proposal.why_now,
                        reason=reason,
                        prefix="Source repair is now part of the governance command path because",
                    ),
                ),
                signal=replace(
                    bundle.signal,
                    trigger_signals=_dedupe((*bundle.signal.trigger_signals, "source_repair_requested")),
                ),
            )
        )
    if not found or directive is None:
        raise ValueError(f"proposal_ref={proposal_ref} is not present in source blindness")
    return tuple(updated), directive


def _route_to_human_review(
    bundles: tuple[ProposalBundle, ...],
    *,
    proposal_ref: str,
    reason: str,
) -> tuple[ProposalBundle, ...]:
    updated: list[ProposalBundle] = []
    found = False
    for bundle in bundles:
        if bundle.proposal.proposal_id != proposal_ref:
            updated.append(bundle)
            continue
        found = True
        updated.append(
            replace(
                bundle,
                proposal=replace(
                    bundle.proposal,
                    review_owner="human-review",
                    why_now=_append_reason(
                        bundle.proposal.why_now,
                        reason=reason,
                        prefix="Human review has been forced because",
                    ),
                ),
                signal=replace(
                    bundle.signal,
                    queue_owner="human-review",
                    trigger_signals=_dedupe((*bundle.signal.trigger_signals, "human_review_routed")),
                ),
                owner_state=OwnerState.ESCALATED,
            )
        )
    if not found:
        raise ValueError(f"proposal_ref={proposal_ref} is not present in source blindness")
    return tuple(updated)


def _build_restriction_candidate(bundle: ProposalBundle) -> PublishPreviewCandidate:
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


def _phase_context(*, phase: str, context: SourceBlindnessContext, reason: str) -> dict[str, object]:
    return {
        "phase": phase,
        "proposal_ref": context.proposal_ref,
        "source_refs": list(context.source_refs),
        "source_types": list(context.source_types),
        "affected_surfaces": list(context.affected_surfaces),
        "affected_audience_labels": list(context.affected_audience_labels),
        "reason": reason,
    }


def _require_bundle(bundles: tuple[ProposalBundle, ...], proposal_ref: str) -> ProposalBundle:
    for bundle in bundles:
        if bundle.proposal.proposal_id == proposal_ref:
            return bundle
    raise ValueError(f"proposal_ref={proposal_ref} is not present in source blindness")


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


def _business_consequence(
    *,
    object_type: KnowledgeObjectType,
    audiences: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> str:
    return (
        f"This {object_type.value} is losing governance confidence for {len(audiences)} audience lane(s), "
        f"so {', '.join(surfaces)} may keep serving stale guidance unless teams intervene."
    )


def _propagation_risk_summary(
    *,
    evidence: tuple[SupportEvidence, ...],
    surfaces: tuple[str, ...],
    audiences: tuple[AudienceFilter, ...],
) -> str:
    stale_count = sum(1 for record in evidence if record.freshness_state is FreshnessState.STALE)
    external_labels = [_audience_label(audience) for audience in audiences if audience.visibility is Visibility.EXTERNAL]
    if external_labels:
        return (
            f"{stale_count or len(evidence)} degraded source signal(s) currently threaten external propagation on "
            f"{', '.join(surfaces)} for {', '.join(external_labels)}."
        )
    return (
        f"Propagation risk is currently concentrated on internal surfaces ({', '.join(surfaces)}), "
        "but governance confidence is still degraded until sources are repaired."
    )


def _append_reason(base: str, *, reason: str, prefix: str) -> str:
    return f"{base.rstrip('.')} {prefix} {reason}."


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)
