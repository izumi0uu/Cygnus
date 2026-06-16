from __future__ import annotations

import unittest

from cygnus.domain import AudienceContext, Visibility
from cygnus.retrieval import KnowledgeObjectIndex, sample_knowledge_objects, sample_support_evidence


class KnowledgeObjectIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = KnowledgeObjectIndex(
            sample_knowledge_objects(),
            sample_support_evidence(),
        )

    def test_object_search_applies_audience_filter_before_result_exposure(self) -> None:
        eu_enterprise = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="enterprise",
            region="eu",
        )
        free_external = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="free",
            region="us",
        )

        eu_results = self.index.search(
            query="invoice export rollout",
            audience_context=eu_enterprise,
        )
        free_results = self.index.search(
            query="invoice export rollout",
            audience_context=free_external,
        )

        eu_ids = {item.object_id for item in eu_results}
        self.assertIn("ko-invoice-export-enterprise-eu", eu_ids)
        self.assertTrue(all(item.audience_match == "exact" for item in eu_results))
        self.assertEqual(free_results, ())

    def test_object_search_hides_unpublished_by_default(self) -> None:
        internal = AudienceContext(
            visibility=Visibility.INTERNAL,
            product_line="billing",
        )

        hidden = self.index.search(
            query="verification troubleshooting",
            audience_context=internal,
        )
        visible = self.index.search(
            query="verification troubleshooting",
            audience_context=internal,
            include_unpublished=True,
        )

        self.assertEqual(hidden, ())
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].publication_status, "in_review")

    def test_object_search_returns_trace_link_and_freshness_rollup(self) -> None:
        context = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="enterprise",
            region="eu",
        )

        results = self.index.search(
            query="manual invoice delivery",
            audience_context=context,
        )

        self.assertEqual(len(results), 2)
        answer = next(item for item in results if item.object_id == "ko-invoice-export-enterprise-eu")
        self.assertEqual(answer.trace_ref, "trace:ko-invoice-export-enterprise-eu")
        self.assertEqual(answer.freshness.value, "stale")


if __name__ == "__main__":
    unittest.main()
