from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


def _normalize_strings(values: Iterable[str] | None, *, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


class FeedbackSignalType(str, Enum):
    COPILOT_ACCEPTED = "copilot_accepted"
    HUMAN_REWRITE = "human_rewrite"
    REJECT_AFTER_SUGGESTION = "reject_after_suggestion"
    ESCALATION_AFTER_SUGGESTION = "escalation_after_suggestion"
    UNRESOLVED_CONVERSATION = "unresolved_conversation"


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceCommandRef:
    command_id: str
    command_type: str
    object_id: str
    object_title: str
    issued_by: str
    issued_at: str
    rationale: str
    affected_surfaces: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")
        if not self.command_type.strip():
            raise ValueError("command_type must not be blank")
        if not self.object_id.strip():
            raise ValueError("object_id must not be blank")
        if not self.object_title.strip():
            raise ValueError("object_title must not be blank")
        if not self.issued_by.strip():
            raise ValueError("issued_by must not be blank")
        if not self.issued_at.strip():
            raise ValueError("issued_at must not be blank")
        if not self.rationale.strip():
            raise ValueError("rationale must not be blank")
        object.__setattr__(
            self,
            "affected_surfaces",
            _normalize_strings(self.affected_surfaces, label="affected surface"),
        )
        if not self.affected_surfaces:
            raise ValueError("affected_surfaces must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "object_id": self.object_id,
            "object_title": self.object_title,
            "issued_by": self.issued_by,
            "issued_at": self.issued_at,
            "rationale": self.rationale,
            "affected_surfaces": list(self.affected_surfaces),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DownstreamFeedbackSignal:
    signal_id: str
    surface_id: str
    signal_type: FeedbackSignalType
    command_ref: GovernanceCommandRef
    audience_label: str
    session_ref: str
    summary: str
    changed_behavior: str
    event_at: str
    queue_owner: str | None = None
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    follow_up_actions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("signal_id must not be blank")
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.audience_label.strip():
            raise ValueError("audience_label must not be blank")
        if not self.session_ref.strip():
            raise ValueError("session_ref must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if not self.changed_behavior.strip():
            raise ValueError("changed_behavior must not be blank")
        if not self.event_at.strip():
            raise ValueError("event_at must not be blank")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        object.__setattr__(self, "source_refs", _normalize_strings(self.source_refs, label="source ref"))
        object.__setattr__(
            self,
            "follow_up_actions",
            _normalize_strings(self.follow_up_actions, label="follow-up action"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "signal_id": self.signal_id,
            "surface_id": self.surface_id,
            "signal_type": self.signal_type.value,
            "command_ref": self.command_ref.to_dict(),
            "audience_label": self.audience_label,
            "session_ref": self.session_ref,
            "summary": self.summary,
            "changed_behavior": self.changed_behavior,
            "event_at": self.event_at,
            "queue_owner": self.queue_owner,
            "source_refs": list(self.source_refs),
            "follow_up_actions": list(self.follow_up_actions),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RealityCheckStrip:
    command_id: str
    command_type: str
    object_title: str
    frontline_changed: bool
    converging_surfaces: tuple[str, ...]
    lagging_surfaces: tuple[str, ...]
    unresolved_signal_count: int
    next_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")
        if not self.command_type.strip():
            raise ValueError("command_type must not be blank")
        if not self.object_title.strip():
            raise ValueError("object_title must not be blank")
        if self.unresolved_signal_count < 0:
            raise ValueError("unresolved_signal_count must not be negative")
        object.__setattr__(
            self,
            "converging_surfaces",
            _normalize_strings(self.converging_surfaces, label="converging surface"),
        )
        object.__setattr__(
            self,
            "lagging_surfaces",
            _normalize_strings(self.lagging_surfaces, label="lagging surface"),
        )
        object.__setattr__(
            self,
            "next_actions",
            _normalize_strings(self.next_actions, label="next action"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "object_title": self.object_title,
            "frontline_changed": self.frontline_changed,
            "converging_surfaces": list(self.converging_surfaces),
            "lagging_surfaces": list(self.lagging_surfaces),
            "unresolved_signal_count": self.unresolved_signal_count,
            "next_actions": list(self.next_actions),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MismatchByAudience:
    audience_label: str
    rewrite_count: int
    reject_count: int
    escalation_count: int
    unresolved_count: int
    affected_surfaces: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.audience_label.strip():
            raise ValueError("audience_label must not be blank")
        for field_name in ("rewrite_count", "reject_count", "escalation_count", "unresolved_count"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")
        object.__setattr__(
            self,
            "affected_surfaces",
            _normalize_strings(self.affected_surfaces, label="affected surface"),
        )
        if not self.affected_surfaces:
            raise ValueError("affected_surfaces must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "audience_label": self.audience_label,
            "rewrite_count": self.rewrite_count,
            "reject_count": self.reject_count,
            "escalation_count": self.escalation_count,
            "unresolved_count": self.unresolved_count,
            "affected_surfaces": list(self.affected_surfaces),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DownstreamRealityCheckSurface:
    surface_id: str
    headline: str
    summary: str
    reality_strip: RealityCheckStrip
    feedback_feed: tuple[DownstreamFeedbackSignal, ...]
    mismatch_by_audience: tuple[MismatchByAudience, ...]
    upstream_object_links: tuple[str, ...]
    send_back_commands: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        object.__setattr__(self, "feedback_feed", tuple(self.feedback_feed))
        object.__setattr__(self, "mismatch_by_audience", tuple(self.mismatch_by_audience))
        object.__setattr__(
            self,
            "upstream_object_links",
            _normalize_strings(self.upstream_object_links, label="upstream object link"),
        )
        object.__setattr__(
            self,
            "send_back_commands",
            _normalize_strings(self.send_back_commands, label="send-back command"),
        )
        if not self.feedback_feed:
            raise ValueError("feedback_feed must not be empty")
        if not self.mismatch_by_audience:
            raise ValueError("mismatch_by_audience must not be empty")
        if not self.send_back_commands:
            raise ValueError("send_back_commands must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "reality_check_strip": self.reality_strip.to_dict(),
            "feedback_feed": [signal.to_dict() for signal in self.feedback_feed],
            "mismatch_by_audience": [item.to_dict() for item in self.mismatch_by_audience],
            "upstream_object_links": list(self.upstream_object_links),
            "send_back_commands": list(self.send_back_commands),
        }


def build_downstream_reality_check_surface(
    *,
    command_ref: GovernanceCommandRef,
    feedback_feed: Iterable[DownstreamFeedbackSignal],
) -> DownstreamRealityCheckSurface:
    ordered_feed = tuple(
        sorted(
            _select_command_feedback(command_ref=command_ref, feedback_feed=feedback_feed),
            key=lambda signal: (signal.event_at, signal.signal_id),
            reverse=True,
        )
    )
    if not ordered_feed:
        raise ValueError("downstream reality check requires at least one feedback signal for the command")

    converging_surfaces = tuple(
        _dedupe(
            signal.surface_id
            for signal in ordered_feed
            if signal.signal_type is FeedbackSignalType.COPILOT_ACCEPTED
        )
    )
    lagging_surfaces = tuple(
        _dedupe(
            signal.surface_id
            for signal in ordered_feed
            if signal.signal_type is not FeedbackSignalType.COPILOT_ACCEPTED
        )
    )
    unresolved_count = sum(
        1
        for signal in ordered_feed
        if signal.signal_type
        in {
            FeedbackSignalType.HUMAN_REWRITE,
            FeedbackSignalType.REJECT_AFTER_SUGGESTION,
            FeedbackSignalType.ESCALATION_AFTER_SUGGESTION,
            FeedbackSignalType.UNRESOLVED_CONVERSATION,
        }
    )
    strip = RealityCheckStrip(
        command_id=command_ref.command_id,
        command_type=command_ref.command_type,
        object_title=command_ref.object_title,
        frontline_changed=bool(converging_surfaces),
        converging_surfaces=converging_surfaces,
        lagging_surfaces=lagging_surfaces,
        unresolved_signal_count=unresolved_count,
        next_actions=_dedupe(
            action for signal in ordered_feed for action in signal.follow_up_actions
        ),
    )
    mismatch_by_audience = tuple(_build_mismatch_by_audience(ordered_feed))
    upstream_links = (
        f"object:{command_ref.object_id}",
        f"command:{command_ref.command_id}",
    )
    send_back_commands = _dedupe(
        (
            "open_recovery_window",
            "return_to_command_brief",
            *(action for signal in ordered_feed for action in signal.follow_up_actions),
        )
    )
    return DownstreamRealityCheckSurface(
        surface_id="downstream-reality-check",
        headline="Downstream reality check",
        summary=_build_surface_summary(
            command_ref=command_ref,
            converging_surfaces=converging_surfaces,
            lagging_surfaces=lagging_surfaces,
            unresolved_count=unresolved_count,
        ),
        reality_strip=strip,
        feedback_feed=ordered_feed,
        mismatch_by_audience=mismatch_by_audience,
        upstream_object_links=upstream_links,
        send_back_commands=send_back_commands,
    )


def _select_command_feedback(
    *,
    command_ref: GovernanceCommandRef,
    feedback_feed: Iterable[DownstreamFeedbackSignal],
) -> tuple[DownstreamFeedbackSignal, ...]:
    return tuple(
        signal
        for signal in feedback_feed
        if signal.command_ref.command_id == command_ref.command_id
    )


def _build_mismatch_by_audience(
    feedback_feed: tuple[DownstreamFeedbackSignal, ...],
) -> list[MismatchByAudience]:
    buckets: dict[str, dict[str, object]] = {}
    for signal in feedback_feed:
        bucket = buckets.setdefault(
            signal.audience_label,
            {
                "rewrite_count": 0,
                "reject_count": 0,
                "escalation_count": 0,
                "unresolved_count": 0,
                "affected_surfaces": [],
            },
        )
        if signal.signal_type is FeedbackSignalType.HUMAN_REWRITE:
            bucket["rewrite_count"] += 1
        elif signal.signal_type is FeedbackSignalType.REJECT_AFTER_SUGGESTION:
            bucket["reject_count"] += 1
        elif signal.signal_type is FeedbackSignalType.ESCALATION_AFTER_SUGGESTION:
            bucket["escalation_count"] += 1
        elif signal.signal_type is FeedbackSignalType.UNRESOLVED_CONVERSATION:
            bucket["unresolved_count"] += 1
        surfaces: list[str] = bucket["affected_surfaces"]  # type: ignore[assignment]
        if signal.surface_id not in surfaces:
            surfaces.append(signal.surface_id)

    results = [
        MismatchByAudience(
            audience_label=audience_label,
            rewrite_count=int(data["rewrite_count"]),
            reject_count=int(data["reject_count"]),
            escalation_count=int(data["escalation_count"]),
            unresolved_count=int(data["unresolved_count"]),
            affected_surfaces=tuple(data["affected_surfaces"]),  # type: ignore[arg-type]
        )
        for audience_label, data in sorted(buckets.items())
    ]
    return sorted(
        results,
        key=lambda item: (
            -(item.rewrite_count + item.reject_count + item.escalation_count + item.unresolved_count),
            item.audience_label,
        ),
    )


def _build_surface_summary(
    *,
    command_ref: GovernanceCommandRef,
    converging_surfaces: tuple[str, ...],
    lagging_surfaces: tuple[str, ...],
    unresolved_count: int,
) -> str:
    changed_clause = (
        f"{len(converging_surfaces)} surface(s) are already reflecting the governance command"
        if converging_surfaces
        else "no supporting surface has confirmed frontline change yet"
    )
    lagging_clause = (
        f"{len(lagging_surfaces)} surface(s) still show rewrite / reject / escalation pressure"
        if lagging_surfaces
        else "no lagging surface has been detected"
    )
    return (
        f"{command_ref.command_type} on {command_ref.object_title} is now being verified downstream; "
        f"{changed_clause}, {lagging_clause}, and {unresolved_count} unresolved frontline signal(s) remain."
    )


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError("deduped value must not be blank")
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return tuple(normalized)
