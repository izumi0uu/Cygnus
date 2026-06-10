from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.publish.preview import (
    BlastRadiusPreview,
    PublishBinding,
    PublishConflict,
    PublishPreviewCandidate,
    build_publish_blast_radius_preview,
)


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


class PublishGovernanceActionType(str, Enum):
    PUBLISH = "publish"
    RESTRICT = "restrict"
    SPLIT_VARIANT = "split_variant"
    HOLD_EXTERNAL = "hold_external"
    REPUBLISH_INTERNAL_ONLY = "republish_internal_only"


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishGovernanceAction:
    action_type: PublishGovernanceActionType
    audiences: tuple[AudienceFilter, ...] = field(default_factory=tuple)
    channels: tuple[str, ...] = field(default_factory=tuple)
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "audiences", tuple(self.audiences))
        object.__setattr__(self, "channels", _normalize_strings(self.channels, label="channel"))
        if not self.reason.strip():
            raise ValueError("reason must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishGovernanceResult:
    updated_candidate: PublishPreviewCandidate
    preview: BlastRadiusPreview
    opened_bindings: tuple[PublishBinding, ...]
    removed_bindings: tuple[PublishBinding, ...]
    held_bindings: tuple[PublishConflict, ...]
    action_log: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "opened_bindings", tuple(self.opened_bindings))
        object.__setattr__(self, "removed_bindings", tuple(self.removed_bindings))
        object.__setattr__(self, "held_bindings", tuple(self.held_bindings))
        object.__setattr__(self, "action_log", _normalize_strings(self.action_log, label="action log"))

    def to_dict(self) -> dict[str, object]:
        return {
            "updated_candidate": self.updated_candidate.to_dict(),
            "preview": self.preview.to_dict(),
            "opened_bindings": [binding.to_dict() for binding in self.opened_bindings],
            "removed_bindings": [binding.to_dict() for binding in self.removed_bindings],
            "held_bindings": [binding.to_dict() for binding in self.held_bindings],
            "action_log": list(self.action_log),
        }


def apply_publish_governance_actions(
    candidate: PublishPreviewCandidate,
    actions: Iterable[PublishGovernanceAction],
) -> PublishGovernanceResult:
    original_bindings = tuple(candidate.target_bindings)
    binding_map = {binding.key: binding for binding in candidate.target_bindings}
    blocked_map = {binding.key: binding for binding in candidate.blocked_bindings}
    action_log: list[str] = []

    for action in actions:
        if action.action_type is PublishGovernanceActionType.PUBLISH:
            for binding in _resolve_action_bindings(candidate, action):
                binding_map[binding.key] = binding
            action_log.append(f"publish:{action.reason}")
            continue

        if action.action_type is PublishGovernanceActionType.RESTRICT:
            for binding in _resolve_action_bindings(candidate, action):
                binding_map.pop(binding.key, None)
                blocked_map.pop(binding.key, None)
            action_log.append(f"restrict:{action.reason}")
            continue

        if action.action_type is PublishGovernanceActionType.SPLIT_VARIANT:
            for binding in _resolve_action_bindings(candidate, action, require_explicit_audiences=True):
                binding_map[binding.key] = binding
            action_log.append(f"split_variant:{action.reason}")
            continue

        if action.action_type is PublishGovernanceActionType.HOLD_EXTERNAL:
            for binding in _resolve_action_bindings(candidate, action, external_only=True):
                blocked_map[binding.key] = PublishConflict(
                    audience_filter=binding.audience_filter,
                    channel=binding.channel,
                    reason=f"Held for gated external review: {action.reason}",
                )
                binding_map[binding.key] = binding
            action_log.append(f"hold_external:{action.reason}")
            continue

        if action.action_type is PublishGovernanceActionType.REPUBLISH_INTERNAL_ONLY:
            internal_bindings = [
                binding
                for binding in _resolve_action_bindings(candidate, action)
                if binding.audience_filter.visibility is Visibility.INTERNAL
            ]
            if action.audiences and not internal_bindings:
                raise ValueError("republish_internal_only requires internal audiences when explicit audiences are provided")
            binding_map = {
                key: binding
                for key, binding in binding_map.items()
                if binding.audience_filter.visibility is Visibility.INTERNAL
            }
            for binding in internal_bindings:
                binding_map[binding.key] = binding
            blocked_map = {
                key: blocked
                for key, blocked in blocked_map.items()
                if blocked.audience_filter.visibility is Visibility.INTERNAL
            }
            action_log.append(f"republish_internal_only:{action.reason}")
            continue

        raise ValueError(f"unsupported governance action: {action.action_type.value}")

    updated_candidate = PublishPreviewCandidate(
        object_id=candidate.object_id,
        object_type=candidate.object_type,
        title=candidate.title,
        action_type=candidate.action_type,
        target_audiences=candidate.target_audiences,
        target_channels=candidate.target_channels,
        target_bindings=tuple(binding_map.values()),
        current_bindings=candidate.current_bindings,
        blocked_bindings=tuple(blocked_map.values()),
    )
    preview = build_publish_blast_radius_preview(updated_candidate)
    updated_keys = {binding.key for binding in updated_candidate.target_bindings}
    original_keys = {binding.key for binding in original_bindings}
    opened_bindings = tuple(binding for binding in updated_candidate.target_bindings if binding.key not in original_keys)
    removed_bindings = tuple(binding for binding in original_bindings if binding.key not in updated_keys)
    held_bindings = tuple(
        blocked
        for blocked in updated_candidate.blocked_bindings
        if blocked.audience_filter.visibility is Visibility.EXTERNAL
    )
    return PublishGovernanceResult(
        updated_candidate=updated_candidate,
        preview=preview,
        opened_bindings=opened_bindings,
        removed_bindings=removed_bindings,
        held_bindings=held_bindings,
        action_log=tuple(action_log),
    )


def _resolve_action_bindings(
    candidate: PublishPreviewCandidate,
    action: PublishGovernanceAction,
    *,
    require_explicit_audiences: bool = False,
    external_only: bool = False,
) -> tuple[PublishBinding, ...]:
    audiences = action.audiences or candidate.target_audiences
    if require_explicit_audiences and not action.audiences:
        raise ValueError(f"{action.action_type.value} requires explicit audiences")
    channels = action.channels or candidate.target_channels
    bindings: list[PublishBinding] = []
    for audience in audiences:
        if external_only and audience.visibility is not Visibility.EXTERNAL:
            continue
        for channel in channels:
            binding = PublishBinding(audience_filter=audience, channel=channel)
            if binding not in bindings:
                bindings.append(binding)
    return tuple(bindings)
