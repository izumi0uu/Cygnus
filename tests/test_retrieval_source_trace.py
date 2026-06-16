from __future__ import annotations

import unittest

from cygnus.retrieval import SourceTraceResolver, sample_knowledge_objects, sample_support_evidence


class SourceTraceResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = SourceTraceResolver(
            sample_knowledge_objects(),
            sample_support_evidence(),
        )

    def test_trace_expands_base_and_variant_evidence(self) -> None:
        trace = self.resolver.get_trace("ko-invoice-export-enterprise-eu")

        assert trace is not None
        self.assertEqual(trace.object_id, "ko-invoice-export-enterprise-eu")
        self.assertEqual(len(trace.evidence_refs), 2)
        scopes = {item.scope for item in trace.evidence_refs}
        self.assertIn("base", scopes)
        self.assertIn("variant:eu-rollout-delay", scopes)
        self.assertEqual(trace.freshness.value, "stale")
        self.assertIn("stale_evidence_present", trace.blind_spots)

    def test_trace_marks_missing_evidence_as_blind_spot(self) -> None:
        object_with_missing = next(
            item for item in sample_knowledge_objects() if item.object_id == "ko-billing-refund-policy"
        )
        filtered_evidence = tuple(
            item
            for item in sample_support_evidence()
            if item.evidence_id != "ev-sop-refund-exception"
        )
        resolver = SourceTraceResolver((object_with_missing,), filtered_evidence)

        trace = resolver.get_trace("ko-billing-refund-policy")

        assert trace is not None
        self.assertEqual(trace.freshness.value, "fresh")
        self.assertIn("missing_evidence:ev-sop-refund-exception", trace.blind_spots)


if __name__ == "__main__":
    unittest.main()
