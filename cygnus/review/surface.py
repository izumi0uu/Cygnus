from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.review.briefing import OwnerState, ReviewCommandBrief, ReviewRiskType
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


class ObservationState(str, Enum):
    READY = "ready"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceObservation:
    state: ObservationState
    observed_count: int
    reason: str
    covered_signals: tuple[str, ...] = field(default_factory=tuple)
    missing_signals: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        if self.observed_count < 0:
            raise ValueError("observed_count must not be negative")

        covered_signals = tuple(
            dict.fromkeys(_normalize(self.covered_signals, label="covered signal"))
        )
        missing_signals = tuple(
            dict.fromkeys(_normalize(self.missing_signals, label="missing signal"))
        )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "covered_signals", covered_signals)
        object.__setattr__(self, "missing_signals", missing_signals)

        if self.state is ObservationState.READY:
            if not covered_signals or missing_signals:
                raise ValueError(
                    "ready observation requires covered signals and no missing signals"
                )
            return
        if self.state is ObservationState.PARTIAL:
            if not covered_signals or not missing_signals:
                raise ValueError(
                    "partial observation requires covered and missing signals"
                )
            return
        if covered_signals or not missing_signals or self.observed_count != 0:
            raise ValueError(
                "unavailable observation requires zero observations, no covered signals, and missing signals"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "observed_count": self.observed_count,
            "reason": self.reason,
            "covered_signals": list(self.covered_signals),
            "missing_signals": list(self.missing_signals),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SituationFrame:
    briefing_note: str
    summary: str
    primary_tension: str
    urgent_items: int
    owner_gaps: int
    affected_surfaces: tuple[str, ...]
    recommended_commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.briefing_note.strip():
            raise ValueError("briefing_note must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if not self.primary_tension.strip():
            raise ValueError("primary_tension must not be blank")
        if self.urgent_items < 0:
            raise ValueError("urgent_items must not be negative")
        if self.owner_gaps < 0:
            raise ValueError("owner_gaps must not be negative")
        object.__setattr__(
            self,
            "affected_surfaces",
            _normalize(self.affected_surfaces, label="affected surface"),
        )
        object.__setattr__(
            self,
            "recommended_commands",
            _normalize(self.recommended_commands, label="recommended command"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "briefing_note": self.briefing_note,
            "summary": self.summary,
            "primary_tension": self.primary_tension,
            "urgent_items": self.urgent_items,
            "owner_gaps": self.owner_gaps,
            "affected_surfaces": list(self.affected_surfaces),
            "recommended_commands": list(self.recommended_commands),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PriorityStackCard:
    risk_id: str
    signal_ref: str
    title: str
    risk_type: ReviewRiskType
    urgency: UrgencyLevel
    object_type: KnowledgeObjectType
    object_ref: str
    why_now_summary: str
    audience_labels: tuple[str, ...]
    affected_audiences: tuple[AudienceFilter, ...]
    affected_surfaces: tuple[str, ...]
    owner_state: OwnerState
    queue_owner: str | None
    command_actions: tuple[str, ...]
    primary_command: str
    assignment_trace_ref: str | None = None
    assignment_version: int | None = None

    def __post_init__(self) -> None:
        if not self.risk_id.strip():
            raise ValueError("risk_id must not be blank")
        if not self.signal_ref.strip():
            raise ValueError("signal_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.object_ref.strip():
            raise ValueError("object_ref must not be blank")
        if not self.why_now_summary.strip():
            raise ValueError("why_now_summary must not be blank")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        if (self.assignment_trace_ref is None) != (self.assignment_version is None):
            raise ValueError("assignment trace and version must be provided together")
        if (
            self.assignment_trace_ref is not None
            and not self.assignment_trace_ref.strip()
        ):
            raise ValueError("assignment_trace_ref must not be blank when provided")
        if self.assignment_version is not None and self.assignment_version < 1:
            raise ValueError("assignment_version must be at least 1")
        if not self.primary_command.strip():
            raise ValueError("primary_command must not be blank")
        object.__setattr__(
            self,
            "audience_labels",
            _normalize(self.audience_labels, label="audience label"),
        )
        object.__setattr__(self, "affected_audiences", tuple(self.affected_audiences))
        object.__setattr__(
            self,
            "affected_surfaces",
            _normalize(self.affected_surfaces, label="affected surface"),
        )
        object.__setattr__(
            self,
            "command_actions",
            _normalize(self.command_actions, label="command action"),
        )
        if not self.affected_audiences:
            raise ValueError("affected_audiences must not be empty")
        if not self.command_actions:
            raise ValueError("command_actions must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_id": self.risk_id,
            "signal_ref": self.signal_ref,
            "title": self.title,
            "risk_type": self.risk_type.value,
            "urgency": self.urgency.value,
            "object_type": self.object_type.value,
            "object_ref": self.object_ref,
            "why_now_summary": self.why_now_summary,
            "audience_labels": list(self.audience_labels),
            "affected_audiences": [
                audience.to_dict() for audience in self.affected_audiences
            ],
            "affected_surfaces": list(self.affected_surfaces),
            "owner_state": self.owner_state.value,
            "queue_owner": self.queue_owner,
            "command_actions": list(self.command_actions),
            "primary_command": self.primary_command,
            "assignment_trace_ref": self.assignment_trace_ref,
            "assignment_version": self.assignment_version,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewCommandSurface:
    surface_id: str
    headline: str
    observation: SurfaceObservation
    situation_frame: SituationFrame
    priority_stack: tuple[PriorityStackCard, ...]
    available_commands: tuple[str, ...] = field(default_factory=tuple)
    command_brief: ReviewCommandBrief | None = None

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        object.__setattr__(self, "priority_stack", tuple(self.priority_stack))
        object.__setattr__(
            self,
            "available_commands",
            _normalize(self.available_commands, label="available command"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "observation": self.observation.to_dict(),
            "situation_frame": self.situation_frame.to_dict(),
            "priority_stack": [card.to_dict() for card in self.priority_stack],
            "available_commands": list(self.available_commands),
            "command_brief": self.command_brief.to_dict()
            if self.command_brief is not None
            else None,
        }
