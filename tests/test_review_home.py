from __future__ import annotations

import unittest
from typing import cast

from cygnus.domain import Visibility
from cygnus.review import (
    OwnerState,
    ReviewHomeQuery,
    ReviewRiskType,
    get_review_home_surface,
)


class ReviewHomeTests(unittest.TestCase):
    def test_get_review_home_surface_returns_default_command_surface(self) -> None:
        payload = get_review_home_surface().to_dict()
        self.assertEqual(payload["surface_id"], "review-home")
        self.assertIn("situation_frame", payload)
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertGreaterEqual(len(priority_stack), 4)
        self.assertEqual(
            payload["headline"], "Today’s highest-leverage governance risks"
        )

    def test_get_review_home_surface_can_focus_external_governance_risks(self) -> None:
        payload = get_review_home_surface(
            ReviewHomeQuery(visibility=Visibility.EXTERNAL)
        ).to_dict()
        self.assertEqual(
            payload["headline"], "External governance risks requiring command attention"
        )
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertTrue(
            all(
                any(
                    audience["visibility"] == "external"
                    for audience in cast(
                        list[dict[str, object]], card["affected_audiences"]
                    )
                )
                for card in priority_stack
            )
        )

    def test_get_review_home_surface_can_focus_owner_gap_items(self) -> None:
        payload = get_review_home_surface(
            ReviewHomeQuery(owner_state=OwnerState.UNASSIGNED)
        ).to_dict()
        situation_frame = cast(dict[str, object], payload["situation_frame"])
        self.assertEqual(
            situation_frame["briefing_note"],
            "Focused command brief for risks that still have an ownership gap.",
        )
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertTrue(
            all(card["owner_state"] == "unassigned" for card in priority_stack)
        )

    def test_get_review_home_surface_can_focus_single_risk_type_and_limit_cards(
        self,
    ) -> None:
        payload = get_review_home_surface(
            ReviewHomeQuery(risk_types=(ReviewRiskType.SOURCE_BLINDNESS,), max_items=1)
        ).to_dict()
        self.assertEqual(
            payload["headline"], "Focused governance brief: source blindness"
        )
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertEqual(len(priority_stack), 1)
        self.assertEqual(priority_stack[0]["risk_type"], "source_blindness")

    def test_get_review_home_surface_can_focus_ticket_pressure(self) -> None:
        payload = get_review_home_surface(
            ReviewHomeQuery(risk_types=(ReviewRiskType.TICKET_PRESSURE,))
        ).to_dict()
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertEqual(priority_stack[0]["risk_type"], "ticket_pressure")
        self.assertIn(
            "queue-sidebar", cast(list[str], priority_stack[0]["affected_surfaces"])
        )

    def test_get_review_home_surface_can_focus_audience_mismatch(self) -> None:
        payload = get_review_home_surface(
            ReviewHomeQuery(risk_types=(ReviewRiskType.AUDIENCE_MISMATCH,))
        ).to_dict()
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertEqual(priority_stack[0]["risk_type"], "audience_mismatch")
        self.assertIn(
            "split_variant", cast(list[str], priority_stack[0]["command_actions"])
        )

    def test_get_review_home_surface_raises_when_query_matches_nothing(self) -> None:
        with self.assertRaises(ValueError):
            get_review_home_surface(
                ReviewHomeQuery(risk_types=(ReviewRiskType.POLICY_CONFLICT,))
            )
