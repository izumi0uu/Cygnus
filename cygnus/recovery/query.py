from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.recovery.fixtures import (
    sample_recovery_alignment_planes,
    sample_reality_check_command_ref,
    sample_reality_check_feedback,
    sample_recovery_metrics_after,
    sample_recovery_metrics_before,
    sample_recovery_residual_risks,
)
from cygnus.recovery.providers import build_downstream_reality_check, build_recovery_window
from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    GovernanceCommandRef,
)
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
    refs = tuple(command_refs) if command_refs is not None else (sample_reality_check_command_ref(),)
    before = tuple(before_metrics) if before_metrics is not None else sample_recovery_metrics_before()
    after = tuple(after_metrics) if after_metrics is not None else sample_recovery_metrics_after()
    planes = tuple(alignment_planes) if alignment_planes is not None else sample_recovery_alignment_planes()
    residuals = tuple(residual_risks) if residual_risks is not None else sample_recovery_residual_risks()
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
