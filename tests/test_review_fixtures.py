from __future__ import annotations

import unittest

from cygnus.review.fixtures import sample_review_command_brief


class ReviewFixtureTests(unittest.TestCase):
    def test_sample_command_brief_matches_cyg6_shape(self) -> None:
        payload = sample_review_command_brief()
        self.assertEqual(payload["brief_id"], "brief-1")
        self.assertGreaterEqual(len(payload["priority_items"]), 2)
        self.assertIn("headline", payload)
        self.assertIn("summary_counts", payload)
        self.assertIn("why_now", payload["priority_items"][0])

