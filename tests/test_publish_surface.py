from __future__ import annotations

import unittest

from cygnus.publish import (
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
)


class PublishSurfaceTests(unittest.TestCase):
    def test_default_surface_selects_top_queue_item_and_exposes_blast_radius(self) -> None:
        payload = get_pressure_intake_publish_preview_surface().to_dict()

        self.assertEqual(payload["surface_id"], "publish-preview")
        self.assertEqual(payload["selected_card"]["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_preview"]["action_type"], "restrict")
        self.assertIn("channel_gate_matrix", payload["selected_preview"])
        self.assertIn("audience_scope", payload["selected_preview"])
        self.assertIn("available_commands", payload)
        self.assertEqual([preset["command_key"] for preset in payload["action_presets"]], ["restrict_publish", "hold_external"])
        self.assertIsNone(payload["selected_action"])
        self.assertIsNone(payload["action_echo"])
        self.assertGreaterEqual(payload["situation_frame"]["blocked_paths"], 1)

    def test_specific_object_ref_exposes_granular_governance_actions(self) -> None:
        payload = get_pressure_intake_publish_preview_surface("refund-enterprise-rewrite").to_dict()

        self.assertEqual(payload["selected_preview"]["object_id"], "refund-enterprise-rewrite")
        effects = {impact["effect"] for impact in payload["selected_preview"]["impacts"]}
        self.assertIn("conflict", effects)
        self.assertIn("stopped_exposure", effects)
        self.assertIn("hold_external", payload["available_commands"])
        self.assertIn("split_variant", payload["available_commands"])
        self.assertIn("republish_internal_only", payload["available_commands"])
        self.assertIsNotNone(payload["previous_object_ref"])

    def test_selected_action_returns_action_echo_and_updated_preview(self) -> None:
        payload = get_pressure_intake_publish_preview_surface(
            "refund-enterprise-rewrite",
            action_key="republish_internal_only",
        ).to_dict()

        self.assertEqual(payload["selected_action"], "republish_internal_only")
        self.assertIsNotNone(payload["action_echo"])
        self.assertEqual(payload["action_echo"]["selected_action"], "republish_internal_only")
        self.assertEqual(len(payload["action_echo"]["removed_bindings"]), 2)
        effects = {(impact["audience_label"], impact["channel"]): impact["effect"] for impact in payload["selected_preview"]["impacts"]}
        self.assertEqual(effects[("internal · billing", "copilot")], "continuing_exposure")
        self.assertEqual(effects[("external · billing · free · us", "help_center")], "stopped_exposure")

    def test_propagation_surface_defaults_to_recommended_action_and_status_lanes(self) -> None:
        payload = get_pressure_intake_publish_propagation_surface().to_dict()

        self.assertEqual(payload["surface_id"], "publish-propagation")
        self.assertEqual(payload["selected_card"]["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_action"], "restrict_publish")
        self.assertIn("propagation_ledger", payload)
        self.assertIn("status_lanes", payload)
        lane_counts = {lane["status"]: lane["count"] for lane in payload["status_lanes"]}
        self.assertEqual(lane_counts["failed"], 2)
        self.assertGreaterEqual(lane_counts["pending"], 1)
        self.assertIn("repair_source_chain", payload["propagation_ledger"]["continue_commands"])

    def test_propagation_surface_can_rehearse_customer_facing_hold_path(self) -> None:
        payload = get_pressure_intake_publish_propagation_surface(
            "refund-enterprise-rewrite",
            action_key="hold_external",
        ).to_dict()

        self.assertEqual(payload["selected_action"], "hold_external")
        self.assertEqual(payload["action_echo"]["selected_action"], "hold_external")
        record_map = {
            record["surface_id"]: record
            for record in payload["propagation_ledger"]["records"]
        }
        self.assertEqual(record_map["hold_resolution"]["status"], "manual_action_required")
        self.assertEqual(record_map["feedback"]["status"], "manual_action_required")
        self.assertIn("resolve_surface_hold", payload["propagation_ledger"]["continue_commands"])


if __name__ == "__main__":
    unittest.main()
