from __future__ import annotations

import unittest
from typing import cast

from cygnus.review import (
    ReviewRiskType,
    build_review_item_detail_surface,
    sample_review_bundles,
)


class ReviewItemTests(unittest.TestCase):
    def test_build_review_item_detail_surface_surfaces_risk_frame_before_content(
        self,
    ) -> None:
        bundle = sample_review_bundles()[0]
        item = __import__(
            "cygnus.review", fromlist=["build_review_risk_item"]
        ).build_review_risk_item(bundle)
        detail = build_review_item_detail_surface(
            item=item,
            evidence=bundle.evidence,
            evidence_sufficiency=bundle.proposal.evidence_sufficiency,
        )

        payload = detail.to_dict()
        risk_frame = cast(dict[str, object], payload["risk_frame"])
        self.assertEqual(risk_frame["risk_type"], "source_blindness")
        self.assertEqual(risk_frame["system_tension"], "Governance blindness")
        self.assertIn("evidence_strength", payload)
        self.assertIn("audience_impact", payload)
        self.assertIn("command_origin_tag", risk_frame)
        evidence_strength = cast(dict[str, object], payload["evidence_strength"])
        self.assertIn("stale:1", cast(list[str], evidence_strength["freshness_mix"]))

    def test_build_review_item_detail_surface_handles_audience_mismatch(self) -> None:
        bundle = next(
            bundle
            for bundle in sample_review_bundles()
            if bundle.signal.risk_type is ReviewRiskType.AUDIENCE_MISMATCH
        )
        item = __import__(
            "cygnus.review", fromlist=["build_review_risk_item"]
        ).build_review_risk_item(bundle)
        detail = build_review_item_detail_surface(
            item=item,
            evidence=bundle.evidence,
            evidence_sufficiency=bundle.proposal.evidence_sufficiency,
        ).to_dict()
        risk_frame = cast(dict[str, object], detail["risk_frame"])
        self.assertEqual(risk_frame["system_tension"], "Audience boundary conflict")
        self.assertIn("split_variant", cast(list[str], detail["command_actions"]))
