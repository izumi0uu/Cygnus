from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.review.briefing import OwnerState, ReviewRiskType
from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.providers import build_review_command_surface_from_bundles
from cygnus.review.queue import ReviewQueueSurface, build_review_queue_surface
from cygnus.review.service import ProposalBundle, derive_owner_state
from cygnus.substrate.compilation_plan import CompilationProposal, EvidenceSufficiency, UrgencyLevel


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


class PressureCommandType(str, Enum):
    ROUTE_TO_REVIEW = "route_to_review"
    ASSIGN_OWNER = "assign_owner"
    MARK_URGENT = "mark_urgent"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewPressureLine:
    proposal_ref: str
    title: str
    risk_type: ReviewRiskType
    suggested_object_type: KnowledgeObjectType
    owner_state: OwnerState
    queue_owner: str | None
    urgency: UrgencyLevel
    trigger_signals: tuple[str, ...]
    affected_audience_labels: tuple[str, ...]
    affected_surfaces: tuple[str, ...]
    evidence_sufficiency: EvidenceSufficiency
    visibility_consequence: str
    impact_summary: str
    command_actions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.proposal_ref.strip():
            raise ValueError("proposal_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        if not self.visibility_consequence.strip():
            raise ValueError("visibility_consequence must not be blank")
        if not self.impact_summary.strip():
            raise ValueError("impact_summary must not be blank")
        object.__setattr__(self, "trigger_signals", _normalize(self.trigger_signals, label="trigger signal"))
        object.__setattr__(self, "affected_audience_labels", _normalize(self.affected_audience_labels, label="affected audience label"))
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))
        object.__setattr__(self, "command_actions", _normalize(self.command_actions, label="command action"))
        if not self.command_actions:
            raise ValueError("command_actions must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_ref": self.proposal_ref,
            "title": self.title,
            "risk_type": self.risk_type.value,
            "suggested_object_type": self.suggested_object_type.value,
            "owner_state": self.owner_state.value,
            "queue_owner": self.queue_owner,
            "urgency": self.urgency.value,
            "trigger_signals": list(self.trigger_signals),
            "affected_audience_labels": list(self.affected_audience_labels),
            "affected_surfaces": list(self.affected_surfaces),
            "evidence_sufficiency": self.evidence_sufficiency.value,
            "visibility_consequence": self.visibility_consequence,
            "impact_summary": self.impact_summary,
            "command_actions": list(self.command_actions),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewPressureSurface:
    surface_id: str
    headline: str
    summary: str
    pressure_lines: tuple[ReviewPressureLine, ...]
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
        object.__setattr__(self, "pressure_lines", tuple(self.pressure_lines))
        object.__setattr__(self, "available_commands", _normalize(self.available_commands, label="available command"))
        object.__setattr__(self, "proposal_lane", _normalize(self.proposal_lane, label="proposal lane ref"))
        object.__setattr__(self, "bundles", tuple(self.bundles))
        if not self.pressure_lines:
            raise ValueError("pressure_lines must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "pressure_lines": [line.to_dict() for line in self.pressure_lines],
            "available_commands": list(self.available_commands),
            "proposal_lane": list(self.proposal_lane),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PressureCommand:
    command_type: PressureCommandType
    target_refs: tuple[str, ...] = field(default_factory=tuple)
    new_owner: str | None = None
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_refs", _normalize(self.target_refs, label="target ref"))
        if self.new_owner is not None and not self.new_owner.strip():
            raise ValueError("new_owner must not be blank when provided")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        if self.command_type is PressureCommandType.ROUTE_TO_REVIEW and not self.target_refs:
            raise ValueError("route_to_review command requires at least one target ref")
        if self.command_type in (PressureCommandType.ASSIGN_OWNER, PressureCommandType.MARK_URGENT) and len(self.target_refs) != 1:
            raise ValueError(f"{self.command_type.value} command requires exactly one target ref")
        if self.command_type is PressureCommandType.ASSIGN_OWNER and self.new_owner is None:
            raise ValueError("assign_owner command requires new_owner")


@dataclass(frozen=True, slots=True, kw_only=True)
class PressureMutationResult:
    pressure_surface: ReviewPressureSurface
    routed_queue: ReviewQueueSurface | None = None
    touched_refs: tuple[str, ...] = field(default_factory=tuple)
    owner_echo: tuple[dict[str, str | None], ...] = field(default_factory=tuple)
    urgency_echo: tuple[dict[str, str], ...] = field(default_factory=tuple)
    command_log: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "touched_refs", _normalize(self.touched_refs, label="touched ref"))
        object.__setattr__(self, "command_log", _normalize(self.command_log, label="command log"))

    def to_dict(self) -> dict[str, object]:
        return {
            "pressure_surface": self.pressure_surface.to_dict(),
            "routed_queue": self.routed_queue.to_dict() if self.routed_queue is not None else None,
            "touched_refs": list(self.touched_refs),
            "owner_echo": list(self.owner_echo),
            "urgency_echo": list(self.urgency_echo),
            "command_log": list(self.command_log),
        }


def get_review_pressure_surface(
    *,
    bundles: Iterable[ProposalBundle] | None = None,
) -> ReviewPressureSurface:
    source_bundles = tuple(bundles) if bundles is not None else sample_review_bundles()
    return build_review_pressure_surface(source_bundles)


def build_review_pressure_surface(
    bundles: Iterable[ProposalBundle],
) -> ReviewPressureSurface:
    pressure_bundles = tuple(bundle for bundle in bundles if _is_frontline_pressure(bundle))
    if not pressure_bundles:
        raise ValueError("review pressure surface requires at least one frontline pressure bundle")
    lines = tuple(_line_from_bundle(bundle) for bundle in pressure_bundles)
    return ReviewPressureSurface(
        surface_id="review-pressure",
        headline="Frontline friction rising into review pressure",
        summary=_build_surface_summary(lines),
        pressure_lines=lines,
        available_commands=_dedupe(command for line in lines for command in line.command_actions),
        proposal_lane=tuple(line.proposal_ref for line in lines),
        bundles=pressure_bundles,
    )


def apply_pressure_commands(
    pressure_surface: ReviewPressureSurface,
    commands: Iterable[PressureCommand],
) -> PressureMutationResult:
    current_bundles = pressure_surface.bundles
    routed_queue: ReviewQueueSurface | None = None
    touched_refs: list[str] = []
    command_log: list[str] = []

    for command in commands:
        if command.command_type is PressureCommandType.ASSIGN_OWNER:
            target_ref = command.target_refs[0]
            current_bundles = _assign_owner(current_bundles, proposal_ref=target_ref, new_owner=command.new_owner or "", reason=command.reason)
            touched_refs.append(target_ref)
            command_log.append(f"assign_owner:{target_ref}:{command.new_owner}:{command.reason}")
        elif command.command_type is PressureCommandType.MARK_URGENT:
            target_ref = command.target_refs[0]
            current_bundles = _mark_urgent(current_bundles, proposal_ref=target_ref)
            touched_refs.append(target_ref)
            command_log.append(f"mark_urgent:{target_ref}:{command.reason}")
        elif command.command_type is PressureCommandType.ROUTE_TO_REVIEW:
            selected_bundles = _select_bundles(current_bundles, command.target_refs)
            routed_queue = build_review_queue_surface(
                build_review_command_surface_from_bundles(
                    surface_id="review-pressure:route",
                    headline="Direct review queue routed from frontline pressure",
                    briefing_note="Frontline friction is entering governance directly without a manual knowledge task.",
                    bundles=selected_bundles,
                )
            )
            touched_refs.extend(command.target_refs)
            command_log.append(f"route_to_review:{','.join(command.target_refs)}:{command.reason}")

    next_surface = build_review_pressure_surface(current_bundles)
    touched_set = tuple(_dedupe(touched_refs))
    touched_lines = tuple(line for line in next_surface.pressure_lines if line.proposal_ref in touched_set)
    return PressureMutationResult(
        pressure_surface=next_surface,
        routed_queue=routed_queue,
        touched_refs=touched_set,
        owner_echo=tuple(
            {
                "proposal_ref": line.proposal_ref,
                "queue_owner": line.queue_owner,
                "owner_state": line.owner_state.value,
            }
            for line in touched_lines
        ),
        urgency_echo=tuple(
            {
                "proposal_ref": line.proposal_ref,
                "urgency": line.urgency.value,
            }
            for line in touched_lines
        ),
        command_log=tuple(command_log),
    )


def _is_frontline_pressure(bundle: ProposalBundle) -> bool:
    trigger_signals = set(bundle.signal.trigger_signals)
    return "rewrite_cluster" in trigger_signals or "ticket_pressure" in trigger_signals


def _line_from_bundle(bundle: ProposalBundle) -> ReviewPressureLine:
    proposal = bundle.proposal
    signal = bundle.signal
    owner_state = bundle.owner_state or derive_owner_state(proposal=proposal, signal=signal)
    queue_owner = _queue_owner(proposal=proposal, queue_owner=signal.queue_owner, owner_state=owner_state)
    audience_labels = tuple(_audience_label(audience) for audience in signal.affected_audiences)
    affected_surfaces = tuple(_dedupe(signal.affected_surfaces))
    return ReviewPressureLine(
        proposal_ref=proposal.proposal_id,
        title=proposal.title,
        risk_type=signal.risk_type,
        suggested_object_type=proposal.object_type,
        owner_state=owner_state,
        queue_owner=queue_owner,
        urgency=proposal.urgency,
        trigger_signals=signal.trigger_signals,
        affected_audience_labels=audience_labels,
        affected_surfaces=affected_surfaces,
        evidence_sufficiency=proposal.evidence_sufficiency,
        visibility_consequence=_visibility_consequence(
            audiences=signal.affected_audiences,
            surfaces=affected_surfaces,
            evidence_sufficiency=proposal.evidence_sufficiency,
        ),
        impact_summary=_impact_summary(
            object_type=proposal.object_type,
            audiences=audience_labels,
            surfaces=affected_surfaces,
        ),
        command_actions=("route_to_review", "assign_owner", "mark_urgent"),
    )


def _queue_owner(
    *,
    proposal: CompilationProposal,
    queue_owner: str | None,
    owner_state: OwnerState,
) -> str | None:
    if owner_state is OwnerState.UNASSIGNED:
        return None
    return queue_owner or proposal.review_owner


def _impact_summary(
    *,
    object_type: KnowledgeObjectType,
    audiences: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> str:
    surface_phrase = ", ".join(surfaces)
    return (
        f"Suggested {object_type.value} spans {len(audiences)} audience lane(s) "
        f"across {surface_phrase}."
    )


def _visibility_consequence(
    *,
    audiences: tuple[AudienceFilter, ...],
    surfaces: tuple[str, ...],
    evidence_sufficiency: EvidenceSufficiency,
) -> str:
    external_count = sum(1 for audience in audiences if audience.visibility.value == "external")
    surface_phrase = ", ".join(surfaces)
    if external_count:
        return (
            f"{external_count} external audience lane(s) may continue receiving unsupported guidance "
            f"across {surface_phrase} while evidence is {evidence_sufficiency.value}."
        )
    return (
        f"Pressure is currently contained to internal surfaces ({surface_phrase}), "
        f"but evidence is still {evidence_sufficiency.value}."
    )


def _build_surface_summary(lines: tuple[ReviewPressureLine, ...]) -> str:
    rewrite_driven = sum(1 for line in lines if "rewrite_cluster" in line.trigger_signals)
    ticket_driven = sum(1 for line in lines if "ticket_pressure" in line.trigger_signals)
    return (
        f"{len(lines)} frontline pressure line(s) are ready to enter review; "
        f"{rewrite_driven} rewrite-driven and {ticket_driven} recurring-ticket-driven signal(s) "
        "can route directly into governance."
    )


def _assign_owner(
    bundles: tuple[ProposalBundle, ...],
    *,
    proposal_ref: str,
    new_owner: str,
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
                    review_owner=new_owner,
                    why_now=f"{bundle.proposal.why_now.rstrip('.')} Ownership rerouted because {reason}.",
                ),
                signal=replace(bundle.signal, queue_owner=new_owner),
                owner_state=OwnerState.ASSIGNED,
            )
        )
    if not found:
        raise ValueError(f"proposal_ref={proposal_ref} is not present in review pressure")
    return tuple(updated)


def _mark_urgent(
    bundles: tuple[ProposalBundle, ...],
    *,
    proposal_ref: str,
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
                proposal=replace(bundle.proposal, urgency=UrgencyLevel.URGENT),
            )
        )
    if not found:
        raise ValueError(f"proposal_ref={proposal_ref} is not present in review pressure")
    return tuple(updated)


def _select_bundles(
    bundles: tuple[ProposalBundle, ...],
    target_refs: tuple[str, ...],
) -> tuple[ProposalBundle, ...]:
    mapping = {bundle.proposal.proposal_id: bundle for bundle in bundles}
    missing = [ref for ref in target_refs if ref not in mapping]
    if missing:
        raise ValueError(f"unknown review pressure refs: {', '.join(missing)}")
    return tuple(mapping[ref] for ref in target_refs)


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
