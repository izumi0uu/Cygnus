from __future__ import annotations

from typing import Iterable

from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    GovernanceCommandRef,
    build_downstream_reality_check_surface,
)
from cygnus.recovery.window import (
    AlignmentPlaneChange,
    RecoveryMetricSnapshot,
    RecoveryWindowSurface,
    ResidualRisk,
    build_recovery_window_surface,
)


def build_downstream_reality_check(
    *,
    command_ref: GovernanceCommandRef,
    feedback_feed: Iterable[DownstreamFeedbackSignal],
) -> DownstreamRealityCheckSurface:
    return build_downstream_reality_check_surface(
        command_ref=command_ref,
        feedback_feed=feedback_feed,
    )


def build_recovery_window(
    *,
    command_ref: GovernanceCommandRef,
    before_metrics: Iterable[RecoveryMetricSnapshot],
    after_metrics: Iterable[RecoveryMetricSnapshot],
    alignment_planes: Iterable[AlignmentPlaneChange],
    residual_risks: Iterable[ResidualRisk],
) -> RecoveryWindowSurface:
    return build_recovery_window_surface(
        command_ref=command_ref,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        alignment_planes=alignment_planes,
        residual_risks=residual_risks,
    )
