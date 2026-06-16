from __future__ import annotations

import unittest

from cygnus.retrieval import EvidenceIndex, sample_support_evidence


class EvidenceIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = EvidenceIndex(sample_support_evidence())

    def test_evidence_search_returns_evidence_first_results(self) -> None:
        results = self.index.search(query="support ops approval refund")

        ids = {item.evidence_id for item in results}
        self.assertIn("ev-sop-refund-exception", ids)
        matching = next(item for item in results if item.evidence_id == "ev-sop-refund-exception")
        self.assertEqual(matching.source_type, "internal_sop")
        self.assertTrue(matching.excerpt_ref.startswith("ev-sop-refund-exception:"))

    def test_evidence_search_respects_filters(self) -> None:
        results = self.index.search(
            query="invoice export",
            filters={"source_type": "release_note", "region": "eu", "product_version": "2026.06"},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].evidence_id, "ev-release-export-eu")
        self.assertEqual(results[0].freshness.value, "fresh")


if __name__ == "__main__":
    unittest.main()
