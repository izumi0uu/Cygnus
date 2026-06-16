from __future__ import annotations

from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    FeedbackSignalType,
    GovernanceCommandRef,
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
