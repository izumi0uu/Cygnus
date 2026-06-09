from __future__ import annotations

from dataclasses import dataclass, field
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
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))
        object.__setattr__(self, "recommended_commands", _normalize(self.recommended_commands, label="recommended command"))

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

    def __post_init__(self) -> None:
        if not self.risk_id.strip():
            raise ValueError("risk_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.object_ref.strip():
            raise ValueError("object_ref must not be blank")
        if not self.why_now_summary.strip():
            raise ValueError("why_now_summary must not be blank")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        if not self.primary_command.strip():
            raise ValueError("primary_command must not be blank")
        object.__setattr__(self, "audience_labels", _normalize(self.audience_labels, label="audience label"))
        object.__setattr__(self, "affected_audiences", tuple(self.affected_audiences))
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))
        object.__setattr__(self, "command_actions", _normalize(self.command_actions, label="command action"))
        if not self.affected_audiences:
            raise ValueError("affected_audiences must not be empty")
        if not self.command_actions:
            raise ValueError("command_actions must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_id": self.risk_id,
            "title": self.title,
            "risk_type": self.risk_type.value,
            "urgency": self.urgency.value,
            "object_type": self.object_type.value,
            "object_ref": self.object_ref,
            "why_now_summary": self.why_now_summary,
            "audience_labels": list(self.audience_labels),
            "affected_audiences": [audience.to_dict() for audience in self.affected_audiences],
            "affected_surfaces": list(self.affected_surfaces),
            "owner_state": self.owner_state.value,
            "queue_owner": self.queue_owner,
            "command_actions": list(self.command_actions),
            "primary_command": self.primary_command,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewCommandSurface:
    surface_id: str
    headline: str
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
        object.__setattr__(self, "available_commands", _normalize(self.available_commands, label="available command"))
        if not self.priority_stack:
            raise ValueError("priority_stack must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "situation_frame": self.situation_frame.to_dict(),
            "priority_stack": [card.to_dict() for card in self.priority_stack],
            "available_commands": list(self.available_commands),
            "command_brief": self.command_brief.to_dict() if self.command_brief is not None else None,
        }
