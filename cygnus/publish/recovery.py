from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.publish.propagation import PublishPropagationLedger, SurfacePropagationRecord
from cygnus.publish.surface import (
    PublishActionEcho,
    PublishActionPreset,
    PublishPropagationSurface,
    get_pressure_intake_publish_propagation_surface,
)
from cygnus.review.intake import (
    PressureIntakeBundle,
    PressureIntakeRecord,
    PressureSignalType,
    compile_pressure_intake_bundle,
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


class RecoverySignalStatus(str, Enum):
    CONFIRMED = "confirmed"
    WATCHING = "watching"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"


class RecoveryBehaviorType(str, Enum):
    ACCEPTED_PATH = "accepted_path"
    REWRITE_PRESSURE = "rewrite_pressure"
    ESCALATION_PRESSURE = "escalation_pressure"
    STALE_PATH_REPLAY = "stale_path_replay"
    SOURCE_FALLBACK = "source_fallback"
    HOLD_LINE = "hold_line"


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverySignal:
    signal_id: str
    surface_id: str
    behavior_type: RecoveryBehaviorType
    status: RecoverySignalStatus
    headline: str
    evidence_note: str
    affected_audience_labels: tuple[str, ...] = field(default_factory=tuple)
    follow_up_commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("signal_id must not be blank")
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.evidence_note.strip():
            raise ValueError("evidence_note must not be blank")
        object.__setattr__(
            self,
            "affected_audience_labels",
            _normalize(self.affected_audience_labels, label="affected audience label"),
        )
        object.__setattr__(
            self,
            "follow_up_commands",
            _normalize(self.follow_up_commands, label="follow-up command"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "signal_id": self.signal_id,
            "surface_id": self.surface_id,
            "behavior_type": self.behavior_type.value,
            "status": self.status.value,
            "headline": self.headline,
            "evidence_note": self.evidence_note,
            "affected_audience_labels": list(self.affected_audience_labels),
            "follow_up_commands": list(self.follow_up_commands),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryProofWindow:
    verdict: str
    operator_note: str
    confirmed: int = 0
    watching: int = 0
    at_risk: int = 0
    blocked: int = 0

    def __post_init__(self) -> None:
        if not self.verdict.strip():
            raise ValueError("verdict must not be blank")
        if not self.operator_note.strip():
            raise ValueError("operator_note must not be blank")
        for field_name in ("confirmed", "watching", "at_risk", "blocked"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "operator_note": self.operator_note,
            "confirmed": self.confirmed,
            "watching": self.watching,
            "at_risk": self.at_risk,
            "blocked": self.blocked,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryProofSurface:
    surface_id: str
    headline: str
    summary: str
    queue_surface: ReviewCommandSurface
    selected_card: PriorityStackCard
    propagation_ledger: PublishPropagationLedger
    recovery_window: RecoveryProofWindow
    signals: tuple[RecoverySignal, ...]
    continue_commands: tuple[str, ...] = field(default_factory=tuple)
    action_presets: tuple[PublishActionPreset, ...] = field(default_factory=tuple)
    selected_action: str | None = None
    action_echo: PublishActionEcho | None = None
    selected_position: int = 0
    total_items: int = 0
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
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(self, "continue_commands", _normalize(self.continue_commands, label="continue command"))
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
            "recovery_window": self.recovery_window.to_dict(),
            "signals": [signal.to_dict() for signal in self.signals],
            "continue_commands": list(self.continue_commands),
            "action_presets": [preset.to_dict() for preset in self.action_presets],
            "selected_action": self.selected_action,
            "action_echo": self.action_echo.to_dict() if self.action_echo is not None else None,
            "selected_position": self.selected_position,
            "total_items": self.total_items,
            "previous_object_ref": self.previous_object_ref,
            "next_object_ref": self.next_object_ref,
            "context_notes": list(self.context_notes),
        }


def get_pressure_intake_recovery_proof_surface(
    selected_object_ref: str | None = None,
    *,
    records: Iterable[PressureIntakeRecord] | None = None,
    action_key: str | None = None,
) -> RecoveryProofSurface:
    source_records = tuple(records) if records is not None else sample_pressure_intake_records()
    propagation_surface = get_pressure_intake_publish_propagation_surface(
        selected_object_ref,
        records=source_records,
        action_key=action_key,
    )
    bundle = _require_bundle(source_records, propagation_surface.selected_card.object_ref)
    signals = _build_recovery_signals(bundle=bundle, propagation_surface=propagation_surface)
    continue_commands = _normalize(
        (
            *propagation_surface.propagation_ledger.continue_commands,
            *(command for signal in signals for command in signal.follow_up_commands),
        ),
        label="continue command",
    )
    return RecoveryProofSurface(
        surface_id="recovery-proof",
        headline="Recovery proof keeps the command center accountable to frontline behavior.",
        summary=_build_surface_summary(signals),
        queue_surface=propagation_surface.queue_surface,
        selected_card=propagation_surface.selected_card,
        propagation_ledger=propagation_surface.propagation_ledger,
        recovery_window=_build_recovery_window(signals),
        signals=signals,
        continue_commands=continue_commands,
        action_presets=propagation_surface.action_presets,
        selected_action=propagation_surface.selected_action,
        action_echo=propagation_surface.action_echo,
        selected_position=propagation_surface.selected_position,
        total_items=propagation_surface.total_items,
        previous_object_ref=propagation_surface.previous_object_ref,
        next_object_ref=propagation_surface.next_object_ref,
        context_notes=_build_context_notes(bundle=bundle, propagation_surface=propagation_surface, signals=signals),
    )


def _require_bundle(
    records: tuple[PressureIntakeRecord, ...],
    object_ref: str,
) -> PressureIntakeBundle:
    for bundle in compile_pressure_intake_bundle(records):
        if bundle.proposal.proposal_id == object_ref:
            return bundle
    raise ValueError(f"object_ref={object_ref} is not present in pressure intake")


def _build_recovery_signals(
    *,
    bundle: PressureIntakeBundle,
    propagation_surface: PublishPropagationSurface,
) -> tuple[RecoverySignal, ...]:
    record_map = {
        record.surface_id: record
        for record in propagation_surface.propagation_ledger.records
    }
    audience_labels = propagation_surface.selected_card.audience_labels
    if bundle.intake_record.signal_type is PressureSignalType.HUMAN_REWRITE:
        return (
            _signal_from_record(
                record_map,
                surface_id="copilot",
                signal_id="copilot-accepted",
                behavior_type=RecoveryBehaviorType.ACCEPTED_PATH,
                default_status=RecoverySignalStatus.CONFIRMED,
                headline="Agent-facing guidance is now carrying the governed refund boundary first.",
                evidence_note="Copilot should stop leaking enterprise-only refund clauses into the free-plan path after this command.",
                affected_audience_labels=audience_labels,
                follow_up_commands=("check_propagation_status",),
            ),
            _signal_from_record(
                record_map,
                surface_id="macro",
                signal_id="macro-rewrite-pressure",
                behavior_type=RecoveryBehaviorType.REWRITE_PRESSURE,
                default_status=RecoverySignalStatus.WATCHING,
                headline="Frontline rewrite pressure still needs to cool before the policy correction is trusted.",
                evidence_note="Macros and hand-crafted replies are where old plan-boundary language tends to replay first.",
                affected_audience_labels=audience_labels,
                follow_up_commands=("inspect_feedback_sessions", "open_review"),
            ),
            _signal_from_record(
                record_map,
                surface_id="feedback",
                signal_id="feedback-hold-line",
                behavior_type=RecoveryBehaviorType.HOLD_LINE,
                default_status=RecoverySignalStatus.AT_RISK,
                headline="Live session feedback is the first proof of whether the hold or narrower path is being respected.",
                evidence_note="If rewrites or agent overrides continue here, the policy boundary still has not fully converged.",
                affected_audience_labels=audience_labels,
                follow_up_commands=("inspect_feedback_sessions", "resolve_surface_hold"),
            ),
        )

    if bundle.intake_record.signal_type is PressureSignalType.SOURCE_FAILURE:
        return (
            _signal_from_record(
                record_map,
                surface_id="help_center",
                signal_id="help-center-stale-replay",
                behavior_type=RecoveryBehaviorType.STALE_PATH_REPLAY,
                default_status=RecoverySignalStatus.BLOCKED,
                headline="Customer-facing workaround paths can still replay stale guidance while the source chain is degraded.",
                evidence_note="This is the clearest place to catch whether old incident wording remains live after the restriction command.",
                affected_audience_labels=audience_labels,
                follow_up_commands=("repair_source_chain", "open_review"),
            ),
            _signal_from_record(
                record_map,
                surface_id="source_repair",
                signal_id="source-repair-fallback",
                behavior_type=RecoveryBehaviorType.SOURCE_FALLBACK,
                default_status=RecoverySignalStatus.BLOCKED,
                headline="Recovery cannot be proved until the missing incident source path is repaired.",
                evidence_note="The control layer can narrow propagation, but it cannot declare success while source truth is still missing.",
                affected_audience_labels=audience_labels,
                follow_up_commands=("refresh_sources", "repair_source_chain"),
            ),
            _signal_from_record(
                record_map,
                surface_id="review_queue",
                signal_id="review-queue-escalation",
                behavior_type=RecoveryBehaviorType.ESCALATION_PRESSURE,
                default_status=RecoverySignalStatus.AT_RISK,
                headline="The review lane should remain escalated until the incident workaround is grounded again.",
                evidence_note="If the queue keeps this item hot, the system is correctly acknowledging unresolved incident risk.",
                affected_audience_labels=audience_labels,
                follow_up_commands=("open_review", "repair_source_chain"),
            ),
        )

    return (
        _signal_from_record(
            record_map,
            surface_id="copilot",
            signal_id="copilot-accepted",
            behavior_type=RecoveryBehaviorType.ACCEPTED_PATH,
            default_status=RecoverySignalStatus.CONFIRMED,
            headline="Copilot should now serve the governed troubleshooting path instead of reconstructing it from memory.",
            evidence_note="This is the first place to confirm the new troubleshooting flow is replacing ad hoc agent recall.",
            affected_audience_labels=audience_labels,
            follow_up_commands=("check_propagation_status",),
        ),
        _signal_from_record(
            record_map,
            surface_id="queue-sidebar",
            signal_id="queue-sidebar-escalation",
            behavior_type=RecoveryBehaviorType.ESCALATION_PRESSURE,
            default_status=RecoverySignalStatus.WATCHING,
            headline="Escalation pressure should fall if the queue sidebar starts carrying the governed flow instead of repeated workaround fragments.",
            evidence_note="If escalations still cluster here, the new troubleshooting object has not yet become operational truth.",
            affected_audience_labels=audience_labels,
            follow_up_commands=("open_review", "assign_owner"),
        ),
        _signal_from_record(
            record_map,
            surface_id="feedback",
            signal_id="feedback-rewrite-watch",
            behavior_type=RecoveryBehaviorType.REWRITE_PRESSURE,
            default_status=RecoverySignalStatus.WATCHING,
            headline="Frontline sessions still need watching until the repeated verification workaround stops being rewritten by hand.",
            evidence_note="This signal is the mirror of whether the new troubleshooting flow is actually lowering support effort.",
            affected_audience_labels=audience_labels,
            follow_up_commands=("inspect_feedback_sessions", "check_propagation_status"),
        ),
    )


def _signal_from_record(
    record_map: dict[str, SurfacePropagationRecord],
    *,
    surface_id: str,
    signal_id: str,
    behavior_type: RecoveryBehaviorType,
    default_status: RecoverySignalStatus,
    headline: str,
    evidence_note: str,
    affected_audience_labels: tuple[str, ...],
    follow_up_commands: tuple[str, ...],
) -> RecoverySignal:
    record = record_map.get(surface_id)
    status = _status_from_propagation_record(record, default=default_status)
    return RecoverySignal(
        signal_id=signal_id,
        surface_id=surface_id,
        behavior_type=behavior_type,
        status=status,
        headline=headline,
        evidence_note=(f"{evidence_note} {record.reason}" if record is not None else evidence_note),
        affected_audience_labels=affected_audience_labels,
        follow_up_commands=record.follow_up_commands if record is not None and record.follow_up_commands else follow_up_commands,
    )


def _status_from_propagation_record(
    record: SurfacePropagationRecord | None,
    *,
    default: RecoverySignalStatus,
) -> RecoverySignalStatus:
    if record is None:
        return default
    match record.status.value:
        case "synced":
            return RecoverySignalStatus.CONFIRMED
        case "pending":
            return RecoverySignalStatus.WATCHING
        case "failed":
            return RecoverySignalStatus.BLOCKED
        case "manual_action_required":
            return RecoverySignalStatus.AT_RISK
    return default


def _build_recovery_window(signals: tuple[RecoverySignal, ...]) -> RecoveryProofWindow:
    counts = {
        RecoverySignalStatus.CONFIRMED: sum(1 for signal in signals if signal.status is RecoverySignalStatus.CONFIRMED),
        RecoverySignalStatus.WATCHING: sum(1 for signal in signals if signal.status is RecoverySignalStatus.WATCHING),
        RecoverySignalStatus.AT_RISK: sum(1 for signal in signals if signal.status is RecoverySignalStatus.AT_RISK),
        RecoverySignalStatus.BLOCKED: sum(1 for signal in signals if signal.status is RecoverySignalStatus.BLOCKED),
    }
    if counts[RecoverySignalStatus.BLOCKED] > 0:
        verdict = "Recovery is blocked by at least one frontline surface that still cannot reflect trusted truth."
        operator_note = "Do not treat this command as resolved yet; a blocked surface still prevents confidence in the new system state."
    elif counts[RecoverySignalStatus.AT_RISK] > 0:
        verdict = "Recovery is directionally improving, but one or more frontline branches can still drift or replay the old path."
        operator_note = "The command changed the system, but human follow-through is still required before the state can be called stable."
    elif counts[RecoverySignalStatus.WATCHING] > 0:
        verdict = "Recovery is moving in the right direction, but downstream observation is still required."
        operator_note = "Use this window to decide whether to keep observing or close the command loop."
    else:
        verdict = "Recovery is currently reflected across the selected frontline mirrors."
        operator_note = "The most visible branches appear aligned with the new governance state."
    return RecoveryProofWindow(
        verdict=verdict,
        operator_note=operator_note,
        confirmed=counts[RecoverySignalStatus.CONFIRMED],
        watching=counts[RecoverySignalStatus.WATCHING],
        at_risk=counts[RecoverySignalStatus.AT_RISK],
        blocked=counts[RecoverySignalStatus.BLOCKED],
    )


def _build_surface_summary(signals: tuple[RecoverySignal, ...]) -> str:
    confirmed = sum(1 for signal in signals if signal.status is RecoverySignalStatus.CONFIRMED)
    unresolved = sum(
        1
        for signal in signals
        if signal.status in (RecoverySignalStatus.WATCHING, RecoverySignalStatus.AT_RISK, RecoverySignalStatus.BLOCKED)
    )
    return (
        f"{confirmed} frontline signal(s) already reflect the command; "
        f"{unresolved} signal(s) still require observation, human action, or upstream repair."
    )


def _build_context_notes(
    *,
    bundle: PressureIntakeBundle,
    propagation_surface: PublishPropagationSurface,
    signals: tuple[RecoverySignal, ...],
) -> tuple[str, ...]:
    at_risk = [signal.surface_id for signal in signals if signal.status in (RecoverySignalStatus.AT_RISK, RecoverySignalStatus.BLOCKED)]
    notes = [
        bundle.proposal.summary,
        f"Command under review: {propagation_surface.selected_action or 'none'}.",
        f"Frontline surfaces still unresolved: {', '.join(at_risk) if at_risk else 'none'}.",
        f"Propagation unresolved surfaces: {', '.join(propagation_surface.propagation_ledger.unresolved_surfaces) if propagation_surface.propagation_ledger.unresolved_surfaces else 'none'}.",
    ]
    if propagation_surface.action_echo is not None:
        notes.append(f"Action echo: {propagation_surface.action_echo.summary}")
    if bundle.proposal.audience_notes:
        notes.append(f"Audience note: {bundle.proposal.audience_notes[0]}.")
    return tuple(note for note in _normalize(notes, label="context note") if note)
