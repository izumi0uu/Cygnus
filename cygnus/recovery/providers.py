from __future__ import annotations

from typing import Iterable

from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    GovernanceCommandRef,
    build_downstream_reality_check_surface,
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
