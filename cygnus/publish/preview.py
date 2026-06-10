from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import AnswerCard, KnowledgeObject, KnowledgeObjectType


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


class PublishActionType(str, Enum):
    PUBLISH = "publish"
    REPUBLISH = "republish"
    RESTRICT = "restrict"


class BlastRadiusEffect(str, Enum):
    NEW_EXPOSURE = "new_exposure"
    CONTINUING_EXPOSURE = "continuing_exposure"
    STOPPED_EXPOSURE = "stopped_exposure"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishBinding:
    audience_filter: AudienceFilter
    channel: str

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise ValueError("channel must not be blank")

    @property
    def key(self) -> tuple[AudienceFilter, str]:
        return (self.audience_filter, self.channel)

    def to_dict(self) -> dict[str, object]:
        return {
            "audience_filter": self.audience_filter.to_dict(),
            "audience_label": _audience_label(self.audience_filter),
            "channel": self.channel,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishConflict:
    audience_filter: AudienceFilter
    channel: str
    reason: str

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise ValueError("channel must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")

    @property
    def key(self) -> tuple[AudienceFilter, str]:
        return (self.audience_filter, self.channel)

    def to_dict(self) -> dict[str, object]:
        return {
            "audience_filter": self.audience_filter.to_dict(),
            "audience_label": _audience_label(self.audience_filter),
            "channel": self.channel,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishPreviewCandidate:
    object_id: str
    object_type: KnowledgeObjectType
    title: str
    action_type: PublishActionType
    target_audiences: tuple[AudienceFilter, ...]
    target_channels: tuple[str, ...]
    target_bindings: tuple[PublishBinding, ...] = field(default_factory=tuple)
    current_bindings: tuple[PublishBinding, ...] = field(default_factory=tuple)
    blocked_bindings: tuple[PublishConflict, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("object_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        object.__setattr__(self, "target_audiences", tuple(self.target_audiences))
        object.__setattr__(
            self,
            "target_channels",
            _normalize_strings(self.target_channels, label="target channel"),
        )
        object.__setattr__(self, "target_bindings", tuple(self.target_bindings))
        object.__setattr__(self, "current_bindings", tuple(self.current_bindings))
        object.__setattr__(self, "blocked_bindings", tuple(self.blocked_bindings))
        if not self.target_audiences:
            raise ValueError("target_audiences must not be empty")
        if not self.target_channels:
            raise ValueError("target_channels must not be empty")
        if not self.target_bindings:
            object.__setattr__(
                self,
                "target_bindings",
                tuple(
                    PublishBinding(audience_filter=audience, channel=channel)
                    for audience in self.target_audiences
                    for channel in self.target_channels
                ),
            )
        object.__setattr__(
            self,
            "target_audiences",
            _bindings_to_audiences(self.target_bindings),
        )
        object.__setattr__(
            self,
            "target_channels",
            _bindings_to_channels(self.target_bindings),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "title": self.title,
            "action_type": self.action_type.value,
            "target_audiences": [audience.to_dict() for audience in self.target_audiences],
            "target_channels": list(self.target_channels),
            "target_bindings": [binding.to_dict() for binding in self.target_bindings],
            "current_bindings": [binding.to_dict() for binding in self.current_bindings],
            "blocked_bindings": [binding.to_dict() for binding in self.blocked_bindings],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceScopeSummary:
    total_audiences: int
    visibility_mix: tuple[str, ...]
    audience_labels: tuple[str, ...]
    affected_channels: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.total_audiences <= 0:
            raise ValueError("total_audiences must be positive")
        object.__setattr__(self, "visibility_mix", _normalize_strings(self.visibility_mix, label="visibility mix"))
        object.__setattr__(self, "audience_labels", _normalize_strings(self.audience_labels, label="audience label"))
        object.__setattr__(self, "affected_channels", _normalize_strings(self.affected_channels, label="affected channel"))

    def to_dict(self) -> dict[str, object]:
        return {
            "total_audiences": self.total_audiences,
            "visibility_mix": list(self.visibility_mix),
            "audience_labels": list(self.audience_labels),
            "affected_channels": list(self.affected_channels),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelGateSummary:
    channel: str
    new_exposure: int = 0
    continuing_exposure: int = 0
    stopped_exposure: int = 0
    conflicts: int = 0

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise ValueError("channel must not be blank")
        for field_name in (
            "new_exposure",
            "continuing_exposure",
            "stopped_exposure",
            "conflicts",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "new_exposure": self.new_exposure,
            "continuing_exposure": self.continuing_exposure,
            "stopped_exposure": self.stopped_exposure,
            "conflicts": self.conflicts,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BlastRadiusImpact:
    audience_filter: AudienceFilter
    channel: str
    effect: BlastRadiusEffect
    reason: str

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise ValueError("channel must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")

    def to_dict(self) -> dict[str, object]:
        return {
            "audience_filter": self.audience_filter.to_dict(),
            "audience_label": _audience_label(self.audience_filter),
            "channel": self.channel,
            "effect": self.effect.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BlastRadiusPreview:
    object_id: str
    object_type: KnowledgeObjectType
    title: str
    action_type: PublishActionType
    audience_scope: AudienceScopeSummary
    channel_gate_matrix: tuple[ChannelGateSummary, ...]
    impacts: tuple[BlastRadiusImpact, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("object_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        object.__setattr__(self, "channel_gate_matrix", tuple(self.channel_gate_matrix))
        object.__setattr__(self, "impacts", tuple(self.impacts))
        object.__setattr__(self, "warnings", _normalize_strings(self.warnings, label="warning"))
        if not self.channel_gate_matrix:
            raise ValueError("channel_gate_matrix must not be empty")
        if not self.impacts:
            raise ValueError("impacts must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "title": self.title,
            "action_type": self.action_type.value,
            "audience_scope": self.audience_scope.to_dict(),
            "channel_gate_matrix": [summary.to_dict() for summary in self.channel_gate_matrix],
            "impacts": [impact.to_dict() for impact in self.impacts],
            "warnings": list(self.warnings),
        }


def build_publish_preview_candidate(
    knowledge_object: KnowledgeObject,
    *,
    action_type: PublishActionType,
    target_channels: Iterable[str] | None = None,
    current_bindings: Iterable[PublishBinding] | None = None,
    blocked_bindings: Iterable[PublishConflict] | None = None,
) -> PublishPreviewCandidate:
    channels = tuple(target_channels) if target_channels is not None else _default_target_channels(knowledge_object)
    audiences = _resolve_target_audiences(knowledge_object)
    return PublishPreviewCandidate(
        object_id=knowledge_object.object_id,
        object_type=knowledge_object.object_type,
        title=knowledge_object.title,
        action_type=action_type,
        target_audiences=audiences,
        target_channels=channels,
        current_bindings=tuple(current_bindings or ()),
        blocked_bindings=tuple(blocked_bindings or ()),
    )


def build_publish_blast_radius_preview(candidate: PublishPreviewCandidate) -> BlastRadiusPreview:
    target_bindings = candidate.target_bindings
    current_by_key = {binding.key: binding for binding in candidate.current_bindings}
    blocked_by_key = {binding.key: binding for binding in candidate.blocked_bindings}

    impacts: list[BlastRadiusImpact] = []
    seen_keys: set[tuple[AudienceFilter, str]] = set()

    for binding in target_bindings:
        seen_keys.add(binding.key)
        blocked = blocked_by_key.get(binding.key)
        if blocked is not None:
            impacts.append(
                BlastRadiusImpact(
                    audience_filter=binding.audience_filter,
                    channel=binding.channel,
                    effect=BlastRadiusEffect.CONFLICT,
                    reason=blocked.reason,
                )
            )
            continue
        if binding.key in current_by_key:
            impacts.append(
                BlastRadiusImpact(
                    audience_filter=binding.audience_filter,
                    channel=binding.channel,
                    effect=BlastRadiusEffect.CONTINUING_EXPOSURE,
                    reason="This audience and channel are already exposed and would remain active.",
                )
            )
            continue
        impacts.append(
            BlastRadiusImpact(
                audience_filter=binding.audience_filter,
                channel=binding.channel,
                effect=BlastRadiusEffect.NEW_EXPOSURE,
                reason="This audience and channel would become newly exposed if the command proceeds.",
            )
        )

    for binding in candidate.current_bindings:
        if binding.key in seen_keys:
            continue
        impacts.append(
            BlastRadiusImpact(
                audience_filter=binding.audience_filter,
                channel=binding.channel,
                effect=BlastRadiusEffect.STOPPED_EXPOSURE,
                reason="This audience and channel are currently exposed but would stop after the command.",
            )
        )

    audience_scope = _build_audience_scope(impacts)
    channel_gate_matrix = _build_channel_gate_matrix(impacts)
    warnings = _build_warnings(candidate, impacts)
    return BlastRadiusPreview(
        object_id=candidate.object_id,
        object_type=candidate.object_type,
        title=candidate.title,
        action_type=candidate.action_type,
        audience_scope=audience_scope,
        channel_gate_matrix=channel_gate_matrix,
        impacts=tuple(impacts),
        warnings=warnings,
    )


def _default_target_channels(knowledge_object: KnowledgeObject) -> tuple[str, ...]:
    if isinstance(knowledge_object, AnswerCard) and knowledge_object.publish_targets:
        return knowledge_object.publish_targets
    raise ValueError("target_channels must be provided when the object has no publish_targets")


def _resolve_target_audiences(knowledge_object: KnowledgeObject) -> tuple[AudienceFilter, ...]:
    audiences: list[AudienceFilter] = []
    for audience in knowledge_object.supported_audiences:
        if audience not in audiences:
            audiences.append(audience)
    if isinstance(knowledge_object, AnswerCard):
        for variant in knowledge_object.audience_variants:
            if variant.audience_filter not in audiences:
                audiences.append(variant.audience_filter)
    if not audiences:
        raise ValueError("knowledge object must expose at least one supported or variant audience")
    return tuple(audiences)


def _build_audience_scope(impacts: list[BlastRadiusImpact]) -> AudienceScopeSummary:
    unique_audiences: list[AudienceFilter] = []
    channels: list[str] = []
    for impact in impacts:
        if impact.audience_filter not in unique_audiences:
            unique_audiences.append(impact.audience_filter)
        if impact.channel not in channels:
            channels.append(impact.channel)

    visibility_mix = []
    for visibility in (Visibility.EXTERNAL, Visibility.INTERNAL):
        count = sum(1 for audience in unique_audiences if audience.visibility is visibility)
        if count:
            visibility_mix.append(f"{visibility.value}:{count}")
    return AudienceScopeSummary(
        total_audiences=len(unique_audiences),
        visibility_mix=tuple(visibility_mix),
        audience_labels=tuple(_audience_label(audience) for audience in unique_audiences),
        affected_channels=tuple(channels),
    )


def _build_channel_gate_matrix(impacts: list[BlastRadiusImpact]) -> tuple[ChannelGateSummary, ...]:
    ordered_channels: list[str] = []
    for impact in impacts:
        if impact.channel not in ordered_channels:
            ordered_channels.append(impact.channel)

    summaries: list[ChannelGateSummary] = []
    for channel in ordered_channels:
        channel_impacts = [impact for impact in impacts if impact.channel == channel]
        summaries.append(
            ChannelGateSummary(
                channel=channel,
                new_exposure=sum(1 for impact in channel_impacts if impact.effect is BlastRadiusEffect.NEW_EXPOSURE),
                continuing_exposure=sum(
                    1 for impact in channel_impacts if impact.effect is BlastRadiusEffect.CONTINUING_EXPOSURE
                ),
                stopped_exposure=sum(
                    1 for impact in channel_impacts if impact.effect is BlastRadiusEffect.STOPPED_EXPOSURE
                ),
                conflicts=sum(1 for impact in channel_impacts if impact.effect is BlastRadiusEffect.CONFLICT),
            )
        )
    return tuple(summaries)


def _build_warnings(
    candidate: PublishPreviewCandidate,
    impacts: list[BlastRadiusImpact],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if any(impact.effect is BlastRadiusEffect.CONFLICT for impact in impacts):
        warnings.append("At least one audience-channel path is blocked by a governance conflict.")
    if any(impact.effect is BlastRadiusEffect.STOPPED_EXPOSURE for impact in impacts):
        warnings.append("This command would remove at least one current exposure path.")
    if candidate.action_type is PublishActionType.RESTRICT and any(
        impact.audience_filter.visibility is Visibility.EXTERNAL
        and impact.effect is BlastRadiusEffect.NEW_EXPOSURE
        for impact in impacts
    ):
        warnings.append("A restrict command still introduces new external exposure and should be double-checked.")
    return tuple(warnings)


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


def _bindings_to_audiences(bindings: tuple[PublishBinding, ...]) -> tuple[AudienceFilter, ...]:
    audiences: list[AudienceFilter] = []
    for binding in bindings:
        if binding.audience_filter not in audiences:
            audiences.append(binding.audience_filter)
    return tuple(audiences)


def _bindings_to_channels(bindings: tuple[PublishBinding, ...]) -> tuple[str, ...]:
    channels: list[str] = []
    for binding in bindings:
        if binding.channel not in channels:
            channels.append(binding.channel)
    return tuple(channels)
