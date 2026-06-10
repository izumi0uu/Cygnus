from __future__ import annotations

import unittest

from cygnus.review import (
    PressureCommand,
    PressureCommandType,
    apply_pressure_commands,
    get_review_pressure_surface,
)


class ReviewPressureTests(unittest.TestCase):
    def test_get_review_pressure_surface_exposes_frontline_pressure_lines(self) -> None:
        payload = get_review_pressure_surface().to_dict()
        self.assertEqual(payload["surface_id"], "review-pressure")
        self.assertIn("route_to_review", payload["available_commands"])
        refs = {line["proposal_ref"]: line for line in payload["pressure_lines"]}
        self.assertIn("cp-ticket-1", refs)
        self.assertIn("cp-audience-1", refs)
        self.assertEqual(refs["cp-ticket-1"]["suggested_object_type"], "troubleshooting_flow")
        self.assertIn("queue-sidebar", refs["cp-ticket-1"]["affected_surfaces"])
        self.assertIn("Suggested troubleshooting_flow", refs["cp-ticket-1"]["impact_summary"])

    def test_assign_owner_and_mark_urgent_update_pressure_line(self) -> None:
        pressure_surface = get_review_pressure_surface()
        result = apply_pressure_commands(
            pressure_surface,
            (
                PressureCommand(
                    command_type=PressureCommandType.ASSIGN_OWNER,
                    target_refs=("cp-ticket-1",),
                    new_owner="support-ops",
                    reason="frontline_rewrite_spike",
                ),
                PressureCommand(
                    command_type=PressureCommandType.MARK_URGENT,
                    target_refs=("cp-ticket-1",),
                    reason="repeat_cluster_breached_threshold",
                ),
            ),
        ).to_dict()
        refs = {line["proposal_ref"]: line for line in result["pressure_surface"]["pressure_lines"]}
        self.assertEqual(refs["cp-ticket-1"]["owner_state"], "assigned")
        self.assertEqual(refs["cp-ticket-1"]["queue_owner"], "support-ops")
        self.assertEqual(refs["cp-ticket-1"]["urgency"], "urgent")
        self.assertIn("assign_owner:cp-ticket-1:support-ops:frontline_rewrite_spike", result["command_log"])
        self.assertIn("mark_urgent:cp-ticket-1:repeat_cluster_breached_threshold", result["command_log"])

    def test_route_to_review_moves_pressure_line_directly_into_review_queue(self) -> None:
        pressure_surface = get_review_pressure_surface()
        result = apply_pressure_commands(
            pressure_surface,
            (
                PressureCommand(
                    command_type=PressureCommandType.ROUTE_TO_REVIEW,
                    target_refs=("cp-ticket-1",),
                    reason="repeat_cluster_promoted",
                ),
            ),
        ).to_dict()
        self.assertIsNotNone(result["routed_queue"])
        self.assertEqual(result["routed_queue"]["entries"][0]["object_ref"], "cp-ticket-1")
        self.assertEqual(result["routed_queue"]["entries"][0]["risk_type"], "ticket_pressure")
        self.assertIn("route_to_review:cp-ticket-1:repeat_cluster_promoted", result["command_log"])
