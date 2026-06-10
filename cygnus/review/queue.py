from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.review.briefing import OwnerState, ReviewRiskType
from cygnus.review.home import ReviewHomeQuery, get_review_home_surface
from cygnus.review.surface import PriorityStackCard, ReviewCommandSurface
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


class QueueCommandType(str, Enum):
    RESTACK = "restack"
    REROUTE = "reroute"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True, kw_only=True)
class UpstreamCommandTrace:
    source_risk_id: str
    source_risk_type: ReviewRiskType
    command_origin_tag: str
    command_history: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.source_risk_id.strip():
            raise ValueError("source_risk_id must not be blank")
        if not self.command_origin_tag.strip():
            raise ValueError("command_origin_tag must not be blank")
        object.__setattr__(self, "command_history", _normalize(self.command_history, label="command history"))

    def append(self, value: str) -> "UpstreamCommandTrace":
        return UpstreamCommandTrace(
            source_risk_id=self.source_risk_id,
            source_risk_type=self.source_risk_type,
            command_origin_tag=self.command_origin_tag,
            command_history=(*self.command_history, value),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_risk_id": self.source_risk_id,
            "source_risk_type": self.source_risk_type.value,
            "command_origin_tag": self.command_origin_tag,
            "command_history": list(self.command_history),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class QueueDependencyState:
    impacted_surfaces: tuple[str, ...]
    waiting_on_refs: tuple[str, ...] = field(default_factory=tuple)
    waiting_summary: str = "Ready for direct action."

    def __post_init__(self) -> None:
        object.__setattr__(self, "impacted_surfaces", _normalize(self.impacted_surfaces, label="impacted surface"))
        object.__setattr__(self, "waiting_on_refs", _normalize(self.waiting_on_refs, label="waiting ref"))
        if not self.waiting_summary.strip():
            raise ValueError("waiting_summary must not be blank")

    def to_dict(self) -> dict[str, object]:
        return {
            "impacted_surfaces": list(self.impacted_surfaces),
            "waiting_on_refs": list(self.waiting_on_refs),
            "waiting_summary": self.waiting_summary,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewQueueEntry:
    object_ref: str
    title: str
    queue_position: int
    urgency: UrgencyLevel
    risk_type: ReviewRiskType
    owner_state: OwnerState
    queue_owner: str | None
    command_actions: tuple[str, ...]
    upstream_trace: UpstreamCommandTrace
    dependency_state: QueueDependencyState

    def __post_init__(self) -> None:
        if not self.object_ref.strip():
            raise ValueError("object_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if self.queue_position < 0:
            raise ValueError("queue_position must not be negative")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        object.__setattr__(self, "command_actions", _normalize(self.command_actions, label="command action"))
        if not self.command_actions:
            raise ValueError("command_actions must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "object_ref": self.object_ref,
            "title": self.title,
            "queue_position": self.queue_position,
            "urgency": self.urgency.value,
            "risk_type": self.risk_type.value,
            "owner_state": self.owner_state.value,
            "queue_owner": self.queue_owner,
            "command_actions": list(self.command_actions),
            "upstream_trace": self.upstream_trace.to_dict(),
            "dependency_state": self.dependency_state.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewQueueSurface:
    queue_id: str
    headline: str
    entries: tuple[ReviewQueueEntry, ...]
    restack_lane: tuple[str, ...]
    available_bulk_commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.queue_id.strip():
            raise ValueError("queue_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "restack_lane", _normalize(self.restack_lane, label="restack lane ref"))
        object.__setattr__(self, "available_bulk_commands", _normalize(self.available_bulk_commands, label="bulk command"))
        if not self.entries:
            raise ValueError("entries must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "queue_id": self.queue_id,
            "headline": self.headline,
            "entries": [entry.to_dict() for entry in self.entries],
            "restack_lane": list(self.restack_lane),
            "available_bulk_commands": list(self.available_bulk_commands),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class QueueCommand:
    command_type: QueueCommandType
    object_ref: str | None = None
    ordered_refs: tuple[str, ...] = field(default_factory=tuple)
    new_owner: str | None = None
    reason: str

    def __post_init__(self) -> None:
        if self.object_ref is not None and not self.object_ref.strip():
            raise ValueError("object_ref must not be blank when provided")
        object.__setattr__(self, "ordered_refs", _normalize(self.ordered_refs, label="ordered ref"))
        if self.new_owner is not None and not self.new_owner.strip():
            raise ValueError("new_owner must not be blank when provided")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class QueueMutationResult:
    queue_surface: ReviewQueueSurface
    touched_refs: tuple[str, ...]
    owner_echo: tuple[dict[str, str | None], ...]
    waiting_echo: tuple[dict[str, object], ...]
    command_log: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "touched_refs", _normalize(self.touched_refs, label="touched ref"))
        object.__setattr__(self, "command_log", _normalize(self.command_log, label="command log"))

    def to_dict(self) -> dict[str, object]:
        return {
            "queue_surface": self.queue_surface.to_dict(),
            "touched_refs": list(self.touched_refs),
            "owner_echo": list(self.owner_echo),
            "waiting_echo": list(self.waiting_echo),
            "command_log": list(self.command_log),
        }


def get_review_queue_surface(
    query: ReviewHomeQuery | None = None,
    *,
    command_surface: ReviewCommandSurface | None = None,
) -> ReviewQueueSurface:
    source_surface = command_surface or get_review_home_surface(query)
    return build_review_queue_surface(source_surface)


def build_review_queue_surface(command_surface: ReviewCommandSurface) -> ReviewQueueSurface:
    cards = command_surface.priority_stack
    entries = _entries_from_cards(cards)
    return ReviewQueueSurface(
        queue_id="review-queue",
        headline=command_surface.headline,
        entries=entries,
        restack_lane=tuple(entry.object_ref for entry in entries),
        available_bulk_commands=("restack", "reroute", "escalate"),
    )


def apply_queue_commands(
    queue_surface: ReviewQueueSurface,
    commands: Iterable[QueueCommand],
) -> QueueMutationResult:
    current = queue_surface
    touched: list[str] = []
    command_log: list[str] = []
    for command in commands:
        if command.command_type is QueueCommandType.RESTACK:
            current, refs = restack_queue(current, ordered_refs=command.ordered_refs, reason=command.reason)
            touched.extend(refs)
            command_log.append(f"restack:{command.reason}")
        elif command.command_type is QueueCommandType.REROUTE:
            current, ref = reroute_queue_entry(current, object_ref=_required_ref(command), new_owner=_required_owner(command), reason=command.reason)
            touched.append(ref)
            command_log.append(f"reroute:{ref}:{command.reason}")
        elif command.command_type is QueueCommandType.ESCALATE:
            current, ref = escalate_queue_entry(current, object_ref=_required_ref(command), reason=command.reason)
            touched.append(ref)
            command_log.append(f"escalate:{ref}:{command.reason}")
    touched_refs = tuple(_dedupe(touched))
    touched_entries = tuple(entry for entry in current.entries if entry.object_ref in touched_refs)
    return QueueMutationResult(
        queue_surface=current,
        touched_refs=touched_refs,
        owner_echo=tuple(
            {
                "object_ref": entry.object_ref,
                "queue_owner": entry.queue_owner,
                "owner_state": entry.owner_state.value,
            }
            for entry in touched_entries
        ),
        waiting_echo=tuple(
            {
                "object_ref": entry.object_ref,
                "waiting_on_refs": list(entry.dependency_state.waiting_on_refs),
                "waiting_summary": entry.dependency_state.waiting_summary,
            }
            for entry in touched_entries
        ),
        command_log=tuple(command_log),
    )


def restack_queue(
    queue_surface: ReviewQueueSurface,
    *,
    ordered_refs: tuple[str, ...],
    reason: str,
) -> tuple[ReviewQueueSurface, tuple[str, ...]]:
    _validate_full_order(queue_surface=queue_surface, ordered_refs=ordered_refs)
    mapping = {entry.object_ref: entry for entry in queue_surface.entries}
    ordered_entries = [
        _entry_with_trace(mapping[ref], f"restack:{reason}")
        for ref in ordered_refs
    ]
    rebuilt = _rebuild_queue_surface(queue_surface=queue_surface, ordered_entries=tuple(ordered_entries))
    return rebuilt, ordered_refs


def reroute_queue_entry(
    queue_surface: ReviewQueueSurface,
    *,
    object_ref: str,
    new_owner: str,
    reason: str,
) -> tuple[ReviewQueueSurface, str]:
    updated: list[ReviewQueueEntry] = []
    found = False
    for entry in queue_surface.entries:
        if entry.object_ref != object_ref:
            updated.append(entry)
            continue
        found = True
        updated.append(
            ReviewQueueEntry(
                object_ref=entry.object_ref,
                title=entry.title,
                queue_position=entry.queue_position,
                urgency=entry.urgency,
                risk_type=entry.risk_type,
                owner_state=OwnerState.ASSIGNED,
                queue_owner=new_owner,
                command_actions=entry.command_actions,
                upstream_trace=entry.upstream_trace.append(f"reroute:{new_owner}:{reason}"),
                dependency_state=entry.dependency_state,
            )
        )
    if not found:
        raise ValueError(f"object_ref={object_ref} is not present in the current queue")
    rebuilt = _rebuild_queue_surface(queue_surface=queue_surface, ordered_entries=tuple(updated))
    return rebuilt, object_ref


def escalate_queue_entry(
    queue_surface: ReviewQueueSurface,
    *,
    object_ref: str,
    reason: str,
) -> tuple[ReviewQueueSurface, str]:
    mapping = {entry.object_ref: entry for entry in queue_surface.entries}
    if object_ref not in mapping:
        raise ValueError(f"object_ref={object_ref} is not present in the current queue")
    front = ReviewQueueEntry(
        object_ref=mapping[object_ref].object_ref,
        title=mapping[object_ref].title,
        queue_position=0,
        urgency=UrgencyLevel.URGENT,
        risk_type=mapping[object_ref].risk_type,
        owner_state=OwnerState.ESCALATED,
        queue_owner=mapping[object_ref].queue_owner,
        command_actions=mapping[object_ref].command_actions,
        upstream_trace=mapping[object_ref].upstream_trace.append(f"escalate:{reason}"),
        dependency_state=mapping[object_ref].dependency_state,
    )
    ordered_refs = (object_ref,) + tuple(entry.object_ref for entry in queue_surface.entries if entry.object_ref != object_ref)
    ordered_entries = [front] + [mapping[ref] for ref in ordered_refs[1:]]
    rebuilt = _rebuild_queue_surface(queue_surface=queue_surface, ordered_entries=tuple(ordered_entries))
    return rebuilt, object_ref


def _rebuild_queue_surface(
    *,
    queue_surface: ReviewQueueSurface,
    ordered_entries: tuple[ReviewQueueEntry, ...],
) -> ReviewQueueSurface:
    entries = _reindex_entries(ordered_entries)
    return ReviewQueueSurface(
        queue_id=queue_surface.queue_id,
        headline=queue_surface.headline,
        entries=entries,
        restack_lane=tuple(entry.object_ref for entry in entries),
        available_bulk_commands=queue_surface.available_bulk_commands,
    )


def _entries_from_cards(cards: tuple[PriorityStackCard, ...]) -> tuple[ReviewQueueEntry, ...]:
    provisional = tuple(
        ReviewQueueEntry(
            object_ref=card.object_ref,
            title=card.title,
            queue_position=index,
            urgency=card.urgency,
            risk_type=card.risk_type,
            owner_state=card.owner_state,
            queue_owner=card.queue_owner,
            command_actions=card.command_actions,
            upstream_trace=UpstreamCommandTrace(
                source_risk_id=card.risk_id,
                source_risk_type=card.risk_type,
                command_origin_tag=f"{card.risk_type.value}:{card.urgency.value}",
            ),
            dependency_state=QueueDependencyState(
                impacted_surfaces=card.affected_surfaces,
            ),
        )
        for index, card in enumerate(cards)
    )
    return _reindex_entries(provisional)


def _reindex_entries(entries: tuple[ReviewQueueEntry, ...]) -> tuple[ReviewQueueEntry, ...]:
    rebuilt: list[ReviewQueueEntry] = []
    for index, entry in enumerate(entries):
        waiting_on_refs = _derive_waiting_refs(index=index, rebuilt=tuple(rebuilt), current=entry)
        rebuilt.append(
            ReviewQueueEntry(
                object_ref=entry.object_ref,
                title=entry.title,
                queue_position=index,
                urgency=entry.urgency,
                risk_type=entry.risk_type,
                owner_state=entry.owner_state,
                queue_owner=entry.queue_owner,
                command_actions=entry.command_actions,
                upstream_trace=entry.upstream_trace,
                dependency_state=QueueDependencyState(
                    impacted_surfaces=entry.dependency_state.impacted_surfaces,
                    waiting_on_refs=waiting_on_refs,
                    waiting_summary=_waiting_summary(waiting_on_refs),
                ),
            )
        )
    return tuple(rebuilt)


def _derive_waiting_refs(
    *,
    index: int,
    rebuilt: tuple[ReviewQueueEntry, ...],
    current: ReviewQueueEntry,
) -> tuple[str, ...]:
    if index == 0:
        return ()
    same_owner = [
        entry.object_ref
        for entry in rebuilt
        if current.queue_owner is not None and entry.queue_owner == current.queue_owner
    ]
    if same_owner:
        return (same_owner[-1],)
    shared_surface_predecessors = [
        entry.object_ref
        for entry in rebuilt
        if set(entry.dependency_state.impacted_surfaces).intersection(current.dependency_state.impacted_surfaces)
    ]
    if shared_surface_predecessors:
        return (shared_surface_predecessors[-1],)
    return ()


def _waiting_summary(waiting_on_refs: tuple[str, ...]) -> str:
    if not waiting_on_refs:
        return "Ready for direct action."
    if len(waiting_on_refs) == 1:
        return f"Waiting behind {waiting_on_refs[0]} before direct action."
    return f"Waiting behind {len(waiting_on_refs)} upstream queue item(s)."


def _urgency_rank(urgency: UrgencyLevel) -> int:
    return {
        UrgencyLevel.URGENT: 0,
        UrgencyLevel.HIGH: 1,
        UrgencyLevel.MEDIUM: 2,
        UrgencyLevel.LOW: 3,
    }[urgency]


def _validate_full_order(*, queue_surface: ReviewQueueSurface, ordered_refs: tuple[str, ...]) -> None:
    current_refs = tuple(entry.object_ref for entry in queue_surface.entries)
    if tuple(ordered_refs) != current_refs and set(ordered_refs) != set(current_refs):
        raise ValueError("ordered_refs must contain the exact queue object refs")
    if len(ordered_refs) != len(current_refs):
        raise ValueError("ordered_refs length must match queue size")
    if len(set(ordered_refs)) != len(ordered_refs):
        raise ValueError("ordered_refs must not contain duplicates")


def _required_ref(command: QueueCommand) -> str:
    if command.object_ref is None:
        raise ValueError(f"{command.command_type.value} command requires object_ref")
    return command.object_ref


def _required_owner(command: QueueCommand) -> str:
    if command.new_owner is None:
        raise ValueError("reroute command requires new_owner")
    return command.new_owner


def _entry_with_trace(entry: ReviewQueueEntry, command_value: str) -> ReviewQueueEntry:
    return ReviewQueueEntry(
        object_ref=entry.object_ref,
        title=entry.title,
        queue_position=entry.queue_position,
        urgency=entry.urgency,
        risk_type=entry.risk_type,
        owner_state=entry.owner_state,
        queue_owner=entry.queue_owner,
        command_actions=entry.command_actions,
        upstream_trace=entry.upstream_trace.append(command_value),
        dependency_state=entry.dependency_state,
    )


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)
