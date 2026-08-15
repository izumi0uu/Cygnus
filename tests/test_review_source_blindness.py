from __future__ import annotations

import unittest
from typing import cast

from cygnus.review import (
    SourceBlindnessCommand,
    SourceBlindnessCommandType,
    apply_source_blindness_commands,
    get_source_blindness_surface,
)


class ReviewSourceBlindnessTests(unittest.TestCase):
    def test_get_source_blindness_surface_translates_source_failure_into_governance_loss(
        self,
    ) -> None:
        payload = get_source_blindness_surface().to_dict()
        self.assertEqual(payload["surface_id"], "source-health")
        available_commands = cast(list[str], payload["available_commands"])
        self.assertIn("repair_source", available_commands)
        self.assertIn("restrict_propagation", available_commands)
        self.assertIn("route_to_human_review", available_commands)
        context = cast(list[dict[str, object]], payload["contexts"])[0]
        self.assertEqual(context["proposal_ref"], "cp-source-1")
        self.assertEqual(context["risk_type"], "source_blindness")
        self.assertIn(
            "incident/sev2-eu-billing", cast(list[str], context["source_refs"])
        )
        self.assertIn("incident_update", cast(list[str], context["source_types"]))
        self.assertIn("help_center", cast(list[str], context["affected_surfaces"]))
        self.assertIn("copilot", cast(list[str], context["affected_surfaces"]))
        self.assertIn("stale", cast(list[str], context["freshness_states"]))
        self.assertIn("stale guidance", cast(str, context["business_consequence"]))
        self.assertIn("external", cast(str, context["propagation_risk_summary"]))

    def test_repair_source_returns_repair_directive_and_updates_context_trail(
        self,
    ) -> None:
        result = apply_source_blindness_commands(
            get_source_blindness_surface(),
            (
                SourceBlindnessCommand(
                    command_type=SourceBlindnessCommandType.REPAIR_SOURCE,
                    target_ref="cp-source-1",
                    reason="incident_feed_must_be_restored_before_next_publish_decision",
                ),
            ),
        ).to_dict()
        repair_directives = cast(list[dict[str, object]], result["repair_directives"])
        self.assertEqual(repair_directives[0]["proposal_ref"], "cp-source-1")
        self.assertIn(
            "incident/sev2-eu-billing",
            cast(list[str], repair_directives[0]["source_refs"]),
        )
        context_trail = cast(list[dict[str, object]], result["context_trail"])
        self.assertEqual(context_trail[0]["phase"], "source_repair")
        self.assertIn(
            "repair_source:cp-source-1:incident_feed_must_be_restored_before_next_publish_decision",
            cast(list[str], result["command_log"]),
        )

    def test_restrict_propagation_converts_source_failure_into_publish_containment(
        self,
    ) -> None:
        result = apply_source_blindness_commands(
            get_source_blindness_surface(),
            (
                SourceBlindnessCommand(
                    command_type=SourceBlindnessCommandType.RESTRICT_PROPAGATION,
                    target_ref="cp-source-1",
                    reason="contain_customer_spread_until_source_confidence_recovers",
                ),
            ),
        ).to_dict()
        self.assertIsNotNone(result["publish_restriction_result"])
        self.assertIsNotNone(result["propagation_ledger"])
        publish_restriction_result = cast(
            dict[str, object], result["publish_restriction_result"]
        )
        impacts = cast(
            list[dict[str, object]],
            cast(dict[str, object], publish_restriction_result["preview"])["impacts"],
        )
        self.assertTrue(any(impact["effect"] == "conflict" for impact in impacts))
        propagation_ledger = cast(dict[str, object], result["propagation_ledger"])
        record_map = {
            cast(str, record["surface_id"]): record
            for record in cast(list[dict[str, object]], propagation_ledger["records"])
        }
        self.assertEqual(record_map["help_center"]["status"], "manual_action_required")
        self.assertEqual(record_map["copilot"]["status"], "manual_action_required")
        self.assertIn(
            "restrict_propagation:cp-source-1:contain_customer_spread_until_source_confidence_recovers",
            cast(list[str], result["command_log"]),
        )

    def test_route_to_human_review_preserves_source_context_into_review_queue(
        self,
    ) -> None:
        result = apply_source_blindness_commands(
            get_source_blindness_surface(),
            (
                SourceBlindnessCommand(
                    command_type=SourceBlindnessCommandType.ROUTE_TO_HUMAN_REVIEW,
                    target_ref="cp-source-1",
                    reason="human_signoff_required_while_source_layer_is_blind",
                ),
            ),
        ).to_dict()
        self.assertIsNotNone(result["human_review_queue"])
        human_review_queue = cast(dict[str, object], result["human_review_queue"])
        first_entry = cast(list[dict[str, object]], human_review_queue["entries"])[0]
        self.assertEqual(first_entry["object_ref"], "cp-source-1")
        self.assertEqual(first_entry["risk_type"], "source_blindness")
        self.assertEqual(first_entry["owner_state"], "escalated")
        context_trail = cast(list[dict[str, object]], result["context_trail"])
        human_review = next(
            item for item in context_trail if item["phase"] == "human_review"
        )
        self.assertIn(
            "incident/sev2-eu-billing", cast(list[str], human_review["source_refs"])
        )
        self.assertIn("help_center", cast(list[str], human_review["affected_surfaces"]))


if __name__ == "__main__":
    unittest.main()
