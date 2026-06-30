from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.recovery.fixtures import (
    sample_all_recovery_residual_risks,
    sample_recovery_alignment_planes,
    sample_recovery_command_refs,
    sample_reality_check_command_ref,
    sample_reality_check_feedback,
    sample_recovery_metrics_after,
    sample_recovery_metrics_before,
    sample_recovery_residual_risks,
)
from cygnus.recovery.providers import build_downstream_reality_check, build_recovery_window
from cygnus.recovery.providers import build_governance_overview
from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    GovernanceCommandRef,
)
from cygnus.recovery.overview import GovernanceOverviewSurface
from cygnus.recovery.window import (
    AlignmentPlaneChange,
    RecoveryMetricSnapshot,
    RecoveryWindowSurface,
    ResidualRisk,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DownstreamRealityCheckQuery:
    command_id: str

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryWindowQuery:
    command_id: str

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceOverviewQuery:
    command_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(command_id.strip() for command_id in self.command_ids if command_id.strip())
        if not normalized:
            raise ValueError("command_ids must not be empty")
        object.__setattr__(self, "command_ids", normalized)


def get_downstream_reality_check_surface(
    query: DownstreamRealityCheckQuery,
    *,
    command_refs: Iterable[GovernanceCommandRef] | None = None,
    feedback_feed: Iterable[DownstreamFeedbackSignal] | None = None,
) -> DownstreamRealityCheckSurface:
    refs = tuple(command_refs) if command_refs is not None else (sample_reality_check_command_ref(),)
    feed = tuple(feedback_feed) if feedback_feed is not None else sample_reality_check_feedback()
    for command_ref in refs:
        if command_ref.command_id != query.command_id:
            continue
        return build_downstream_reality_check(
            command_ref=command_ref,
            feedback_feed=feed,
        )
    raise ValueError(f"downstream reality check not found for command_id={query.command_id}")


def get_recovery_window_surface(
    query: RecoveryWindowQuery,
    *,
    command_refs: Iterable[GovernanceCommandRef] | None = None,
    before_metrics: Iterable[RecoveryMetricSnapshot] | None = None,
    after_metrics: Iterable[RecoveryMetricSnapshot] | None = None,
    alignment_planes: Iterable[AlignmentPlaneChange] | None = None,
    residual_risks: Iterable[ResidualRisk] | None = None,
) -> RecoveryWindowSurface:
    refs = tuple(command_refs) if command_refs is not None else sample_recovery_command_refs()
    before = (
        tuple(before_metrics)
        if before_metrics is not None
        else sample_recovery_metrics_before(command_id=query.command_id)
    )
    after = (
        tuple(after_metrics)
        if after_metrics is not None
        else sample_recovery_metrics_after(command_id=query.command_id)
    )
    planes = (
        tuple(alignment_planes)
        if alignment_planes is not None
        else sample_recovery_alignment_planes(command_id=query.command_id)
    )
    residuals = (
        tuple(residual_risks)
        if residual_risks is not None
        else sample_recovery_residual_risks(command_id=query.command_id)
    )
    for command_ref in refs:
        if command_ref.command_id != query.command_id:
            continue
        return build_recovery_window(
            command_ref=command_ref,
            before_metrics=before,
            after_metrics=after,
            alignment_planes=planes,
            residual_risks=residuals,
        )
    raise ValueError(f"recovery window not found for command_id={query.command_id}")


def get_governance_overview_surface(
    query: GovernanceOverviewQuery,
    *,
    command_refs: Iterable[GovernanceCommandRef] | None = None,
    recovery_windows: Iterable[RecoveryWindowSurface] | None = None,
    residual_risks: Iterable[ResidualRisk] | None = None,
) -> GovernanceOverviewSurface:
    refs = tuple(command_refs) if command_refs is not None else sample_recovery_command_refs()
    filtered_refs = tuple(ref for ref in refs if ref.command_id in query.command_ids)
    if not filtered_refs:
        raise ValueError("governance overview not found for the requested command_ids")

    windows = tuple(recovery_windows) if recovery_windows is not None else tuple(
        get_recovery_window_surface(
            RecoveryWindowQuery(command_id=ref.command_id),
            command_refs=filtered_refs,
        )
        for ref in filtered_refs
    )
    filtered_windows = tuple(
        window for window in windows if window.command_ref.command_id in query.command_ids
    )
    if not filtered_windows:
        raise ValueError("governance overview requires at least one matching recovery window")

    residuals = (
        tuple(residual_risks)
        if residual_risks is not None
        else sample_all_recovery_residual_risks()
    )
    return build_governance_overview(
        command_refs=filtered_refs,
        recovery_windows=filtered_windows,
        residual_risks=tuple(risk for risk in residuals if risk.command_id in query.command_ids),
    )


def get_default_governance_overview_surface(
    *,
    command_refs: Iterable[GovernanceCommandRef] | None = None,
    recovery_windows: Iterable[RecoveryWindowSurface] | None = None,
    residual_risks: Iterable[ResidualRisk] | None = None,
) -> GovernanceOverviewSurface:
    refs = tuple(command_refs) if command_refs is not None else sample_recovery_command_refs()
    return get_governance_overview_surface(
        GovernanceOverviewQuery(command_ids=tuple(ref.command_id for ref in refs)),
        command_refs=refs,
        recovery_windows=recovery_windows,
        residual_risks=residual_risks,
    )
