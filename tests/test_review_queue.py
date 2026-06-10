from __future__ import annotations

import unittest

from cygnus.review import (
    QueueCommand,
    QueueCommandType,
    ReviewHomeQuery,
    build_review_queue_surface,
    get_review_home_surface,
    get_review_queue_surface,
    apply_queue_commands,
)


class ReviewQueueTests(unittest.TestCase):
    def test_get_review_queue_surface_builds_command_driven_queue(self) -> None:
        payload = get_review_queue_surface().to_dict()
        self.assertEqual(payload["queue_id"], "review-queue")
        self.assertGreaterEqual(len(payload["entries"]), 4)
        self.assertEqual(payload["entries"][0]["upstream_trace"]["source_risk_id"], "source_blindness:cp-source-1")
        self.assertIn("restack", payload["available_bulk_commands"])

    def test_restack_command_reorders_queue_and_preserves_origin_trace(self) -> None:
        queue = get_review_queue_surface()
        ordered_refs = tuple(reversed(queue.restack_lane))
        result = apply_queue_commands(
            queue,
            (
                QueueCommand(
                    command_type=QueueCommandType.RESTACK,
                    ordered_refs=ordered_refs,
                    reason="new_frontline_pressure",
                ),
            ),
        ).to_dict()
        self.assertEqual(result["queue_surface"]["restack_lane"][0], ordered_refs[0])
        self.assertIn("restack:new_frontline_pressure", result["queue_surface"]["entries"][0]["upstream_trace"]["command_history"])

    def test_reroute_command_updates_owner_echo(self) -> None:
        queue = get_review_queue_surface(ReviewHomeQuery(owner_state=None))
        result = apply_queue_commands(
            queue,
            (
                QueueCommand(
                    command_type=QueueCommandType.REROUTE,
                    object_ref="cp-ticket-1",
                    new_owner="queue-b",
                    reason="handoff_to_specialist",
                ),
            ),
        ).to_dict()
        echo = next(item for item in result["owner_echo"] if item["object_ref"] == "cp-ticket-1")
        self.assertEqual(echo["queue_owner"], "queue-b")
        self.assertEqual(echo["owner_state"], "assigned")

    def test_escalate_command_moves_item_forward_and_marks_escalated(self) -> None:
        queue = get_review_queue_surface()
        result = apply_queue_commands(
            queue,
            (
                QueueCommand(
                    command_type=QueueCommandType.ESCALATE,
                    object_ref="cp-ticket-1",
                    reason="urgent_pattern_break",
                ),
            ),
        ).to_dict()
        first = result["queue_surface"]["entries"][0]
        self.assertEqual(first["object_ref"], "cp-ticket-1")
        self.assertEqual(first["owner_state"], "escalated")
        self.assertIn("escalate:cp-ticket-1:urgent_pattern_break", result["command_log"])

    def test_waiting_echo_updates_after_restack(self) -> None:
        queue = get_review_queue_surface()
        result = apply_queue_commands(
            queue,
            (
                QueueCommand(
                    command_type=QueueCommandType.RESTACK,
                    ordered_refs=("cp-ticket-1", "cp-source-1", "cp-audience-1", "cp-drift-1"),
                    reason="owner_load_balance",
                ),
            ),
        ).to_dict()
        touched = {item["object_ref"]: item for item in result["waiting_echo"]}
        self.assertIn("cp-source-1", touched)
        self.assertIn("Waiting", touched["cp-source-1"]["waiting_summary"])
