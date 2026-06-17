from __future__ import annotations

from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    FeedbackSignalType,
    GovernanceCommandRef,
)
from cygnus.recovery.window import (
    AlignmentPlaneChange,
    RecoveryMetricSnapshot,
    ResidualRisk,
    TruthPlaneState,
)


def sample_reality_check_command_ref() -> GovernanceCommandRef:
    return GovernanceCommandRef(
        command_id="cmd-publish-1",
        command_type="publish",
        object_id="ko-invoice-export-enterprise-eu",
        object_title="Invoice export answer",
        issued_by="support-lead",
        issued_at="2026-06-16T09:30:00Z",
        rationale="Release wording was updated and frontline behavior must converge before the next queue spike.",
        affected_surfaces=("copilot", "macro", "queue_sidebar"),
    )


def sample_reality_check_feedback() -> tuple[DownstreamFeedbackSignal, ...]:
    command_ref = sample_reality_check_command_ref()
    return (
        DownstreamFeedbackSignal(
            signal_id="sig-accepted-1",
            surface_id="copilot",
            signal_type=FeedbackSignalType.COPILOT_ACCEPTED,
            command_ref=command_ref,
            audience_label="external · billing · enterprise · eu",
            session_ref="sess-copilot-1",
            summary="The refreshed billing answer is now being accepted without manual rewrite in the copilot panel.",
            changed_behavior="copilot suggestion now matches the governed invoice export path",
            event_at="2026-06-16T09:42:00Z",
            queue_owner="support-ops",
            source_refs=("release/2026-06-09-eu-billing",),
            follow_up_actions=("open_recovery_window",),
        ),
        DownstreamFeedbackSignal(
            signal_id="sig-rewrite-1",
            surface_id="macro",
            signal_type=FeedbackSignalType.HUMAN_REWRITE,
            command_ref=command_ref,
            audience_label="external · billing · enterprise · eu",
            session_ref="sess-macro-1",
            summary="Agents are still rewriting the macro for legacy EU rollout wording.",
            changed_behavior="human rewrite remains necessary before the message can be sent",
            event_at="2026-06-16T09:39:00Z",
            queue_owner="knowledge-manager",
            source_refs=("macro/invoice-export-eu",),
            follow_up_actions=("route_macro_fix_to_review",),
        ),
        DownstreamFeedbackSignal(
            signal_id="sig-escalate-1",
            surface_id="queue_sidebar",
            signal_type=FeedbackSignalType.ESCALATION_AFTER_SUGGESTION,
            command_ref=command_ref,
            audience_label="external · billing · free · us",
            session_ref="sess-queue-1",
            summary="Queue sidebar still routes free-plan users into the enterprise escalation path.",
            changed_behavior="escalation remains above baseline after the governance command",
            event_at="2026-06-16T09:35:00Z",
            queue_owner="escalation-lead",
            source_refs=("queue/sidebar-routing",),
            follow_up_actions=("open_audience_mismatch_review",),
        ),
        DownstreamFeedbackSignal(
            signal_id="sig-unresolved-1",
            surface_id="copilot",
            signal_type=FeedbackSignalType.UNRESOLVED_CONVERSATION,
            command_ref=command_ref,
            audience_label="external · billing · free · us",
            session_ref="sess-copilot-2",
            summary="A free-plan conversation remains unresolved after the suggestion and fell back to manual handling.",
            changed_behavior="conversation still requires manual takeover",
            event_at="2026-06-16T09:33:00Z",
            source_refs=("conversation/free-us-1",),
            follow_up_actions=("inspect_unresolved_sessions",),
        ),
    )


def sample_recovery_metrics_before() -> tuple[RecoveryMetricSnapshot, ...]:
    return (
        RecoveryMetricSnapshot(
            metric_key="rewrite_count",
            label="Rewrite Delta",
            value=11,
            explanation="Manual rewrites were still common before the publish command.",
        ),
        RecoveryMetricSnapshot(
            metric_key="drift_count",
            label="Drift Delta",
            value=4,
            explanation="Multiple downstream surfaces were still carrying stale billing wording.",
        ),
        RecoveryMetricSnapshot(
            metric_key="escalation_count",
            label="Escalation Delta",
            value=7,
            explanation="Escalations stayed above baseline before the latest command was issued.",
        ),
        RecoveryMetricSnapshot(
            metric_key="coverage_gap_count",
            label="Coverage Gap Delta",
            value=3,
            explanation="Three audience branches still lacked governed support coverage.",
        ),
        RecoveryMetricSnapshot(
            metric_key="publish_conflict_count",
            label="Publish Conflict Delta",
            value=2,
            explanation="Internal and external surfaces still disagreed on the latest governed wording.",
        ),
    )


