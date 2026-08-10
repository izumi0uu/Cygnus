from __future__ import annotations

import unittest
from collections import Counter

from cygnus.domain import (
    AudienceContext,
    KnowledgeObject,
    LifecycleState,
    TroubleshootingFlow,
    Visibility,
)
from cygnus.evaluation.contracts import EvalCase
from cygnus.evaluation.corpus import production_eval_cases
from cygnus.evidence import FreshnessState, SupportEvidence


_EXPECTED_FAMILIES = {
    "plan_tier_refund",
    "product_version_known_issue",
    "region_feature_availability",
    "freshness_conflict",
    "ticket_cluster_draft",
}


class ProductionEvaluationCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = production_eval_cases()
        self.by_id = {case.case_id: case for case in self.cases}

    def test_case_ids_are_stable_sorted_and_unique(self) -> None:
        case_ids = tuple(case.case_id for case in self.cases)
        repeated_ids = tuple(case.case_id for case in production_eval_cases())

        self.assertIsInstance(self.cases, tuple)
        self.assertGreaterEqual(len(self.cases), 10)
        self.assertEqual(case_ids, tuple(sorted(case_ids)))
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertEqual(repeated_ids, case_ids)

    def test_corpus_has_exactly_two_cases_for_each_required_family(self) -> None:
        family_counts = Counter(case.family for case in self.cases)

        self.assertEqual(set(family_counts), _EXPECTED_FAMILIES)
        self.assertEqual(
            family_counts, Counter({family: 2 for family in _EXPECTED_FAMILIES})
        )

    def test_cases_use_direct_typed_domain_and_evidence_contracts(self) -> None:
        second_copy = production_eval_cases()

        for case, repeated_case in zip(self.cases, second_copy, strict=True):
            with self.subTest(case_id=case.case_id):
                self.assertIsInstance(case, EvalCase)
                self.assertIsInstance(case.audience_context, AudienceContext)
                self.assertIsInstance(case.objects, tuple)
                self.assertIsInstance(case.evidence, tuple)
                self.assertTrue(
                    all(
                        isinstance(object_, KnowledgeObject) for object_ in case.objects
                    )
                )
                self.assertTrue(
                    all(
                        isinstance(evidence, SupportEvidence)
                        for evidence in case.evidence
                    )
                )
                self.assertIsNot(case, repeated_case)
                for object_, repeated_object in zip(
                    case.objects, repeated_case.objects, strict=True
                ):
                    self.assertIsNot(object_, repeated_object)

    def test_expected_refs_resolve_to_case_owned_objects_and_evidence(self) -> None:
        for case in self.cases:
            object_ids = {object_.object_id for object_ in case.objects}
            evidence_ids = {evidence.evidence_id for evidence in case.evidence}
            expectation = case.expectation

            with self.subTest(case_id=case.case_id):
                self.assertLessEqual(set(expectation.object_refs), object_ids)
                self.assertLessEqual(set(expectation.forbidden_object_refs), object_ids)
                self.assertLessEqual(set(expectation.evidence_refs), evidence_ids)
                self.assertLessEqual(set(expectation.citation_refs), evidence_ids)
                self.assertEqual(
                    set(expectation.trace_refs),
                    {f"trace:{object_ref}" for object_ref in expectation.object_refs},
                )
                if expectation.citation_refs:
                    self.assertIsNotNone(case.citation_text)
                    for citation_ref in expectation.citation_refs:
                        self.assertIn(citation_ref, case.citation_text or "")

    def test_supported_and_wrong_audience_boundaries_are_explicit(self) -> None:
        supported = self.by_id["plan-tier-refund-01-free-supported"]
        restricted = self.by_id["plan-tier-refund-02-enterprise-restricted"]
        wrong_region = self.by_id["region-feature-availability-02-apac-restricted"]

        self.assertEqual(supported.expectation.disposition, "answerable")
        self.assertTrue(supported.expectation.object_refs)
        self.assertEqual(supported.audience_context.visibility, Visibility.EXTERNAL)
        self.assertTrue(
            supported.objects[0]
            .supported_audiences[0]
            .matches(supported.audience_context)
        )

        self.assertEqual(restricted.expectation.disposition, "restricted")
        self.assertEqual(
            restricted.expectation.forbidden_object_refs,
            (restricted.objects[0].object_id,),
        )
        self.assertFalse(
            restricted.objects[0]
            .supported_audiences[0]
            .matches(restricted.audience_context)
        )
        self.assertEqual(
            restricted.objects[0].supported_audiences[0].visibility,
            Visibility.INTERNAL,
        )

        self.assertEqual(wrong_region.audience_context.region, "apac")
        self.assertEqual(wrong_region.expectation.disposition, "restricted")
        self.assertFalse(
            wrong_region.objects[0]
            .supported_audiences[0]
            .matches(wrong_region.audience_context)
        )

    def test_unsupported_version_falls_back_without_governed_content(self) -> None:
        unsupported = self.by_id["product-version-known-issue-02-legacy-unsupported"]

        self.assertEqual(unsupported.expectation.disposition, "fallback")
        self.assertEqual(unsupported.audience_context.product_version, "3.9.0")
        self.assertEqual(len(unsupported.objects), 1)
        self.assertEqual(len(unsupported.evidence), 1)
        self.assertFalse(
            unsupported.objects[0]
            .supported_audiences[0]
            .matches(unsupported.audience_context)
        )
        self.assertEqual(unsupported.expectation.object_refs, ())
        self.assertEqual(unsupported.expectation.evidence_refs, ())

    def test_freshness_cases_cover_fresh_stale_conflict_and_stale_only_truth(
        self,
    ) -> None:
        conflict = self.by_id["freshness-conflict-01-current-guidance"]
        stale_only = self.by_id["freshness-conflict-02-stale-only"]

        self.assertEqual(
            {evidence.freshness_state for evidence in conflict.evidence},
            {FreshnessState.FRESH, FreshnessState.STALE},
        )
        self.assertEqual(conflict.expectation.disposition, "answerable")
        self.assertEqual(conflict.expectation.freshness, FreshnessState.FRESH)
        self.assertEqual(
            conflict.expectation.object_refs,
            ("ko-webhook-retry-current",),
        )
        self.assertEqual(
            conflict.expectation.evidence_refs,
            ("ev-webhook-retry-current",),
        )

        self.assertEqual(stale_only.expectation.disposition, "restricted")
        self.assertEqual(stale_only.expectation.freshness, FreshnessState.STALE)
        self.assertEqual(
            {evidence.freshness_state for evidence in stale_only.evidence},
            {FreshnessState.STALE},
        )

    def test_ticket_cluster_cases_cover_unpublished_draft_and_source_blindness(
        self,
    ) -> None:
        unpublished = self.by_id["ticket-cluster-draft-01-unpublished"]
        source_blind = self.by_id["ticket-cluster-draft-02-source-blind"]

        self.assertIsInstance(unpublished.objects[0], TroubleshootingFlow)
        self.assertEqual(
            unpublished.objects[0].lifecycle_state,
            LifecycleState.IN_REVIEW,
        )
        self.assertEqual(unpublished.expectation.disposition, "restricted")
        self.assertEqual(
            unpublished.expectation.forbidden_object_refs,
            (unpublished.objects[0].object_id,),
        )

        self.assertIsInstance(source_blind.objects[0], TroubleshootingFlow)
        self.assertEqual(
            source_blind.objects[0].lifecycle_state,
            LifecycleState.PUBLISHED,
        )
        self.assertEqual(source_blind.expectation.disposition, "escalate")
        self.assertEqual(source_blind.evidence, ())
        self.assertTrue(source_blind.objects[0].evidence_ids)
        self.assertEqual(source_blind.expectation.freshness, FreshnessState.UNKNOWN)

    def test_policy_expectations_cover_success_approval_and_version_conflict(
        self,
    ) -> None:
        approved = self.by_id["plan-tier-refund-01-free-supported"].expectation.policy
        pending = self.by_id[
            "plan-tier-refund-02-enterprise-restricted"
        ].expectation.policy
        stale = self.by_id["freshness-conflict-02-stale-only"].expectation.policy

        self.assertIsNotNone(approved)
        self.assertEqual(approved.draft_status, "approved")
        self.assertTrue(approved.is_admin)
        self.assertEqual(approved.expected_status, "success")
        self.assertIsNone(approved.expected_error)

        self.assertIsNotNone(pending)
        self.assertEqual(pending.draft_status, "pending")
        self.assertEqual(pending.expected_status, "approval_required")
        self.assertEqual(pending.expected_error, "approval_required")

        self.assertIsNotNone(stale)
        self.assertEqual(stale.page_version, 5)
        self.assertEqual(stale.expected_version, 4)
        self.assertEqual(stale.expected_status, "conflict")
        self.assertEqual(stale.expected_error, "stale_version")


if __name__ == "__main__":
    unittest.main()
