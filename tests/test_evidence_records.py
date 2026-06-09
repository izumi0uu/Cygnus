from __future__ import annotations

import unittest

from cygnus.domain import AudienceFilter, Visibility
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence


class EvidenceRecordTests(unittest.TestCase):
    def test_support_evidence_carries_support_metadata(self) -> None:
        evidence = SupportEvidence(
            evidence_id="ev-1",
            source_type=EvidenceSourceType.RELEASE_NOTE,
            source_ref="release-2026-06-09",
            title="Invoice export rollout",
            content="Enterprise EU invoice export is rolling out behind a feature flag.",
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing",),
                plans=("enterprise",),
                regions=("eu",),
            ),
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
            product_versions=("2026.06",),
            tags=("billing", "invoice"),
            freshness_state=FreshnessState.FRESH,
            updated_at="2026-06-09",
        )

        payload = evidence.to_dict()
        self.assertEqual(payload["source_type"], "release_note")
        self.assertEqual(payload["freshness_state"], "fresh")
        self.assertEqual(payload["product_lines"], ["billing"])

