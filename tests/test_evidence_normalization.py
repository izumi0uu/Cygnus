from __future__ import annotations

import unittest

from cygnus.domain import Visibility
from cygnus.evidence.normalization import RawEvidenceInput, normalize_evidence
from cygnus.evidence.records import EvidenceSourceType, FreshnessState


class EvidenceNormalizationTests(unittest.TestCase):
    def test_normalize_evidence_outputs_unified_metadata(self) -> None:
        evidence = normalize_evidence(
            "ev-2",
            RawEvidenceInput(
                source_type=EvidenceSourceType.RESOLVED_TICKET,
                source_ref="zd-1001",
                title="Resolved export failure",
                content="Support confirmed export succeeds after role refresh.",
                visibility=Visibility.INTERNAL,
                product_line="billing",
                plan="enterprise",
                region="eu",
                language="en",
                product_version="2026.06",
                freshness_state=FreshnessState.FRESH,
            ),
        )

        self.assertEqual(evidence.evidence_id, "ev-2")
        self.assertEqual(evidence.audience_filter.product_lines, ("billing",))
        self.assertEqual(evidence.tags[0], "resolved_ticket")

