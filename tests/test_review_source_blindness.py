from __future__ import annotations

import unittest

from cygnus.review import (
    SourceBlindnessCommand,
    SourceBlindnessCommandType,
    apply_source_blindness_commands,
    get_source_blindness_surface,
)


class ReviewSourceBlindnessTests(unittest.TestCase):
    def test_get_source_blindness_surface_translates_source_failure_into_governance_loss(self) -> None:
        payload = get_source_blindness_surface().to_dict()
        self.assertEqual(payload["surface_id"], "source-health")
        self.assertIn("repair_source", payload["available_commands"])
        self.assertIn("restrict_propagation", payload["available_commands"])
        self.assertIn("route_to_human_review", payload["available_commands"])
        context = payload["contexts"][0]
        self.assertEqual(context["proposal_ref"], "cp-source-1")
        self.assertEqual(context["risk_type"], "source_blindness")
        self.assertIn("incident/sev2-eu-billing", context["source_refs"])
        self.assertIn("incident_update", context["source_types"])
        self.assertIn("help_center", context["affected_surfaces"])
        self.assertIn("copilot", context["affected_surfaces"])
        self.assertIn("stale", context["freshness_states"])
        self.assertIn("stale guidance", context["business_consequence"])
        self.assertIn("external", context["propagation_risk_summary"])

    def test_repair_source_returns_repair_directive_and_updates_context_trail(self) -> None:
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
        self.assertEqual(result["repair_directives"][0]["proposal_ref"], "cp-source-1")
        self.assertIn("incident/sev2-eu-billing", result["repair_directives"][0]["source_refs"])
        self.assertEqual(result["context_trail"][0]["phase"], "source_repair")
        self.assertIn(
            "repair_source:cp-source-1:incident_feed_must_be_restored_before_next_publish_decision",
            result["command_log"],
        )

    def test_restrict_propagation_converts_source_failure_into_publish_containment(self) -> None:
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
        self.assertTrue(any(impact["effect"] == "conflict" for impact in result["publish_restriction_result"]["preview"]["impacts"]))
        record_map = {record["surface_id"]: record for record in result["propagation_ledger"]["records"]}
        self.assertEqual(record_map["help_center"]["status"], "manual_action_required")
        self.assertEqual(record_map["copilot"]["status"], "manual_action_required")
        self.assertIn(
            "restrict_propagation:cp-source-1:contain_customer_spread_until_source_confidence_recovers",
            result["command_log"],
        )

    def test_route_to_human_review_preserves_source_context_into_review_queue(self) -> None:
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
        first_entry = result["human_review_queue"]["entries"][0]
        self.assertEqual(first_entry["object_ref"], "cp-source-1")
        self.assertEqual(first_entry["risk_type"], "source_blindness")
        self.assertEqual(first_entry["owner_state"], "escalated")
        human_review = next(item for item in result["context_trail"] if item["phase"] == "human_review")
        self.assertIn("incident/sev2-eu-billing", human_review["source_refs"])
        self.assertIn("help_center", human_review["affected_surfaces"])


if __name__ == "__main__":
    unittest.main()
