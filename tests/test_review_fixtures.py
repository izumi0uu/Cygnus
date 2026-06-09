from __future__ import annotations

import unittest

from cygnus.review.fixtures import sample_review_command_brief, sample_review_command_surface


class ReviewFixtureTests(unittest.TestCase):
    def test_sample_command_brief_matches_cyg6_shape(self) -> None:
        payload = sample_review_command_brief()
        self.assertEqual(payload["brief_id"], "brief-1")
        self.assertGreaterEqual(len(payload["priority_items"]), 2)
        self.assertIn("headline", payload)
        self.assertIn("summary_counts", payload)
        self.assertIn("why_now", payload["priority_items"][0])

    def test_sample_command_surface_matches_cyg6_screen_shape(self) -> None:
        payload = sample_review_command_surface()
        self.assertEqual(payload["surface_id"], "review-home")
        self.assertIn("situation_frame", payload)
        self.assertIn("priority_stack", payload)
        self.assertIn("available_commands", payload)
        self.assertEqual(payload["priority_stack"][0]["risk_type"], "source_blindness")
