from __future__ import annotations

import unittest

from cygnus.review import (
    OwnerState,
    ReviewHomeQuery,
    ReviewQueueDrilldownQuery,
    get_review_queue_drilldown,
)


class ReviewDrilldownTests(unittest.TestCase):
    def test_get_review_queue_drilldown_keeps_queue_context_and_selected_detail(self) -> None:
        payload = get_review_queue_drilldown(
            ReviewQueueDrilldownQuery(selected_object_ref="cp-source-1")
        ).to_dict()

        self.assertEqual(payload["surface_id"], "review-queue-drilldown")
        self.assertEqual(payload["selected_position"], 0)
        self.assertEqual(payload["selected_card"]["object_ref"], "cp-source-1")
        self.assertEqual(payload["selected_detail"]["item_ref"], "cp-source-1")
        self.assertIsNone(payload["previous_object_ref"])
        self.assertIsNotNone(payload["next_object_ref"])
        self.assertIn("queue_surface", payload)

    def test_get_review_queue_drilldown_can_preserve_filtered_queue(self) -> None:
        payload = get_review_queue_drilldown(
            ReviewQueueDrilldownQuery(
                selected_object_ref="cp-ticket-1",
                home_query=ReviewHomeQuery(owner_state=OwnerState.UNASSIGNED),
            )
        ).to_dict()

        self.assertEqual(payload["total_items"], 2)
        self.assertEqual(payload["selected_detail"]["risk_frame"]["risk_type"], "ticket_pressure")
        self.assertTrue(
            all(card["owner_state"] == "unassigned" for card in payload["queue_surface"]["priority_stack"])
        )

    def test_get_review_queue_drilldown_raises_when_selected_item_is_not_in_queue(self) -> None:
        with self.assertRaises(ValueError):
            get_review_queue_drilldown(
                ReviewQueueDrilldownQuery(
                    selected_object_ref="cp-drift-1",
                    home_query=ReviewHomeQuery(owner_state=OwnerState.UNASSIGNED),
                )
            )
