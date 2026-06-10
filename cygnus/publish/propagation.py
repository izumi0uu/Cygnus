from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.publish.actions import PublishGovernanceResult
from cygnus.publish.preview import PublishBinding


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


class PropagationStatus(str, Enum):
    SYNCED = "synced"
    PENDING = "pending"
    FAILED = "failed"
    MANUAL_ACTION_REQUIRED = "manual_action_required"


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfacePropagationUpdate:
    surface_id: str
    status: PropagationStatus
    reason: str
    channel_refs: tuple[str, ...] = field(default_factory=tuple)
    follow_up_commands: tuple[str, ...] = field(default_factory=tuple)
    binding_refs: tuple[PublishBinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        object.__setattr__(self, "channel_refs", _normalize_strings(self.channel_refs, label="channel ref"))
        object.__setattr__(
            self,
            "follow_up_commands",
            _normalize_strings(self.follow_up_commands, label="follow-up command"),
        )
        object.__setattr__(self, "binding_refs", tuple(self.binding_refs))


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfacePropagationRecord:
    surface_id: str
    status: PropagationStatus
    reason: str
    channel_refs: tuple[str, ...]
    binding_refs: tuple[PublishBinding, ...] = field(default_factory=tuple)
    follow_up_commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        object.__setattr__(self, "channel_refs", _normalize_strings(self.channel_refs, label="channel ref"))
        object.__setattr__(self, "binding_refs", tuple(self.binding_refs))
        object.__setattr__(
            self,
            "follow_up_commands",
            _normalize_strings(self.follow_up_commands, label="follow-up command"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "status": self.status.value,
            "reason": self.reason,
            "channel_refs": list(self.channel_refs),
            "binding_refs": [binding.to_dict() for binding in self.binding_refs],
            "follow_up_commands": list(self.follow_up_commands),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PropagationLedgerSummary:
    synced: int = 0
    pending: int = 0
    failed: int = 0
    manual_action_required: int = 0

    def __post_init__(self) -> None:
        for field_name in ("synced", "pending", "failed", "manual_action_required"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")

    def to_dict(self) -> dict[str, int]:
        return {
            "synced": self.synced,
            "pending": self.pending,
            "failed": self.failed,
            "manual_action_required": self.manual_action_required,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishPropagationLedger:
    object_id: str
    title: str
    action_log: tuple[str, ...]
    summary: PropagationLedgerSummary
    records: tuple[SurfacePropagationRecord, ...]
    unresolved_surfaces: tuple[str, ...]
    continue_commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("object_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        object.__setattr__(self, "action_log", _normalize_strings(self.action_log, label="action log"))
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "unresolved_surfaces", _normalize_strings(self.unresolved_surfaces, label="unresolved surface"))
        object.__setattr__(
            self,
            "continue_commands",
            _normalize_strings(self.continue_commands, label="continue command"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "title": self.title,
            "action_log": list(self.action_log),
            "summary": self.summary.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "unresolved_surfaces": list(self.unresolved_surfaces),
            "continue_commands": list(self.continue_commands),
        }


def build_publish_propagation_ledger(
    governance_result: PublishGovernanceResult,
    *,
    surface_updates: Iterable[SurfacePropagationUpdate] | None = None,
    supporting_surfaces: Iterable[str] | None = None,
) -> PublishPropagationLedger:
    updates = tuple(surface_updates or ())
    update_map = {update.surface_id: update for update in updates}

    channel_bindings = _group_bindings_by_channel(governance_result)
    surface_ids = _ordered_surfaces(
        channel_bindings.keys(),
        tuple(supporting_surfaces or ()),
        tuple(update_map.keys()),
    )

    records: list[SurfacePropagationRecord] = []
    for surface_id in surface_ids:
        explicit = update_map.get(surface_id)
        if explicit is not None:
            bindings = explicit.binding_refs or tuple(channel_bindings.get(surface_id, ()))
            channels = explicit.channel_refs or _channels_from_bindings(bindings) or ((surface_id,) if surface_id in channel_bindings else ())
            records.append(
                SurfacePropagationRecord(
                    surface_id=surface_id,
                    status=explicit.status,
                    reason=explicit.reason,
                    channel_refs=channels,
                    binding_refs=bindings,
                    follow_up_commands=explicit.follow_up_commands,
                )
            )
            continue

        record = _default_record(surface_id=surface_id, governance_result=governance_result, channel_bindings=channel_bindings)
        if record is not None:
            records.append(record)

    summary = PropagationLedgerSummary(
        synced=sum(1 for record in records if record.status is PropagationStatus.SYNCED),
        pending=sum(1 for record in records if record.status is PropagationStatus.PENDING),
        failed=sum(1 for record in records if record.status is PropagationStatus.FAILED),
        manual_action_required=sum(
            1 for record in records if record.status is PropagationStatus.MANUAL_ACTION_REQUIRED
        ),
    )
    unresolved_surfaces = tuple(
        record.surface_id for record in records if record.status is not PropagationStatus.SYNCED
    )
    continue_commands = _dedupe(
        command
        for record in records
        if record.status is not PropagationStatus.SYNCED
        for command in record.follow_up_commands
    )
    return PublishPropagationLedger(
        object_id=governance_result.updated_candidate.object_id,
        title=governance_result.updated_candidate.title,
        action_log=governance_result.action_log,
        summary=summary,
        records=tuple(records),
        unresolved_surfaces=unresolved_surfaces,
        continue_commands=continue_commands,
    )


def _default_record(
    *,
    surface_id: str,
    governance_result: PublishGovernanceResult,
    channel_bindings: dict[str, tuple[PublishBinding, ...]],
) -> SurfacePropagationRecord | None:
    if surface_id in channel_bindings:
        blocked = tuple(
            binding
            for binding in channel_bindings[surface_id]
            if any(
                held.audience_filter == binding.audience_filter and held.channel == binding.channel
                for held in governance_result.held_bindings
            )
        )
        if blocked:
            return SurfacePropagationRecord(
                surface_id=surface_id,
                status=PropagationStatus.MANUAL_ACTION_REQUIRED,
                reason="This surface still contains held audience paths that require manual intervention before full sync.",
                channel_refs=(surface_id,),
                binding_refs=blocked,
                follow_up_commands=("resolve_surface_hold", "recheck_propagation"),
            )
        removed = tuple(binding for binding in governance_result.removed_bindings if binding.channel == surface_id)
        if removed:
            return SurfacePropagationRecord(
                surface_id=surface_id,
                status=PropagationStatus.PENDING,
                reason="This surface has removal or routing changes defined, but downstream confirmation has not been recorded yet.",
                channel_refs=(surface_id,),
                binding_refs=_dedupe_bindings((*channel_bindings[surface_id], *removed)),
                follow_up_commands=("check_propagation_status",),
            )
        return SurfacePropagationRecord(
            surface_id=surface_id,
            status=PropagationStatus.PENDING,
            reason="This surface is a propagation target but no sync result has been recorded yet.",
            channel_refs=(surface_id,),
            binding_refs=channel_bindings[surface_id],
            follow_up_commands=("check_propagation_status",),
        )

    return SurfacePropagationRecord(
        surface_id=surface_id,
        status=PropagationStatus.PENDING,
        reason="This supporting surface is expected to reflect publish results, but no downstream status has been recorded yet.",
        channel_refs=(),
        binding_refs=(),
        follow_up_commands=("check_supporting_surface",),
    )


def _group_bindings_by_channel(governance_result: PublishGovernanceResult) -> dict[str, tuple[PublishBinding, ...]]:
    grouped: dict[str, list[PublishBinding]] = {}
    for binding in governance_result.updated_candidate.target_bindings:
        grouped.setdefault(binding.channel, []).append(binding)
    for binding in governance_result.removed_bindings:
        grouped.setdefault(binding.channel, []).append(binding)
    return {channel: tuple(bindings) for channel, bindings in grouped.items()}


def _ordered_surfaces(
    channel_surfaces: Iterable[str],
    supporting_surfaces: Iterable[str],
    updated_surfaces: Iterable[str],
) -> tuple[str, ...]:
    ordered: list[str] = []
    for surface_id in (*tuple(channel_surfaces), *tuple(supporting_surfaces), *tuple(updated_surfaces)):
        if surface_id not in ordered:
            ordered.append(surface_id)
    return tuple(ordered)


def _channels_from_bindings(bindings: tuple[PublishBinding, ...]) -> tuple[str, ...]:
    return _dedupe(binding.channel for binding in bindings)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _dedupe_bindings(values: Iterable[PublishBinding]) -> tuple[PublishBinding, ...]:
    seen: set[tuple[object, str]] = set()
    ordered: list[PublishBinding] = []
    for binding in values:
        if binding.key in seen:
            continue
        seen.add(binding.key)
        ordered.append(binding)
    return tuple(ordered)
