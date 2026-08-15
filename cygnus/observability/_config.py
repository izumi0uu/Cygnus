"""Observability configuration — env-driven, introspective, exporter-safe.

The config is a plain dataclass resolved from runtime ``Settings`` attributes
when present. It carries no secrets: only enable flags, endpoint/name strings,
and cardinality bounds. When the runtime ``Settings`` object lacks the new
attributes (e.g. older processes), defaults apply so the module is safe to
import before config lands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

DEFAULT_MAX_LABEL_LENGTH = 64
DEFAULT_MAX_SERIES_PER_METRIC = 200

#: Settings attribute names the runtime shell may expose (see
#: cygnus/runtime/config.py). Resolution is opt-in per attribute.
_TELEMETRY_ENABLED_ATTR = "telemetry_enabled"
_PROMETHEUS_ENABLED_ATTR = "prometheus_metrics_enabled"
_OTLP_ENDPOINT_ATTR = "otlp_endpoint"
_OTLP_SERVICE_NAME_ATTR = "otlp_service_name"
_MAX_LABEL_LENGTH_ATTR = "telemetry_max_label_length"
_MAX_SERIES_PER_METRIC_ATTR = "telemetry_max_series_per_metric"


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    """Bounded, secret-free observability configuration."""

    telemetry_enabled: bool = True
    prometheus_metrics_enabled: bool = True
    otlp_endpoint: Optional[str] = None
    otlp_service_name: str = "cygnus"
    max_label_length: int = DEFAULT_MAX_LABEL_LENGTH
    max_series_per_metric: int = DEFAULT_MAX_SERIES_PER_METRIC
    extra: Mapping[str, Any] = field(default_factory=dict)

    def with_overrides(self, **overrides: Any) -> "ObservabilityConfig":
        """Return a copy with validated bounded overrides applied."""
        data: dict[str, Any] = {
            "telemetry_enabled": self.telemetry_enabled,
            "prometheus_metrics_enabled": self.prometheus_metrics_enabled,
            "otlp_endpoint": self.otlp_endpoint,
            "otlp_service_name": self.otlp_service_name,
            "max_label_length": self.max_label_length,
            "max_series_per_metric": self.max_series_per_metric,
        }
        for key, value in overrides.items():
            if key not in data:
                raise ValueError(f"unknown observability override: {key}")
            if value is not None:
                data[key] = value
        return ObservabilityConfig(
            **data,
            extra=self.extra,
        )


def _resolve_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def configure_observability(
    settings: Optional[Any] = None,
    **overrides: Any,
) -> ObservabilityConfig:
    """Resolve bounded telemetry settings from runtime config or environment.

    Deployment environments may not construct the full Cygnus ``Settings``
    object (for example, a standalone worker or smoke probe), so the same
    contract is available through explicit environment variables.  A supplied
    settings object wins over environment values, and keyword overrides win
    over both.
    """
    env_names = {
        _TELEMETRY_ENABLED_ATTR: ("TELEMETRY_ENABLED", "CYGNUS_TELEMETRY_ENABLED"),
        _PROMETHEUS_ENABLED_ATTR: (
            "PROMETHEUS_METRICS_ENABLED",
            "CYGNUS_PROMETHEUS_METRICS_ENABLED",
        ),
        _OTLP_ENDPOINT_ATTR: (
            "OTLP_ENDPOINT",
            "CYGNUS_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
        ),
        _OTLP_SERVICE_NAME_ATTR: ("OTLP_SERVICE_NAME", "OTEL_SERVICE_NAME"),
        _MAX_LABEL_LENGTH_ATTR: (
            "TELEMETRY_MAX_LABEL_LENGTH",
            "CYGNUS_TELEMETRY_MAX_LABEL_LENGTH",
        ),
        _MAX_SERIES_PER_METRIC_ATTR: (
            "TELEMETRY_MAX_SERIES_PER_METRIC",
            "CYGNUS_TELEMETRY_MAX_SERIES_PER_METRIC",
        ),
    }
    source: dict[str, Any] = {}
    for attr, names in env_names.items():
        for name in names:
            if name in os.environ:
                source[attr] = os.environ[name]
                break
    if settings is not None:
        settings_values = getattr(settings, "__dict__", {})
        if settings_values:
            source.update(
                {
                    attr: settings_values[attr]
                    for attr in env_names
                    if attr in settings_values
                }
            )
        else:
            source.update(
                {
                    attr: getattr(settings, attr)
                    for attr in env_names
                    if hasattr(settings, attr)
                }
            )

    def _bool(name: str, default: bool) -> bool:
        value = source.get(name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    cfg = ObservabilityConfig(
        telemetry_enabled=_bool(_TELEMETRY_ENABLED_ATTR, True),
        prometheus_metrics_enabled=_bool(_PROMETHEUS_ENABLED_ATTR, True),
        otlp_endpoint=(
            str(source[_OTLP_ENDPOINT_ATTR]).strip() or None
            if source.get(_OTLP_ENDPOINT_ATTR)
            else None
        ),
        otlp_service_name=str(source.get(_OTLP_SERVICE_NAME_ATTR, "cygnus")),
        max_label_length=_resolve_int(
            source.get(_MAX_LABEL_LENGTH_ATTR), DEFAULT_MAX_LABEL_LENGTH
        ),
        max_series_per_metric=_resolve_int(
            source.get(_MAX_SERIES_PER_METRIC_ATTR), DEFAULT_MAX_SERIES_PER_METRIC
        ),
    )
    if overrides:
        cfg = cfg.with_overrides(**overrides)
    return cfg
