from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.publish.actions import (
    PublishGovernanceAction,
    PublishGovernanceActionType,
    PublishGovernanceResult,
    apply_publish_governance_actions,
)
from cygnus.publish.propagation import (
    PropagationStatus,
    PublishPropagationLedger,
    SurfacePropagationUpdate,
    build_publish_propagation_ledger,
)
from cygnus.publish.preview import (
    BlastRadiusEffect,
    BlastRadiusPreview,
    PublishActionType,
    PublishBinding,
    PublishConflict,
    PublishPreviewCandidate,
    build_publish_blast_radius_preview,
)
from cygnus.review.intake import (
    PressureIntakeBundle,
    PressureIntakeRecord,
    PressureSignalType,
    compile_pressure_intake_bundle,
    get_pressure_intake_review_brief_surface,
    sample_pressure_intake_records,
)
from cygnus.review.surface import PriorityStackCard, ReviewCommandSurface


def _normalize(values: Iterable[str] | None, *, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    out: list[str] = []
    for raw in values:
        value = raw.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        if value not in out:
            out.append(value)
    return tuple(out)


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishSituationFrame:
    briefing_note: str
    truth_boundary: str
    consequence_summary: str
    blocked_paths: int
    new_paths: int
    stopped_paths: int
    affected_surfaces: tuple[str, ...]
    recommended_commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.briefing_note.strip():
            raise ValueError("briefing_note must not be blank")
        if not self.truth_boundary.strip():
            raise ValueError("truth_boundary must not be blank")
        if not self.consequence_summary.strip():
            raise ValueError("consequence_summary must not be blank")
        for field_name in ("blocked_paths", "new_paths", "stopped_paths"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))
        object.__setattr__(self, "recommended_commands", _normalize(self.recommended_commands, label="recommended command"))

    def to_dict(self) -> dict[str, object]:
        return {
            "briefing_note": self.briefing_note,
            "truth_boundary": self.truth_boundary,
            "consequence_summary": self.consequence_summary,
            "blocked_paths": self.blocked_paths,
            "new_paths": self.new_paths,
            "stopped_paths": self.stopped_paths,
            "affected_surfaces": list(self.affected_surfaces),
            "recommended_commands": list(self.recommended_commands),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishActionPreset:
    command_key: str
    summary: str
    reason: str
    audience_labels: tuple[str, ...]
    channels: tuple[str, ...]
    consequence_hint: str
    recommended: bool = False

    def __post_init__(self) -> None:
        if not self.command_key.strip():
            raise ValueError("command_key must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        if not self.consequence_hint.strip():
            raise ValueError("consequence_hint must not be blank")
        object.__setattr__(self, "audience_labels", _normalize(self.audience_labels, label="audience label"))
        object.__setattr__(self, "channels", _normalize(self.channels, label="channel"))
        if not self.channels:
            raise ValueError("channels must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "command_key": self.command_key,
            "summary": self.summary,
            "reason": self.reason,
            "audience_labels": list(self.audience_labels),
            "channels": list(self.channels),
            "consequence_hint": self.consequence_hint,
            "recommended": self.recommended,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishActionEcho:
    selected_action: str
    summary: str
    action_log: tuple[str, ...]
    opened_bindings: tuple[PublishBinding, ...] = field(default_factory=tuple)
    removed_bindings: tuple[PublishBinding, ...] = field(default_factory=tuple)
    held_bindings: tuple[PublishConflict, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.selected_action.strip():
            raise ValueError("selected_action must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        object.__setattr__(self, "action_log", _normalize(self.action_log, label="action log"))
        object.__setattr__(self, "opened_bindings", tuple(self.opened_bindings))
        object.__setattr__(self, "removed_bindings", tuple(self.removed_bindings))
        object.__setattr__(self, "held_bindings", tuple(self.held_bindings))

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_action": self.selected_action,
            "summary": self.summary,
            "action_log": list(self.action_log),
            "opened_bindings": [binding.to_dict() for binding in self.opened_bindings],
            "removed_bindings": [binding.to_dict() for binding in self.removed_bindings],
            "held_bindings": [binding.to_dict() for binding in self.held_bindings],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishPreviewSurface:
    surface_id: str
    headline: str
    summary: str
    situation_frame: PublishSituationFrame
    queue_surface: ReviewCommandSurface
    selected_card: PriorityStackCard
    selected_candidate: PublishPreviewCandidate
    selected_preview: BlastRadiusPreview
    selected_position: int
    total_items: int
    previous_object_ref: str | None = None
    next_object_ref: str | None = None
    available_commands: tuple[str, ...] = field(default_factory=tuple)
    context_notes: tuple[str, ...] = field(default_factory=tuple)
    action_presets: tuple[PublishActionPreset, ...] = field(default_factory=tuple)
    selected_action: str | None = None
    action_echo: PublishActionEcho | None = None

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if self.selected_position < 0:
            raise ValueError("selected_position must not be negative")
        if self.total_items <= 0:
            raise ValueError("total_items must be positive")
        object.__setattr__(self, "available_commands", _normalize(self.available_commands, label="available command"))
        object.__setattr__(self, "context_notes", _normalize(self.context_notes, label="context note"))
        object.__setattr__(self, "action_presets", tuple(self.action_presets))
        if self.selected_action is not None and not self.selected_action.strip():
            raise ValueError("selected_action must not be blank when provided")
        if not self.available_commands:
            raise ValueError("available_commands must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "situation_frame": self.situation_frame.to_dict(),
            "queue_surface": self.queue_surface.to_dict(),
            "selected_card": self.selected_card.to_dict(),
            "selected_candidate": self.selected_candidate.to_dict(),
            "selected_preview": self.selected_preview.to_dict(),
            "selected_position": self.selected_position,
            "total_items": self.total_items,
            "previous_object_ref": self.previous_object_ref,
            "next_object_ref": self.next_object_ref,
            "available_commands": list(self.available_commands),
            "context_notes": list(self.context_notes),
            "action_presets": [preset.to_dict() for preset in self.action_presets],
            "selected_action": self.selected_action,
            "action_echo": self.action_echo.to_dict() if self.action_echo is not None else None,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PropagationStatusLane:
    status: PropagationStatus
    headline: str
    note: str
    count: int
    surface_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.note.strip():
            raise ValueError("note must not be blank")
        if self.count < 0:
            raise ValueError("count must not be negative")
        object.__setattr__(self, "surface_ids", _normalize(self.surface_ids, label="surface id"))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "headline": self.headline,
            "note": self.note,
            "count": self.count,
            "surface_ids": list(self.surface_ids),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishPropagationSurface:
    surface_id: str
    headline: str
    summary: str
    queue_surface: ReviewCommandSurface
    selected_card: PriorityStackCard
    propagation_ledger: PublishPropagationLedger
    status_lanes: tuple[PropagationStatusLane, ...]
    selected_position: int
    total_items: int
    action_presets: tuple[PublishActionPreset, ...] = field(default_factory=tuple)
    selected_action: str | None = None
    action_echo: PublishActionEcho | None = None
    previous_object_ref: str | None = None
    next_object_ref: str | None = None
    context_notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if self.selected_position < 0:
            raise ValueError("selected_position must not be negative")
        if self.total_items <= 0:
            raise ValueError("total_items must be positive")
        object.__setattr__(self, "status_lanes", tuple(self.status_lanes))
        object.__setattr__(self, "action_presets", tuple(self.action_presets))
        object.__setattr__(self, "context_notes", _normalize(self.context_notes, label="context note"))
        if self.selected_action is not None and not self.selected_action.strip():
            raise ValueError("selected_action must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "queue_surface": self.queue_surface.to_dict(),
            "selected_card": self.selected_card.to_dict(),
            "propagation_ledger": self.propagation_ledger.to_dict(),
            "status_lanes": [lane.to_dict() for lane in self.status_lanes],
            "selected_position": self.selected_position,
            "total_items": self.total_items,
            "action_presets": [preset.to_dict() for preset in self.action_presets],
            "selected_action": self.selected_action,
            "action_echo": self.action_echo.to_dict() if self.action_echo is not None else None,
            "previous_object_ref": self.previous_object_ref,
            "next_object_ref": self.next_object_ref,
            "context_notes": list(self.context_notes),
        }


def get_pressure_intake_publish_preview_surface(
    selected_object_ref: str | None = None,
    *,
    records: Iterable[PressureIntakeRecord] | None = None,
    action_key: str | None = None,
) -> PublishPreviewSurface:
    source_records = tuple(records) if records is not None else sample_pressure_intake_records()
    queue_surface = get_pressure_intake_review_brief_surface(records=source_records)
    queue_cards = queue_surface.priority_stack
    if not queue_cards:
        raise ValueError("publish preview requires at least one review queue card")

    selected_card = _resolve_selected_card(queue_cards, selected_object_ref)
    selected_position = queue_cards.index(selected_card)
    intake_bundles = compile_pressure_intake_bundle(source_records)
    bundle = _require_intake_bundle(intake_bundles, selected_card.object_ref)
    base_candidate = _build_candidate(bundle)
    base_preview = build_publish_blast_radius_preview(base_candidate)
    action_presets = _build_action_presets(bundle=bundle, candidate=base_candidate, preview=base_preview)

    selected_candidate = base_candidate
    selected_preview = base_preview
    action_echo: PublishActionEcho | None = None
    if action_key is not None:
        result = _apply_selected_action(action_key, bundle=bundle, candidate=base_candidate, presets=action_presets)
        selected_candidate = result.updated_candidate
        selected_preview = result.preview
        action_echo = _build_action_echo(action_key, result)

    available_commands = tuple(_normalize((preset.command_key for preset in action_presets), label="available command"))
    situation_frame = _build_situation_frame(bundle=bundle, preview=selected_preview, commands=available_commands)
    return PublishPreviewSurface(
        surface_id="publish-preview",
        headline="Publish becomes blast-radius control before any outward command",
        summary=_build_surface_summary(selected_preview),
        situation_frame=situation_frame,
        queue_surface=queue_surface,
        selected_card=selected_card,
        selected_candidate=selected_candidate,
        selected_preview=selected_preview,
        selected_position=selected_position,
        total_items=len(queue_cards),
        previous_object_ref=queue_cards[selected_position - 1].object_ref if selected_position > 0 else None,
        next_object_ref=queue_cards[selected_position + 1].object_ref if selected_position < len(queue_cards) - 1 else None,
        available_commands=available_commands,
        context_notes=_build_context_notes(
            bundle=bundle,
            preview=selected_preview,
            candidate=selected_candidate,
            action_echo=action_echo,
        ),
        action_presets=action_presets,
        selected_action=action_key,
        action_echo=action_echo,
    )


def get_pressure_intake_publish_propagation_surface(
    selected_object_ref: str | None = None,
    *,
    records: Iterable[PressureIntakeRecord] | None = None,
    action_key: str | None = None,
) -> PublishPropagationSurface:
    source_records = tuple(records) if records is not None else sample_pressure_intake_records()
    queue_surface = get_pressure_intake_review_brief_surface(records=source_records)
    queue_cards = queue_surface.priority_stack
    if not queue_cards:
        raise ValueError("publish propagation surface requires at least one review queue card")

    selected_card = _resolve_selected_card(queue_cards, selected_object_ref)
    selected_position = queue_cards.index(selected_card)
    intake_bundles = compile_pressure_intake_bundle(source_records)
    bundle = _require_intake_bundle(intake_bundles, selected_card.object_ref)
    base_candidate = _build_candidate(bundle)
    base_preview = build_publish_blast_radius_preview(base_candidate)
    action_presets = _build_action_presets(bundle=bundle, candidate=base_candidate, preview=base_preview)
    effective_action = action_key or _default_action_key(action_presets)
    result = _apply_selected_action(effective_action, bundle=bundle, candidate=base_candidate, presets=action_presets)
    action_echo = _build_action_echo(effective_action, result)
    ledger = build_publish_propagation_ledger(
        result,
        surface_updates=_build_propagation_surface_updates(bundle=bundle, result=result),
        supporting_surfaces=_supporting_surface_ids(),
    )
    return PublishPropagationSurface(
        surface_id="publish-propagation",
        headline="Propagation theater turns a publish command into the next governance screen.",
        summary=_build_propagation_summary(ledger),
        queue_surface=queue_surface,
        selected_card=selected_card,
        propagation_ledger=ledger,
        status_lanes=_build_status_lanes(ledger),
        selected_position=selected_position,
        total_items=len(queue_cards),
        action_presets=action_presets,
        selected_action=effective_action,
        action_echo=action_echo,
        previous_object_ref=queue_cards[selected_position - 1].object_ref if selected_position > 0 else None,
        next_object_ref=queue_cards[selected_position + 1].object_ref if selected_position < len(queue_cards) - 1 else None,
        context_notes=_build_propagation_context_notes(bundle=bundle, ledger=ledger, action_echo=action_echo),
    )


def _resolve_selected_card(
    queue_cards: tuple[PriorityStackCard, ...],
    selected_object_ref: str | None,
) -> PriorityStackCard:
    if selected_object_ref is None:
        return queue_cards[0]
    for card in queue_cards:
        if card.object_ref == selected_object_ref:
            return card
    raise ValueError(f"object_ref={selected_object_ref} is not present in the publish queue")


def _require_intake_bundle(
    bundles: tuple[PressureIntakeBundle, ...],
    object_ref: str,
) -> PressureIntakeBundle:
    for bundle in bundles:
        if bundle.proposal.proposal_id == object_ref:
            return bundle
    raise ValueError(f"object_ref={object_ref} is not present in pressure intake")


def _build_candidate(bundle: PressureIntakeBundle) -> PublishPreviewCandidate:
    proposal = bundle.proposal
    signal = bundle.signal
    record = bundle.intake_record
    target_audiences = _target_audiences(record)
    return PublishPreviewCandidate(
        object_id=proposal.proposal_id,
        object_type=proposal.object_type,
        title=proposal.title,
        action_type=_action_type(record.signal_type),
        target_audiences=target_audiences,
        target_channels=signal.affected_surfaces,
        target_bindings=tuple(
            PublishBinding(audience_filter=audience, channel=surface)
            for audience in target_audiences
            for surface in signal.affected_surfaces
        ),
        current_bindings=_current_bindings(record),
        blocked_bindings=_blocked_bindings(record),
    )


def _action_type(signal_type: PressureSignalType) -> PublishActionType:
    return {
        PressureSignalType.TICKET_CLUSTER: PublishActionType.PUBLISH,
        PressureSignalType.HUMAN_REWRITE: PublishActionType.REPUBLISH,
        PressureSignalType.SOURCE_FAILURE: PublishActionType.RESTRICT,
    }[signal_type]


def _current_bindings(record: PressureIntakeRecord) -> tuple[PublishBinding, ...]:
    audience = record.audience_filter
    bindings: list[PublishBinding] = []
    if record.signal_type is PressureSignalType.TICKET_CLUSTER:
        bindings.extend(
            PublishBinding(audience_filter=audience, channel=channel)
            for channel in ("copilot", "macro")
        )
    elif record.signal_type is PressureSignalType.HUMAN_REWRITE:
        bindings.extend(
            PublishBinding(audience_filter=audience, channel=channel)
            for channel in ("copilot", "help_center")
        )
        internal_audience = AudienceFilter(
            visibility=Visibility.INTERNAL,
            brands=audience.brands,
            product_lines=audience.product_lines,
            languages=audience.languages,
            product_versions=audience.product_versions,
        )
        bindings.append(PublishBinding(audience_filter=internal_audience, channel="copilot"))
    else:
        bindings.extend(
            PublishBinding(audience_filter=audience, channel=channel)
            for channel in ("help_center", "copilot", "macro")
        )
    return tuple(bindings)


def _blocked_bindings(record: PressureIntakeRecord) -> tuple[PublishConflict, ...]:
    audience = record.audience_filter
    if record.signal_type is PressureSignalType.HUMAN_REWRITE:
        return (
            PublishConflict(
                audience_filter=audience,
                channel="macro",
                reason="Free-plan refund messaging is still colliding with enterprise-only policy clauses.",
            ),
        )
    if record.signal_type is PressureSignalType.SOURCE_FAILURE:
        return (
            PublishConflict(
                audience_filter=audience,
                channel="help_center",
                reason="Customer-facing incident guidance is source-degraded and must not keep expanding until recovery proof exists.",
            ),
        )
    return ()


def _build_action_presets(
    *,
    bundle: PressureIntakeBundle,
    candidate: PublishPreviewCandidate,
    preview: BlastRadiusPreview,
) -> tuple[PublishActionPreset, ...]:
    presets: list[PublishActionPreset] = []
    audience_labels = tuple(preview.audience_scope.audience_labels)
    channels = candidate.target_channels
    primary_command = _primary_command_key(candidate)
    primary_summary = {
        "publish": "Open the planned support path for the currently selected answer boundary.",
        "republish": "Refresh the governed answer path without widening beyond the selected boundary.",
        "restrict_publish": "Tighten the active publish path before the answer spreads further.",
    }[primary_command]
    primary_hint = {
        "publish": "Use when the object is directionally correct and the main need is to preserve or reopen the current governed path.",
        "republish": "Use when the team needs to refresh the same governed path after rewrite or source repair.",
        "restrict_publish": "Use when the answer should stay live only inside the safer portion of the current governed boundary.",
    }[primary_command]
    presets.append(
        PublishActionPreset(
            command_key=primary_command,
            summary=primary_summary,
            reason="preserve the planned publish path while keeping the current governance scope",
            audience_labels=audience_labels,
            channels=channels,
            consequence_hint=primary_hint,
            recommended=True,
        )
    )
    if primary_command != "restrict_publish":
        presets.append(
            PublishActionPreset(
                command_key="restrict_publish",
                summary="Narrow exposure without discarding the entire object.",
                reason="reduce outward spread while the answer is still under governance repair",
                audience_labels=audience_labels,
                channels=channels,
                consequence_hint="Turns part of the current path into stopped exposure so the team can contain blast radius first.",
            )
        )
    if any(impact.audience_filter.visibility is Visibility.EXTERNAL for impact in preview.impacts):
        presets.append(
            PublishActionPreset(
                command_key="hold_external",
                summary="Pause customer-facing exposure while keeping the object in the governance lane.",
                reason="customer-facing propagation needs a hold while support or policy reviewers finish sign-off",
                audience_labels=tuple(
                    _audience_label(impact.audience_filter)
                    for impact in preview.impacts
                    if impact.audience_filter.visibility is Visibility.EXTERNAL
                ),
                channels=tuple(
                    binding.channel
                    for binding in candidate.target_bindings
                    if binding.audience_filter.visibility is Visibility.EXTERNAL
                ) or channels,
                consequence_hint="Converts external paths into explicit conflicts instead of silently letting them continue.",
            )
        )
    split_audiences = _split_variant_audiences(bundle, candidate)
    if split_audiences:
        presets.append(
            PublishActionPreset(
                command_key="split_variant",
                summary="Open a separately governed audience variant instead of widening the base answer.",
                reason="a narrower rollout variant should be governed separately from the base answer path",
                audience_labels=tuple(_audience_label(audience) for audience in split_audiences),
                channels=(candidate.target_channels[0],),
                consequence_hint="Adds a new governed path so a risky audience can be split out instead of forcing binary approval.",
            )
        )
    if _can_republish_internal_only(candidate):
        presets.append(
            PublishActionPreset(
                command_key="republish_internal_only",
                summary="Keep internal truth live while external paths are withdrawn.",
                reason="internal support guidance must stay live while customer-facing exposure is paused",
                audience_labels=tuple(
                    _audience_label(binding.audience_filter)
                    for binding in (*candidate.target_bindings, *candidate.current_bindings)
                    if binding.audience_filter.visibility is Visibility.INTERNAL
                )
                or audience_labels,
                channels=tuple(
                    binding.channel
                    for binding in (*candidate.target_bindings, *candidate.current_bindings)
                    if binding.audience_filter.visibility is Visibility.INTERNAL
                )
                or channels,
                consequence_hint="Useful when agents still need guidance but external surfaces should stop carrying the answer.",
            )
        )
    return tuple(presets)


def _apply_selected_action(
    action_key: str,
    *,
    bundle: PressureIntakeBundle,
    candidate: PublishPreviewCandidate,
    presets: tuple[PublishActionPreset, ...],
) -> PublishGovernanceResult:
    known_actions = {preset.command_key for preset in presets}
    if action_key not in known_actions:
        raise ValueError(f"action_key={action_key} is not available for this publish surface")

    actions: tuple[PublishGovernanceAction, ...]
    if action_key in {"publish", "republish"}:
        actions = (
            PublishGovernanceAction(
                action_type=PublishGovernanceActionType.PUBLISH,
                reason="keep the currently selected publish path open",
            ),
        )
    elif action_key == "restrict_publish":
        actions = (
            PublishGovernanceAction(
                action_type=PublishGovernanceActionType.RESTRICT,
                audiences=tuple(
                    audience
                    for audience in candidate.target_audiences
                    if audience.visibility is bundle.intake_record.audience_filter.visibility
                )
                or candidate.target_audiences,
                channels=candidate.target_channels,
                reason="contain blast radius while support governance narrows the answer boundary",
            ),
        )
    elif action_key == "hold_external":
        actions = (
            PublishGovernanceAction(
                action_type=PublishGovernanceActionType.HOLD_EXTERNAL,
                channels=tuple(
                    binding.channel
                    for binding in candidate.target_bindings
                    if binding.audience_filter.visibility is Visibility.EXTERNAL
                )
                or candidate.target_channels,
                reason="pause customer-facing propagation until reviewers confirm the boundary is safe",
            ),
        )
    elif action_key == "split_variant":
        audiences = _split_variant_audiences(bundle, candidate)
        if not audiences:
            raise ValueError("split_variant is not available without a derived variant audience")
        actions = (
            PublishGovernanceAction(
                action_type=PublishGovernanceActionType.SPLIT_VARIANT,
                audiences=audiences,
                channels=(candidate.target_channels[0],),
                reason="route the risky audience into a separately governed variant path",
            ),
        )
    elif action_key == "republish_internal_only":
        actions = (
            PublishGovernanceAction(
                action_type=PublishGovernanceActionType.REPUBLISH_INTERNAL_ONLY,
                channels=tuple(
                    binding.channel
                    for binding in candidate.current_bindings
                    if binding.audience_filter.visibility is Visibility.INTERNAL
                )
                or tuple(
                    channel
                    for channel in candidate.target_channels
                ),
                reason="keep internal support truth live while stopping external spread",
            ),
        )
    else:
        raise ValueError(f"unsupported action key: {action_key}")
    return apply_publish_governance_actions(candidate, actions)


def _default_action_key(presets: tuple[PublishActionPreset, ...]) -> str:
    recommended = next((preset.command_key for preset in presets if preset.recommended), None)
    if recommended is not None:
        return recommended
    return presets[0].command_key


def _build_action_echo(action_key: str, result: PublishGovernanceResult) -> PublishActionEcho:
    summary_parts: list[str] = []
    if result.opened_bindings:
        summary_parts.append(f"{len(result.opened_bindings)} path(s) opened")
    if result.removed_bindings:
        summary_parts.append(f"{len(result.removed_bindings)} path(s) withdrawn")
    if result.held_bindings:
        summary_parts.append(f"{len(result.held_bindings)} external path(s) held")
    if not summary_parts:
        summary_parts.append("No path counts changed, but the governance command is now explicit")
    return PublishActionEcho(
        selected_action=action_key,
        summary="; ".join(summary_parts) + ".",
        action_log=result.action_log,
        opened_bindings=result.opened_bindings,
        removed_bindings=result.removed_bindings,
        held_bindings=result.held_bindings,
    )


def _primary_command_key(candidate: PublishPreviewCandidate) -> str:
    if candidate.action_type is PublishActionType.PUBLISH:
        return "publish"
    if candidate.action_type is PublishActionType.REPUBLISH:
        return "republish"
    return "restrict_publish"


def _split_variant_audiences(
    bundle: PressureIntakeBundle,
    candidate: PublishPreviewCandidate,
) -> tuple[AudienceFilter, ...]:
    base_audience = bundle.intake_record.audience_filter
    if base_audience.visibility is not Visibility.EXTERNAL:
        return ()
    variant = AudienceFilter(
        visibility=base_audience.visibility,
        brands=base_audience.brands,
        product_lines=base_audience.product_lines or bundle.intake_record.product_lines,
        plans=("enterprise",) if base_audience.plans != ("enterprise",) else base_audience.plans,
        regions=base_audience.regions or ("eu",),
        languages=base_audience.languages,
        product_versions=base_audience.product_versions,
    )
    existing = {audience for audience in candidate.target_audiences}
    if variant in existing:
        return ()
    return (variant,)


def _can_republish_internal_only(candidate: PublishPreviewCandidate) -> bool:
    bindings = (*candidate.target_bindings, *candidate.current_bindings)
    has_internal = any(binding.audience_filter.visibility is Visibility.INTERNAL for binding in bindings)
    has_external = any(binding.audience_filter.visibility is Visibility.EXTERNAL for binding in bindings)
    return has_internal and has_external


def _build_situation_frame(
    *,
    bundle: PressureIntakeBundle,
    preview: BlastRadiusPreview,
    commands: tuple[str, ...],
) -> PublishSituationFrame:
    impacts = preview.impacts
    blocked_paths = sum(1 for impact in impacts if impact.effect is BlastRadiusEffect.CONFLICT)
    new_paths = sum(1 for impact in impacts if impact.effect is BlastRadiusEffect.NEW_EXPOSURE)
    stopped_paths = sum(1 for impact in impacts if impact.effect is BlastRadiusEffect.STOPPED_EXPOSURE)
    truth_boundary = ", ".join(preview.audience_scope.audience_labels)
    consequence_summary = (
        f"{new_paths} new path(s), {blocked_paths} blocked path(s), and {stopped_paths} path(s) withdrawn "
        "if this command proceeds."
    )
    return PublishSituationFrame(
        briefing_note=bundle.proposal.why_now,
        truth_boundary=truth_boundary,
        consequence_summary=consequence_summary,
        blocked_paths=blocked_paths,
        new_paths=new_paths,
        stopped_paths=stopped_paths,
        affected_surfaces=preview.audience_scope.affected_channels,
        recommended_commands=commands,
    )


def _build_surface_summary(preview: BlastRadiusPreview) -> str:
    external_paths = sum(1 for impact in preview.impacts if impact.audience_filter.visibility is Visibility.EXTERNAL)
    blocked_paths = sum(1 for impact in preview.impacts if impact.effect is BlastRadiusEffect.CONFLICT)
    return (
        f"{external_paths} external path(s) are inside this command boundary; "
        f"{blocked_paths} path(s) already need an explicit gate decision."
    )


def _build_context_notes(
    *,
    bundle: PressureIntakeBundle,
    preview: BlastRadiusPreview,
    candidate: PublishPreviewCandidate,
    action_echo: PublishActionEcho | None,
) -> tuple[str, ...]:
    current_channels = tuple(dict.fromkeys(binding.channel for binding in candidate.current_bindings))
    notes = [
        bundle.proposal.summary,
        f"Current exposure still includes {', '.join(current_channels)}.",
        f"Target audience boundary: {', '.join(preview.audience_scope.audience_labels)}.",
    ]
    if bundle.proposal.audience_notes:
        notes.append(f"Audience note: {bundle.proposal.audience_notes[0]}.")
    if action_echo is not None:
        notes.append(f"Action echo: {action_echo.summary}")
        notes.extend(action_echo.action_log)
    if preview.warnings:
        notes.extend(preview.warnings)
    return tuple(_normalize(notes, label="context note"))


def _supporting_surface_ids() -> tuple[str, ...]:
    return ("review_queue", "queue-sidebar", "feedback", "source_repair", "hold_resolution")


def _build_propagation_surface_updates(
    *,
    bundle: PressureIntakeBundle,
    result: PublishGovernanceResult,
) -> tuple[SurfacePropagationUpdate, ...]:
    updates = [
        SurfacePropagationUpdate(
            surface_id="queue-sidebar",
            status=PropagationStatus.SYNCED,
            reason="The queue-side support workbench has already captured this governance command as the current operator context.",
        )
    ]

    if bundle.intake_record.signal_type is PressureSignalType.SOURCE_FAILURE:
        updates.append(
            SurfacePropagationUpdate(
                surface_id="review_queue",
                status=PropagationStatus.FAILED,
                reason="The review queue remains open because the governing source chain is degraded during an active incident path.",
                follow_up_commands=("open_review", "repair_source_chain", "recheck_propagation"),
            )
        )
        updates.append(
            SurfacePropagationUpdate(
                surface_id="source_repair",
                status=PropagationStatus.FAILED,
                reason="Source repair is still required before this propagation result can be treated as trusted external truth.",
                follow_up_commands=("refresh_sources", "repair_source_chain", "recheck_propagation"),
            )
        )
    elif result.removed_bindings or result.held_bindings:
        updates.append(
            SurfacePropagationUpdate(
                surface_id="review_queue",
                status=PropagationStatus.PENDING,
                reason="The review queue should keep this object visible until narrowed or held paths are confirmed downstream.",
                follow_up_commands=("open_review", "check_propagation_status"),
            )
        )
        updates.append(
            SurfacePropagationUpdate(
                surface_id="source_repair",
                status=PropagationStatus.SYNCED,
                reason="No upstream source repair branch is currently blocking this propagation decision.",
            )
        )
    else:
        updates.append(
            SurfacePropagationUpdate(
                surface_id="review_queue",
                status=PropagationStatus.SYNCED,
                reason="The review queue has absorbed this command without leaving an unresolved rerank or containment branch.",
            )
        )
        updates.append(
            SurfacePropagationUpdate(
                surface_id="source_repair",
                status=PropagationStatus.SYNCED,
                reason="No source-repair branch is required for this propagation command.",
            )
        )

    if result.held_bindings:
        updates.append(
            SurfacePropagationUpdate(
                surface_id="hold_resolution",
                status=PropagationStatus.MANUAL_ACTION_REQUIRED,
                reason="At least one customer-facing path is intentionally held and now needs an explicit human release decision.",
                follow_up_commands=("resolve_surface_hold", "recheck_propagation"),
            )
        )
        updates.append(
            SurfacePropagationUpdate(
                surface_id="feedback",
                status=PropagationStatus.MANUAL_ACTION_REQUIRED,
                reason="Live support sessions should be inspected while held customer-facing paths are prevented from resuming silently.",
                follow_up_commands=("inspect_feedback_sessions", "resolve_surface_hold"),
            )
        )
    elif _has_external_bindings((*result.opened_bindings, *result.removed_bindings)):
        updates.append(
            SurfacePropagationUpdate(
                surface_id="hold_resolution",
                status=PropagationStatus.SYNCED,
                reason="No explicit hold remains after this propagation command.",
            )
        )
        updates.append(
            SurfacePropagationUpdate(
                surface_id="feedback",
                status=PropagationStatus.PENDING,
                reason="Customer-facing path changes should still be watched in live conversations before the command is considered closed.",
                follow_up_commands=("inspect_feedback_sessions", "check_propagation_status"),
            )
        )
    else:
        updates.append(
            SurfacePropagationUpdate(
                surface_id="hold_resolution",
                status=PropagationStatus.SYNCED,
                reason="No hold-resolution branch is open for this command aftermath.",
            )
        )
        updates.append(
            SurfacePropagationUpdate(
                surface_id="feedback",
                status=PropagationStatus.SYNCED,
                reason="This command stays on internal or already-contained surfaces, so no extra live-session watch is required.",
            )
        )

    return tuple(updates)


def _has_external_bindings(bindings: Iterable[PublishBinding]) -> bool:
    return any(binding.audience_filter.visibility is Visibility.EXTERNAL for binding in bindings)


def _build_status_lanes(ledger: PublishPropagationLedger) -> tuple[PropagationStatusLane, ...]:
    lane_meta = {
        PropagationStatus.SYNCED: (
            "Surfaces already reflecting the command",
            "These supporting surfaces or channels have recorded the command aftermath.",
        ),
        PropagationStatus.PENDING: (
            "Surfaces waiting for downstream confirmation",
            "The command has been routed, but confirmation or observation still needs to come back.",
        ),
        PropagationStatus.FAILED: (
            "Surfaces blocked by an upstream failure",
            "These branches are not waiting idly — they are blocked by a broken dependency or degraded source path.",
        ),
        PropagationStatus.MANUAL_ACTION_REQUIRED: (
            "Surfaces paused for explicit human action",
            "These branches require a person to release, inspect, or resolve the path before propagation can close.",
        ),
    }
    lanes: list[PropagationStatusLane] = []
    for status in (
        PropagationStatus.SYNCED,
        PropagationStatus.PENDING,
        PropagationStatus.FAILED,
        PropagationStatus.MANUAL_ACTION_REQUIRED,
    ):
        matching = tuple(record.surface_id for record in ledger.records if record.status is status)
        headline, note = lane_meta[status]
        lanes.append(
            PropagationStatusLane(
                status=status,
                headline=headline,
                note=note,
                count=len(matching),
                surface_ids=matching,
            )
        )
    return tuple(lanes)


def _build_propagation_summary(ledger: PublishPropagationLedger) -> str:
    unresolved = len(ledger.unresolved_surfaces)
    continue_count = len(ledger.continue_commands)
    return (
        f"{ledger.summary.synced} surface(s) have already reflected the command; "
        f"{unresolved} surface(s) remain unresolved, with {continue_count} follow-up command(s) still open."
    )


def _build_propagation_context_notes(
    *,
    bundle: PressureIntakeBundle,
    ledger: PublishPropagationLedger,
    action_echo: PublishActionEcho,
) -> tuple[str, ...]:
    notes = [
        bundle.proposal.summary,
        f"Propagation unresolved surfaces: {', '.join(ledger.unresolved_surfaces) if ledger.unresolved_surfaces else 'none'}.",
        f"Continue commands still open: {', '.join(ledger.continue_commands) if ledger.continue_commands else 'none'}.",
        f"Action echo: {action_echo.summary}",
        *action_echo.action_log,
    ]
    if bundle.proposal.audience_notes:
        notes.append(f"Audience note: {bundle.proposal.audience_notes[0]}.")
    return tuple(_normalize(notes, label="context note"))


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


def _target_audiences(record: PressureIntakeRecord) -> tuple[AudienceFilter, ...]:
    audiences: list[AudienceFilter] = [record.audience_filter]
    if record.signal_type is PressureSignalType.HUMAN_REWRITE:
        audiences.append(
            AudienceFilter(
                visibility=Visibility.INTERNAL,
                brands=record.audience_filter.brands,
                product_lines=record.audience_filter.product_lines or record.product_lines,
                languages=record.audience_filter.languages,
                product_versions=record.audience_filter.product_versions,
            )
        )
    return tuple(dict.fromkeys(audiences))
