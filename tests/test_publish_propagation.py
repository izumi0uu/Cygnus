from __future__ import annotations

import unittest

from cygnus.domain import AnswerCard, AudienceFilter, AudienceVariant, Visibility
from cygnus.publish import (
    PropagationStatus,
    PublishActionType,
    PublishGovernanceAction,
    PublishGovernanceActionType,
    SurfacePropagationUpdate,
    apply_publish_governance_actions,
    build_publish_preview_candidate,
    build_publish_propagation_ledger,
)


class PublishPropagationLedgerTests(unittest.TestCase):
    def test_ledger_reports_surface_states_and_follow_up_commands(self) -> None:
        external = AudienceFilter(visibility=Visibility.EXTERNAL, product_lines=("billing",))
        internal = AudienceFilter(visibility=Visibility.INTERNAL, product_lines=("billing",))
        enterprise_eu = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
        )
        answer = AnswerCard(
            object_id="ac-prop-1",
            title="Refund routing",
            summary="Controls how refund messaging propagates after governance review.",
            question="Can I refund this subscription?",
            canonical_answer="Refund handling depends on plan and contract type.",
            publish_targets=("help_center", "copilot"),
            supported_audiences=(external, internal),
            audience_variants=(
                AudienceVariant(
                    audience_filter=enterprise_eu,
                    label="enterprise-eu",
                    content="Enterprise EU requires manual sign-off before customer-facing propagation.",
                ),
            ),
        )
        base_candidate = build_publish_preview_candidate(answer, action_type=PublishActionType.PUBLISH)
        candidate = build_publish_preview_candidate(
            answer,
            action_type=PublishActionType.PUBLISH,
            current_bindings=tuple(base_candidate.target_bindings),
        )
        governance_result = apply_publish_governance_actions(
            candidate,
            (
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.RESTRICT,
                    audiences=(external,),
                    channels=("help_center",),
                    reason="customer-facing help-center update is paused pending policy wording correction",
                ),
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.HOLD_EXTERNAL,
                    audiences=(enterprise_eu,),
                    channels=("copilot",),
                    reason="enterprise-eu path requires manual publish confirmation",
                ),
            ),
        )

        ledger = build_publish_propagation_ledger(
            governance_result,
            supporting_surfaces=("review_queue", "feedback", "queue_sidebar"),
            surface_updates=(
                SurfacePropagationUpdate(
                    surface_id="copilot",
                    status=PropagationStatus.SYNCED,
                    reason="Internal copilot indices and runtime hints have already been updated.",
                    channel_refs=("copilot",),
                    follow_up_commands=("open_copilot_snapshot",),
                ),
                SurfacePropagationUpdate(
                    surface_id="review_queue",
                    status=PropagationStatus.FAILED,
                    reason="Review queue rerank webhook timed out before downstream confirmation.",
                    follow_up_commands=("retry_review_queue_sync",),
                ),
                SurfacePropagationUpdate(
                    surface_id="feedback",
                    status=PropagationStatus.MANUAL_ACTION_REQUIRED,
                    reason="Feedback monitor still needs a human to confirm if old wording is appearing in live sessions.",
                    follow_up_commands=("inspect_feedback_sessions",),
                ),
            ),
        ).to_dict()

        self.assertEqual(
            ledger["summary"],
            {
                "synced": 1,
                "pending": 2,
                "failed": 1,
                "manual_action_required": 1,
            },
        )
        record_map = {record["surface_id"]: record for record in ledger["records"]}
        self.assertEqual(record_map["copilot"]["status"], "synced")
        self.assertEqual(record_map["review_queue"]["status"], "failed")
        self.assertEqual(record_map["feedback"]["status"], "manual_action_required")
        self.assertEqual(record_map["help_center"]["status"], "pending")
        self.assertEqual(record_map["queue_sidebar"]["status"], "pending")
        self.assertIn("retry_review_queue_sync", ledger["continue_commands"])
        self.assertIn("inspect_feedback_sessions", ledger["continue_commands"])

    def test_default_channel_record_uses_manual_action_when_hold_exists(self) -> None:
        external = AudienceFilter(visibility=Visibility.EXTERNAL, product_lines=("billing",))
        enterprise_eu = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
        )
        answer = AnswerCard(
            object_id="ac-prop-2",
            title="Enterprise export rollout",
            summary="Tracks external rollout holds for EU enterprise customers.",
            question="Can enterprise EU customers export invoices?",
            canonical_answer="Availability depends on rollout verification.",
            publish_targets=("copilot",),
            supported_audiences=(external,),
            audience_variants=(
                AudienceVariant(
                    audience_filter=enterprise_eu,
                    label="enterprise-eu",
                    content="Enterprise EU rollout stays gated until sign-off.",
                ),
            ),
        )
        base_candidate = build_publish_preview_candidate(answer, action_type=PublishActionType.REPUBLISH)
        governance_result = apply_publish_governance_actions(
            build_publish_preview_candidate(
                answer,
                action_type=PublishActionType.REPUBLISH,
                current_bindings=tuple(base_candidate.target_bindings),
            ),
            (
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.HOLD_EXTERNAL,
                    audiences=(enterprise_eu,),
                    channels=("copilot",),
                    reason="enterprise-eu still needs release manager sign-off",
                ),
            ),
        )

        ledger = build_publish_propagation_ledger(governance_result).to_dict()
        record_map = {record["surface_id"]: record for record in ledger["records"]}
        self.assertEqual(record_map["copilot"]["status"], "manual_action_required")
        self.assertIn("resolve_surface_hold", record_map["copilot"]["follow_up_commands"])


if __name__ == "__main__":
    unittest.main()
