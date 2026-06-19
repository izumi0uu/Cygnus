from __future__ import annotations

import unittest

from cygnus.api.app import (
    command_center,
    downstream_reality_check,
    governance_overview,
    healthz,
    knowledge_graph,
    publish_preview,
    publish_propagation,
    recovery_proof,
    recovery_window,
    review_intake,
    review_queue_item,
)


class CommandCenterApiTests(unittest.TestCase):
    def test_healthz_ok(self) -> None:
        self.assertEqual(healthz(), {"status": "ok"})

    def test_command_center_payload_shape(self) -> None:
        payload = command_center()
        self.assertIn("situation_frame", payload)
        self.assertIn("priority_stack", payload)
        self.assertIn("available_commands", payload)
        self.assertEqual(len(payload["priority_stack"]), 4)
        self.assertEqual(payload["situation_frame"]["urgent_items"], 1)

    def test_review_intake_payload_shape(self) -> None:
        payload = review_intake()
        self.assertIn("review_home", payload)
        self.assertIn("pressure_surface", payload)
        self.assertIn("source_blindness_surface", payload)
        self.assertEqual(payload["review_home"]["surface_id"], "review-home")
        self.assertEqual(payload["pressure_surface"]["surface_id"], "review-pressure")
        self.assertEqual(payload["source_blindness_surface"]["surface_id"], "source-health")

    def test_review_queue_item_returns_intake_drilldown_surface(self) -> None:
        payload = review_queue_item("refund-enterprise-rewrite")
        self.assertEqual(payload["surface_id"], "review-queue-drilldown")
        self.assertEqual(payload["selected_card"]["object_ref"], "refund-enterprise-rewrite")
        self.assertIn("queue_surface", payload)

    def test_publish_preview_returns_blast_radius_surface(self) -> None:
        payload = publish_preview()
        self.assertEqual(payload["surface_id"], "publish-preview")
        self.assertIn("selected_preview", payload)
        self.assertIn("situation_frame", payload)

    def test_publish_propagation_returns_supporting_surface_theater(self) -> None:
        payload = publish_propagation("refund-enterprise-rewrite", action_key="hold_external")
        self.assertEqual(payload["surface_id"], "publish-propagation")
        self.assertEqual(payload["selected_action"], "hold_external")
        self.assertIn("propagation_ledger", payload)

    def test_recovery_proof_returns_frontline_reality_check(self) -> None:
        payload = recovery_proof("billing-verification-w25")
        self.assertEqual(payload["surface_id"], "recovery-proof")
        self.assertEqual(payload["selected_card"]["object_ref"], "billing-verification-w25")
        self.assertIn("recovery_window", payload)
        self.assertIn("signals", payload)

    def test_downstream_reality_check_payload_shape(self) -> None:
        payload = downstream_reality_check("cmd-publish-1")
        self.assertEqual(payload["surface_id"], "downstream-reality-check")
        self.assertIn("reality_check_strip", payload)
        self.assertIn("feedback_feed", payload)
        self.assertIn("mismatch_by_audience", payload)

    def test_recovery_window_payload_shape(self) -> None:
        payload = recovery_window("cmd-publish-1")
        self.assertEqual(payload["surface_id"], "recovery-window")
        self.assertIn("before_after_alignment_view", payload)
        self.assertIn("rewrite_delta", payload)
        self.assertIn("closure_judge", payload)

    def test_governance_overview_payload_shape(self) -> None:
        payload = governance_overview()
        self.assertEqual(payload["surface_id"], "governance-overview")
        self.assertIn("open_loops", payload)
        self.assertIn("open_loop_ranks", payload)
        self.assertIn("highest_leverage_command", payload)
        self.assertEqual(len(payload["open_loops"]), 2)
        self.assertEqual(payload["highest_leverage_command"], "cmd-restrict-2")

    def test_knowledge_graph_payload_shape(self) -> None:
        payload = knowledge_graph()
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertIn("stats", payload)
        self.assertGreater(payload["stats"]["objects"], 0)
        self.assertGreater(payload["stats"]["evidence"], 0)
        self.assertGreater(payload["stats"]["audiences"], 0)
        node_kinds = {node["kind"] for node in payload["nodes"]}
        edge_kinds = {edge["kind"] for edge in payload["edges"]}
        self.assertTrue({"object", "evidence", "audience"}.issubset(node_kinds))
        self.assertTrue({"cites", "serves"}.issubset(edge_kinds))


if __name__ == "__main__":
    unittest.main()
