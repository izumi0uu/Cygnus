from __future__ import annotations

from collections.abc import Iterator
from typing import Any, final

from cygnus.domain.objects import KnowledgeObjectType
from cygnus.governance.drift_signals import DriftSignalProviderResult
from cygnus.review.service import ProposalBundle
from cygnus.review.surface import ObservationState, SurfaceObservation
from cygnus.runtime.database.models import GovernanceSignal
from cygnus.substrate.agent_protocol import ToolDefinition


_FILTER_KEYS = ("object_type", "severity", "channel")
_OBJECT_TYPE_VALUES = frozenset(item.value for item in KnowledgeObjectType)
_SEVERITY_VALUES = frozenset({"medium", "high", "urgent"})
_DRIFT_COVERAGE = ("release_delta", "incident_delta")


@final
class GovernedDriftTools:
    """Request-scoped adapter over durable release and incident drift truth."""

    __slots__ = ("_provider",)

    def __init__(self, provider: DriftSignalProviderResult) -> None:
        self._provider = provider

    def list_drift_alerts(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Project scoped durable alerts without hiding incomplete coverage."""
        try:
            normalized_filters, normalized_limit = normalize_drift_alert_arguments(
                filters=filters,
                limit=limit,
            )
        except ValueError as exc:
            return _invalid(str(exc))

        alerts: list[dict[str, object]] = []
        observed_count = 0
        for alert in _alerts_from_provider(self._provider):
            if not _matches_filters(alert, normalized_filters):
                continue
            observed_count += 1
            if len(alerts) < normalized_limit:
                alerts.append(alert)
        observation = _observation_for_provider(
            self._provider,
            observed_count=observed_count,
        )
        return {
            "status": _status_for_observation(observation),
            "summary": _summary_for_observation(observation, len(alerts)),
            "data": {
                "filters": normalized_filters,
                "limit": normalized_limit,
                "observation": observation.to_dict(),
                "alerts": alerts,
            },
            "warnings": list(observation.missing_signals),
            "errors": [],
        }


def normalize_drift_alert_arguments(
    *,
    filters: object | None,
    limit: object,
) -> tuple[dict[str, str], int]:
    """Validate raw tool inputs without loading request-scoped provider truth."""
    return _normalize_filters(filters), _normalize_limit(limit)


def drift_tool_definitions() -> tuple[ToolDefinition, ...]:
    return _DRIFT_TOOL_DEFINITIONS


def drift_tool_bindings(
    tools: GovernedDriftTools,
) -> tuple[tuple[ToolDefinition, Any], ...]:
    definition = drift_tool_definitions()[0]
    return ((definition, tools.list_drift_alerts),)


def _alerts_from_provider(
    provider: DriftSignalProviderResult,
) -> Iterator[dict[str, object]]:
    bundles_by_signal_ref = {
        bundle.signal.signal_ref: bundle for bundle in provider.bundles
    }
    for signal in provider.signals:
        bundle = bundles_by_signal_ref.get(signal.signal_ref)
        if bundle is not None:
            yield _alert_from_signal_bundle(signal, bundle)


def _alert_from_signal_bundle(
    signal: GovernanceSignal,
    bundle: ProposalBundle,
) -> dict[str, object]:
    return {
        "signal_ref": signal.signal_ref,
        "signal_type": signal.signal_type,
        "object_ref": signal.object_ref,
        "object_type": bundle.proposal.object_type.value,
        "title": signal.title,
        "severity": bundle.proposal.urgency.value,
        "reason": signal.reason,
        "summary": signal.summary,
        "affected_audiences": [
            audience.to_dict() for audience in bundle.signal.affected_audiences
        ],
        "affected_surfaces": list(bundle.signal.affected_surfaces),
        "suggested_actions": list(bundle.signal.recommended_actions),
        "freshness": signal.freshness,
        "observed_at": signal.observed_at.isoformat(),
        "trace_ref": f"governance-signal:{signal.signal_ref}",
    }


def _normalize_filters(filters: object | None) -> dict[str, str]:
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")

    unknown = tuple(key for key in filters if key not in _FILTER_KEYS)
    if unknown:
        raise ValueError(
            "filters contain unsupported keys: "
            + ", ".join(str(key) for key in unknown)
        )

    normalized: dict[str, str] = {}
    for key in _FILTER_KEYS:
        if key not in filters:
            continue
        raw_value = filters[key]
        if not isinstance(raw_value, str):
            raise ValueError(f"filters.{key} must be a nonblank string")
        value = raw_value.strip()
        if not value:
            raise ValueError(f"filters.{key} must be a nonblank string")
        if key == "object_type" and value not in _OBJECT_TYPE_VALUES:
            raise ValueError(
                "filters.object_type must be one of "
                + ", ".join(sorted(_OBJECT_TYPE_VALUES))
            )
        if key == "severity" and value not in _SEVERITY_VALUES:
            raise ValueError(
                "filters.severity must be one of " + ", ".join(sorted(_SEVERITY_VALUES))
            )
        normalized[key] = value
    return normalized


def _normalize_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer between 1 and 50")
    if not 1 <= value <= 50:
        raise ValueError("limit must be between 1 and 50")
    return value


def _matches_filters(
    alert: dict[str, object],
    filters: dict[str, str],
) -> bool:
    object_type = filters.get("object_type")
    if object_type is not None and alert["object_type"] != object_type:
        return False
    severity = filters.get("severity")
    if severity is not None and alert["severity"] != severity:
        return False
    channel = filters.get("channel")
    affected_surfaces = alert["affected_surfaces"]
    if channel is not None and (
        not isinstance(affected_surfaces, (list, tuple))
        or channel not in affected_surfaces
    ):
        return False
    return True


def _observation_for_provider(
    provider: DriftSignalProviderResult,
    *,
    observed_count: int,
) -> SurfaceObservation:
    if not provider.covered_signals:
        return SurfaceObservation(
            state=ObservationState.UNAVAILABLE,
            observed_count=0,
            reason="persisted_drift_provider_unavailable",
            missing_signals=provider.missing_signals or _DRIFT_COVERAGE,
        )
    return SurfaceObservation(
        state=(
            ObservationState.PARTIAL
            if provider.missing_signals
            else ObservationState.READY
        ),
        observed_count=observed_count,
        reason=(
            "persisted_drift_provider_partial"
            if provider.missing_signals
            else "persisted_drift_provider_ready"
        ),
        covered_signals=provider.covered_signals,
        missing_signals=provider.missing_signals,
    )


def _status_for_observation(observation: SurfaceObservation) -> str:
    if observation.state is ObservationState.PARTIAL:
        return "partial"
    if observation.state is ObservationState.UNAVAILABLE:
        return "unavailable"
    return "success"


def _summary_for_observation(
    observation: SurfaceObservation,
    alert_count: int,
) -> str:
    if observation.state is ObservationState.UNAVAILABLE:
        return "Durable drift alert coverage is unavailable."
    if observation.state is ObservationState.PARTIAL:
        return f"{alert_count} governed drift alert(s) loaded with partial detector coverage."
    if alert_count:
        return f"{alert_count} governed drift alert(s) loaded."
    return "No governed drift alerts matched the current filters."


def _invalid(summary: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "summary": summary,
        "data": {},
        "warnings": [],
        "errors": ["invalid_arguments"],
    }


_DRIFT_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="list_drift_alerts",
        description=(
            "List scoped durable release and incident drift alerts with explicit "
            "coverage state."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "filters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "enum": sorted(_OBJECT_TYPE_VALUES),
                        },
                        "severity": {
                            "type": "string",
                            "enum": sorted(_SEVERITY_VALUES),
                        },
                        "channel": {"type": "string", "minLength": 1},
                    },
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                },
            },
        },
        risk_level="R0",
    ),
)
