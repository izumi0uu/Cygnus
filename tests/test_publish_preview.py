from __future__ import annotations

import unittest
from typing import cast

from cygnus.domain import AnswerCard, AudienceFilter, AudienceVariant, Visibility
from cygnus.publish import (
    BlastRadiusEffect,
    PublishActionType,
    PublishBinding,
    PublishConflict,
    build_publish_blast_radius_preview,
    build_publish_preview_candidate,
)


class PublishPreviewTests(unittest.TestCase):
    def test_candidate_uses_answer_card_targets_and_variants(self) -> None:
        answer = AnswerCard(
            object_id="ac-pub-1",
            title="Invoice export",
            summary="Explains where invoice export is available.",
            question="How do I export invoices?",
            canonical_answer="Open Billing > Invoices.",
            publish_targets=("help_center", "copilot"),
            supported_audiences=(
                AudienceFilter(
                    visibility=Visibility.EXTERNAL,
                    product_lines=("billing",),
                ),
            ),
            audience_variants=(
                AudienceVariant(
                    audience_filter=AudienceFilter(
                        visibility=Visibility.EXTERNAL,
                        product_lines=("billing",),
                        plans=("enterprise",),
                        regions=("eu",),
                    ),
                    label="enterprise-eu",
                    content="EU enterprise workspaces may require invoice export rollout confirmation.",
                ),
            ),
        )

        candidate = build_publish_preview_candidate(
            answer,
            action_type=PublishActionType.PUBLISH,
        ).to_dict()

        target_audiences = cast(list[dict[str, object]], candidate["target_audiences"])
        self.assertEqual(candidate["target_channels"], ["help_center", "copilot"])
        self.assertEqual(len(target_audiences), 2)

    def test_preview_distinguishes_new_continue_stop_and_conflict(self) -> None:
        canonical = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
        )
        enterprise_eu = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
        )
        answer = AnswerCard(
            object_id="ac-pub-2",
            title="Refund exception routing",
            summary="Shows which customers can use self-serve refunds.",
            question="Can I refund this subscription?",
            canonical_answer="Refund eligibility depends on plan and contract type.",
            publish_targets=("help_center", "copilot"),
            supported_audiences=(canonical,),
            audience_variants=(
                AudienceVariant(
                    audience_filter=enterprise_eu,
                    label="enterprise-eu",
                    content="Enterprise EU contracts require manual review before refund messaging is shown.",
                ),
            ),
        )

        candidate = build_publish_preview_candidate(
            answer,
            action_type=PublishActionType.REPUBLISH,
            current_bindings=(
                PublishBinding(audience_filter=canonical, channel="help_center"),
                PublishBinding(audience_filter=enterprise_eu, channel="macro"),
            ),
            blocked_bindings=(
                PublishConflict(
                    audience_filter=enterprise_eu,
                    channel="help_center",
                    reason="Enterprise EU wording is still pending policy sign-off.",
                ),
            ),
        )

        preview = build_publish_blast_radius_preview(candidate).to_dict()

        impacts = cast(list[dict[str, object]], preview["impacts"])
        effects: set[str] = {cast(str, impact["effect"]) for impact in impacts}
        self.assertEqual(
            effects,
            {
                BlastRadiusEffect.NEW_EXPOSURE.value,
                BlastRadiusEffect.CONTINUING_EXPOSURE.value,
                BlastRadiusEffect.STOPPED_EXPOSURE.value,
                BlastRadiusEffect.CONFLICT.value,
            },
        )
        audience_scope = cast(dict[str, object], preview["audience_scope"])
        self.assertEqual(audience_scope["total_audiences"], 2)
        gate_matrix = cast(list[dict[str, object]], preview["channel_gate_matrix"])
        self.assertEqual(gate_matrix[0]["channel"], "help_center")
        warnings = cast(list[str], preview["warnings"])
        self.assertIn(
            "At least one audience-channel path is blocked by a governance conflict.",
            warnings,
        )
        self.assertIn(
            "This command would remove at least one current exposure path.",
            warnings,
        )


if __name__ == "__main__":
    unittest.main()
