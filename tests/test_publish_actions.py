from __future__ import annotations

import unittest

from cygnus.domain import AnswerCard, AudienceFilter, AudienceVariant, Visibility
from cygnus.publish import (
    BlastRadiusEffect,
    PublishActionType,
    PublishBinding,
    PublishGovernanceAction,
    PublishGovernanceActionType,
    apply_publish_governance_actions,
    build_publish_preview_candidate,
)


class PublishGovernanceActionTests(unittest.TestCase):
    def test_governance_actions_support_partial_open_restrict_and_hold(self) -> None:
        external = AudienceFilter(visibility=Visibility.EXTERNAL, product_lines=("billing",))
        internal = AudienceFilter(visibility=Visibility.INTERNAL, product_lines=("billing",))
        enterprise_eu = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
        )
        answer = AnswerCard(
            object_id="ac-action-1",
            title="Refund answer",
            summary="Controls external and internal refund messaging.",
            question="Can I refund this account?",
            canonical_answer="Refund eligibility depends on plan and contract.",
            publish_targets=("help_center", "copilot"),
            supported_audiences=(external, internal),
            audience_variants=(
                AudienceVariant(
                    audience_filter=enterprise_eu,
                    label="enterprise-eu",
                    content="Enterprise EU refund wording requires separate handling.",
                ),
            ),
        )
        candidate = build_publish_preview_candidate(answer, action_type=PublishActionType.PUBLISH)
        candidate = build_publish_preview_candidate(
            answer,
            action_type=PublishActionType.PUBLISH,
            current_bindings=tuple(candidate.target_bindings),
        )

        result = apply_publish_governance_actions(
            candidate,
            (
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.RESTRICT,
                    audiences=(external,),
                    channels=("help_center",),
                    reason="keep external help-center exposure closed while policy wording is corrected",
                ),
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.HOLD_EXTERNAL,
                    audiences=(enterprise_eu,),
                    channels=("copilot",),
                    reason="enterprise-eu path needs manual sign-off",
                ),
            ),
        ).to_dict()

        effects = {(impact["audience_label"], impact["channel"]): impact["effect"] for impact in result["preview"]["impacts"]}
        self.assertEqual(effects[("external · billing", "help_center")], BlastRadiusEffect.STOPPED_EXPOSURE.value)
        self.assertEqual(effects[("internal · billing", "help_center")], BlastRadiusEffect.CONTINUING_EXPOSURE.value)
        self.assertEqual(effects[("external · billing · enterprise · eu", "copilot")], BlastRadiusEffect.CONFLICT.value)
        self.assertIn("hold_external:enterprise-eu path needs manual sign-off", result["action_log"])

    def test_split_variant_opens_new_binding_without_binary_approval(self) -> None:
        external = AudienceFilter(visibility=Visibility.EXTERNAL, product_lines=("billing",))
        enterprise_eu = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
        )
        answer = AnswerCard(
            object_id="ac-action-2",
            title="Invoice export answer",
            summary="Controls rollout-safe invoice export guidance.",
            question="How do I export an invoice?",
            canonical_answer="Use Billing > Invoices.",
            publish_targets=("copilot",),
            supported_audiences=(external,),
        )
        candidate = build_publish_preview_candidate(answer, action_type=PublishActionType.REPUBLISH)

        result = apply_publish_governance_actions(
            candidate,
            (
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.SPLIT_VARIANT,
                    audiences=(enterprise_eu,),
                    channels=("copilot",),
                    reason="add enterprise-eu as a separately governed rollout path",
                ),
            ),
        ).to_dict()

        self.assertEqual(len(result["opened_bindings"]), 1)
        self.assertEqual(result["opened_bindings"][0]["audience_label"], "external · billing · enterprise · eu")
        self.assertEqual(result["opened_bindings"][0]["channel"], "copilot")

    def test_republish_internal_only_removes_external_paths(self) -> None:
        external = AudienceFilter(visibility=Visibility.EXTERNAL, product_lines=("billing",))
        internal = AudienceFilter(visibility=Visibility.INTERNAL, product_lines=("billing",))
        candidate = build_publish_preview_candidate(
            AnswerCard(
                object_id="ac-action-3",
                title="Known issue response",
                summary="Temporarily restricts customer-facing known issue messaging.",
                question="Why is invoice export delayed?",
                canonical_answer="Invoice export delays are being investigated.",
                publish_targets=("help_center", "copilot"),
                supported_audiences=(external, internal),
            ),
            action_type=PublishActionType.RESTRICT,
            current_bindings=(
                PublishBinding(audience_filter=external, channel="help_center"),
                PublishBinding(audience_filter=external, channel="copilot"),
                PublishBinding(audience_filter=internal, channel="copilot"),
            ),
        )

        result = apply_publish_governance_actions(
            candidate,
            (
                PublishGovernanceAction(
                    action_type=PublishGovernanceActionType.REPUBLISH_INTERNAL_ONLY,
                    reason="customer-facing propagation is paused while internal guidance stays live",
                ),
            ),
        ).to_dict()

        preview_impacts = result["preview"]["impacts"]
        self.assertTrue(all(impact["audience_filter"]["visibility"] == "internal" for impact in preview_impacts if impact["effect"] != "stopped_exposure"))
        self.assertEqual(len(result["removed_bindings"]), 2)


if __name__ == "__main__":
    unittest.main()
