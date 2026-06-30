"""Governance control-plane recovery modules for Cygnus.

Ownership:
- downstream reality check, governance overview, recovery window, and recovery proof surfaces live here
- this package owns governance recovery semantics, not runtime app-shell wiring
"""

from cygnus.recovery.fixtures import (
    sample_all_recovery_residual_risks,
    sample_recovery_alignment_planes,
    sample_recovery_command_refs,
    sample_recovery_metrics_after,
    sample_recovery_metrics_before,
    sample_recovery_residual_risks,
    sample_restrict_command_ref,
    sample_reality_check_command_ref,
    sample_reality_check_feedback,
)
from cygnus.recovery.providers import (
    build_downstream_reality_check,
    build_governance_overview,
    build_recovery_window,
)
from cygnus.recovery.query import (
    DownstreamRealityCheckQuery,
    GovernanceOverviewQuery,
    RecoveryWindowQuery,
    get_downstream_reality_check_surface,
    get_default_governance_overview_surface,
    get_governance_overview_surface,
    get_recovery_window_surface,
)
from cygnus.recovery.overview import (
    GovernanceOverviewSurface,
    OpenLoopComparisonRow,
    OpenLoopRank,
    build_governance_overview_surface,
)
from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    FeedbackSignalType,
    GovernanceCommandRef,
    MismatchByAudience,
    RealityCheckStrip,
    build_downstream_reality_check_surface,
)
from cygnus.recovery.proof import (
    RecoveryBehaviorType,
    RecoveryProofSurface,
    RecoveryProofWindow,
    RecoverySignal,
    RecoverySignalStatus,
    get_pressure_intake_recovery_proof_surface,
)
from cygnus.recovery.window import (
    AlignmentPlaneChange,
    BeforeAfterAlignmentView,
    ClosureJudge,
    RecoveryAssessment,
    RecoveryDecision,
    RecoveryMetricDelta,
    RecoveryMetricSnapshot,
    RecoveryWindowSurface,
    ResidualRisk,
    TruthPlaneState,
    build_recovery_window_surface,
)

__all__ = [
    "AlignmentPlaneChange",
    "BeforeAfterAlignmentView",
    "ClosureJudge",
    "DownstreamFeedbackSignal",
    "DownstreamRealityCheckQuery",
    "DownstreamRealityCheckSurface",
    "FeedbackSignalType",
    "GovernanceCommandRef",
    "MismatchByAudience",
    "RealityCheckStrip",
    "build_downstream_reality_check",
    "build_downstream_reality_check_surface",
    "build_governance_overview",
    "build_governance_overview_surface",
    "build_recovery_window",
    "build_recovery_window_surface",
    "get_downstream_reality_check_surface",
    "get_default_governance_overview_surface",
    "get_governance_overview_surface",
    "get_recovery_window_surface",
    "GovernanceOverviewQuery",
    "GovernanceOverviewSurface",
    "OpenLoopComparisonRow",
    "OpenLoopRank",
    "RecoveryAssessment",
    "RecoveryDecision",
    "RecoveryMetricDelta",
    "RecoveryMetricSnapshot",
    "RecoveryWindowQuery",
    "RecoveryWindowSurface",
    "ResidualRisk",
    "RecoveryBehaviorType",
    "RecoveryProofSurface",
    "RecoveryProofWindow",
    "RecoverySignal",
    "RecoverySignalStatus",
    "sample_all_recovery_residual_risks",
    "TruthPlaneState",
    "sample_recovery_alignment_planes",
    "sample_recovery_command_refs",
    "sample_recovery_metrics_after",
    "sample_recovery_metrics_before",
    "sample_recovery_residual_risks",
    "sample_restrict_command_ref",
    "sample_reality_check_command_ref",
    "sample_reality_check_feedback",
    "get_pressure_intake_recovery_proof_surface",
]
