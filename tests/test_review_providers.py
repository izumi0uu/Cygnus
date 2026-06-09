from __future__ import annotations

import unittest

from cygnus.review import (
    build_review_command_surface,
    build_review_command_surface_from_bundles,
    sample_review_bundles,
)
from cygnus.review.queries import build_review_command_brief
from cygnus.review.service import build_review_risk_item


class ReviewProviderTests(unittest.TestCase):
    def test_build_review_command_surface_from_bundles_matches_cyg6_shape(self) -> None:
        payload = build_review_command_surface_from_bundles(
            surface_id="review-home",
            headline="Today’s highest-leverage governance risks",
            briefing_note="Morning command brief before opening any draft detail.",
            bundles=sample_review_bundles(),
        ).to_dict()

        self.assertEqual(payload["surface_id"], "review-home")
        self.assertEqual(payload["headline"], "Today’s highest-leverage governance risks")
        self.assertIn("situation_frame", payload)
        self.assertIn("priority_stack", payload)
        self.assertEqual(payload["priority_stack"][0]["risk_type"], "source_blindness")
        self.assertIn("affected_audiences", payload["priority_stack"][0])
        self.assertIn("affected_surfaces", payload["priority_stack"][0])
        self.assertIn("owner_state", payload["priority_stack"][0])
        self.assertIn("primary_command", payload["priority_stack"][0])
        self.assertIn("available_commands", payload)

    def test_build_review_command_surface_from_brief_preserves_existing_brief(self) -> None:
        items = tuple(build_review_risk_item(bundle) for bundle in sample_review_bundles())
        brief = build_review_command_brief(
            brief_id="brief-1",
            headline="Today’s highest-leverage governance risks",
            items=items,
        )
        surface = build_review_command_surface(
            surface_id="review-home",
            briefing_note="Morning command brief before opening any draft detail.",
            brief=brief,
        )

        payload = surface.to_dict()
        self.assertEqual(payload["command_brief"]["brief_id"], "brief-1")
        self.assertEqual(payload["situation_frame"]["briefing_note"], "Morning command brief before opening any draft detail.")
