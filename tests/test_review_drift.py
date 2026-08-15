from __future__ import annotations

import unittest
from typing import cast

from cygnus.review import (
    DriftGovernanceCommand,
    DriftGovernanceCommandType,
    apply_drift_governance_commands,
    get_drift_governance_surface,
)


class ReviewDriftTests(unittest.TestCase):
    def test_get_drift_governance_surface_exposes_direct_drift_commands(self) -> None:
        payload = get_drift_governance_surface().to_dict()
        self.assertEqual(payload["surface_id"], "drift-governance")
        available_commands = cast(list[str], payload["available_commands"])
        self.assertIn("open_urgent_review", available_commands)
        self.assertIn("freeze_external_publish", available_commands)
        context = cast(list[dict[str, object]], payload["contexts"])[0]
        self.assertEqual(context["proposal_ref"], "cp-drift-1")
        self.assertIn("release_note", cast(list[str], context["event_types"]))
        self.assertIn(
            "release/2026-06-09-eu-billing", cast(list[str], context["event_refs"])
        )
        self.assertIn("copilot", cast(list[str], context["affected_surfaces"]))

    def test_open_urgent_review_preserves_release_context_into_follow_up_phase(
        self,
    ) -> None:
        result = apply_drift_governance_commands(
            get_drift_governance_surface(),
            (
                DriftGovernanceCommand(
                    command_type=DriftGovernanceCommandType.OPEN_URGENT_REVIEW,
                    target_ref="cp-drift-1",
                    reason="release_week_drift_requires_command_path",
                ),
            ),
        ).to_dict()
        self.assertIsNotNone(result["urgent_review_queue"])
        urgent_review_queue = cast(dict[str, object], result["urgent_review_queue"])
        first_entry = cast(list[dict[str, object]], urgent_review_queue["entries"])[0]
        self.assertEqual(first_entry["object_ref"], "cp-drift-1")
        self.assertEqual(first_entry["urgency"], "urgent")
        context_trail = cast(list[dict[str, object]], result["context_trail"])
        review_phase = next(
            item for item in context_trail if item["phase"] == "urgent_review"
        )
        self.assertIn(
            "release/2026-06-09-eu-billing", cast(list[str], review_phase["event_refs"])
        )
        self.assertIn("release_note", cast(list[str], review_phase["event_types"]))

    def test_freeze_then_recheck_supports_restrict_before_repair_rhythm(self) -> None:
        result = apply_drift_governance_commands(
            get_drift_governance_surface(),
            (
                DriftGovernanceCommand(
                    command_type=DriftGovernanceCommandType.FREEZE_EXTERNAL_PUBLISH,
                    target_ref="cp-drift-1",
                    reason="freeze_customer_spread_before_answer_refresh",
                ),
                DriftGovernanceCommand(
                    command_type=DriftGovernanceCommandType.FORCE_AUDIENCE_RECHECK,
                    target_ref="cp-drift-1",
                    reason="enterprise_eu_rollout_boundary_needs_recheck",
                ),
            ),
        ).to_dict()
        self.assertIsNotNone(result["publish_freeze_result"])
        publish_freeze_result = cast(dict[str, object], result["publish_freeze_result"])
        impacts = cast(
            list[dict[str, object]],
            cast(dict[str, object], publish_freeze_result["preview"])["impacts"],
        )
        self.assertTrue(all(impact["effect"] == "conflict" for impact in impacts))
        self.assertIn(
            "external · billing · enterprise · eu",
            cast(list[str], result["audience_recheck_labels"]),
        )
        context_trail = cast(list[dict[str, object]], result["context_trail"])
        phases = {item["phase"] for item in context_trail}
        self.assertEqual(phases, {"publish_freeze", "audience_recheck"})
        self.assertEqual(
            result["command_log"],
            [
                "freeze_external_publish:cp-drift-1:freeze_customer_spread_before_answer_refresh",
                "force_audience_recheck:cp-drift-1:enterprise_eu_rollout_boundary_needs_recheck",
            ],
        )