def sample_recovery_metrics_after() -> tuple[RecoveryMetricSnapshot, ...]:
    return (
        RecoveryMetricSnapshot(
            metric_key="rewrite_count",
            label="Rewrite Delta",
            value=5,
            explanation="Rewrites dropped after the publish command but have not disappeared.",
        ),
        RecoveryMetricSnapshot(
            metric_key="drift_count",
            label="Drift Delta",
            value=2,
            explanation="Drift pressure dropped, but two surfaces still trail the latest truth.",
        ),
        RecoveryMetricSnapshot(
            metric_key="escalation_count",
            label="Escalation Delta",
            value=3,
            explanation="Escalations improved, though free-plan routing is still above target.",
        ),
        RecoveryMetricSnapshot(
            metric_key="coverage_gap_count",
            label="Coverage Gap Delta",
            value=2,
            explanation="One coverage gap closed, but not enough to call the cycle fully recovered.",
        ),
        RecoveryMetricSnapshot(
            metric_key="publish_conflict_count",
            label="Publish Conflict Delta",
            value=1,
            explanation="Most publish conflict is gone, yet one split-brain surface remains.",
        ),
    )


def sample_recovery_alignment_planes() -> tuple[AlignmentPlaneChange, ...]:
    return (
        AlignmentPlaneChange(
            plane_key="object_truth",
            label="Object Truth",
            before_state=TruthPlaneState.MISALIGNED,
            after_state=TruthPlaneState.ALIGNED,
            before_score=0.34,
            after_score=0.91,
        ),
        AlignmentPlaneChange(
            plane_key="audience_truth",
            label="Audience Truth",
            before_state=TruthPlaneState.MISALIGNED,
            after_state=TruthPlaneState.PARTIAL,
            before_score=0.22,
            after_score=0.58,
            residual_reasons=(
                "Free-plan US routing still points to the enterprise escalation path.",
            ),
        ),
        AlignmentPlaneChange(
            plane_key="publish_truth",
            label="Publish Truth",
            before_state=TruthPlaneState.SPLIT_BRAIN,
            after_state=TruthPlaneState.SPLIT_BRAIN,
            before_score=0.41,
            after_score=0.56,
            residual_reasons=(
                "Macro wording still lags the published external answer.",
            ),
        ),
        AlignmentPlaneChange(
            plane_key="coverage_truth",
            label="Coverage Truth",
            before_state=TruthPlaneState.PARTIAL,
            after_state=TruthPlaneState.PARTIAL,
            before_score=0.43,
            after_score=0.62,
            residual_reasons=(
                "Free-plan billing exception handling is still under-covered.",
            ),
        ),
    )


def sample_recovery_residual_risks() -> tuple[ResidualRisk, ...]:
    return (
        ResidualRisk(
            risk_id="risk-audience-free-us",
            label="Free-plan US audience mismatch remains open",
            severity="elevated",
            truth_plane="audience_truth",
            summary="Queue routing still sends free-plan billing users into an enterprise escalation path.",
            acceptable_residual=False,
            recommended_command="open_audience_mismatch_review",
            owner="support-ops",
            blocking_surface="queue_sidebar",
            evidence_refs=("conversation/free-us-1", "queue/sidebar-routing"),
        ),
        ResidualRisk(
            risk_id="risk-publish-macro-eu",
            label="Macro surface still shows split-brain publish behavior",
            severity="emerging",
            truth_plane="publish_truth",
            summary="The internal macro still uses legacy EU rollout wording even after the publish command.",
            acceptable_residual=False,
            recommended_command="route_macro_fix_to_review",
            owner="knowledge-manager",
            blocking_surface="macro",
            evidence_refs=("macro/invoice-export-eu",),
        ),
        ResidualRisk(
            risk_id="risk-coverage-free-us",
            label="Free-plan billing exception coverage is still thin",
            severity="watch",
            truth_plane="coverage_truth",
            summary="Coverage improved, but one low-volume branch still lacks a stable governed answer.",
            acceptable_residual=True,
            recommended_command="monitor_free_plan_coverage",
            owner="support-lead",
            blocking_surface="copilot",
            evidence_refs=("coverage/free-us-billing",),
        ),
    )
