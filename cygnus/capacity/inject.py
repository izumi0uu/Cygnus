"""Staging-safe failure injection and recovery evidence (CYG-142).

Fault injection is fail-closed: it requires three independent
confirmations -- the config environment is ``staging``, the deployment
config explicitly enables injection, and the runtime environment variable
``CYGNUS_CAPACITY_GATE_INJECTION=1`` is present. Recovery evidence is a
required input to a PASS verdict; a gate that never exercised faults
cannot certify production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from cygnus.capacity.metrics import _optional_float, _required_float, _required_int
from cygnus.capacity.schema import (
    ENVIRONMENT_NOT_STAGING,
    ENVIRONMENT_STAGING,
    HARD_MAX_INJECTION_WINDOW_SECONDS,
    INJECTION_NOT_EXERCISED,
    INJECTION_TARGETS,
    InjectionTarget,
)


class InjectionNotSupported(RuntimeError):
    """A route target cannot inject the requested fault on this deployment."""


@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionScenario:
    """One bounded fault window against one dependency, on one route."""

    target: InjectionTarget
    duration_seconds: float
    post_recovery_seconds: float

    def __post_init__(self) -> None:
        if self.target not in INJECTION_TARGETS:
            raise ValueError(f"unknown injection target: {self.target}")
        if not 1.0 <= self.duration_seconds <= HARD_MAX_INJECTION_WINDOW_SECONDS:
            raise ValueError(
                "duration_seconds must be within "
                f"[1.0, {HARD_MAX_INJECTION_WINDOW_SECONDS:g}]"
            )
        if self.post_recovery_seconds < 1.0:
            raise ValueError("post_recovery_seconds must be >= 1.0")


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryEvidence:
    """What the gate observed around one bounded fault window."""

    target: InjectionTarget
    injected: bool
    window_seconds: float
    failures_during_window: int
    recovery_seconds: float | None
    post_recovery_error_rate: float
    recovered: bool
    detail: str

    def __post_init__(self) -> None:
        if self.target not in INJECTION_TARGETS:
            raise ValueError(f"unknown injection target: {self.target}")
        if self.post_recovery_error_rate < 0.0:
            raise ValueError("post_recovery_error_rate must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "injected": self.injected,
            "window_seconds": round(self.window_seconds, 3),
            "failures_during_window": self.failures_during_window,
            "recovery_seconds": (
                None
                if self.recovery_seconds is None
                else round(self.recovery_seconds, 3)
            ),
            "post_recovery_error_rate": round(self.post_recovery_error_rate, 6),
            "recovered": self.recovered,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "RecoveryEvidence":
        try:
            target = raw["target"]
            if not isinstance(target, str):
                raise ValueError(f"invalid injection target: {target!r}")
            if target not in INJECTION_TARGETS:
                raise ValueError(f"invalid injection target: {target!r}")
            return cls(
                target=target,
                injected=bool(raw["injected"]),
                window_seconds=_required_float(raw, "window_seconds"),
                failures_during_window=_required_int(raw, "failures_during_window"),
                recovery_seconds=_optional_float(raw.get("recovery_seconds")),
                post_recovery_error_rate=_required_float(
                    raw, "post_recovery_error_rate"
                ),
                recovered=bool(raw["recovered"]),
                detail=str(raw["detail"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid recovery evidence: {exc}") from exc


class StagingGuard:
    """Fail-closed gate deciding whether fault injection may run."""

    def __init__(
        self,
        *,
        environment: str,
        config_enabled: bool,
        runtime_confirmed: bool,
    ) -> None:
        self.environment = environment
        self.config_enabled = config_enabled
        self.runtime_confirmed = runtime_confirmed

    @property
    def allowed(self) -> bool:
        return (
            self.environment == ENVIRONMENT_STAGING
            and self.config_enabled
            and self.runtime_confirmed
        )

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.environment != ENVIRONMENT_STAGING:
            reasons.append(ENVIRONMENT_NOT_STAGING)
        if not self.config_enabled or not self.runtime_confirmed:
            reasons.append(INJECTION_NOT_EXERCISED)
        return tuple(reasons)
