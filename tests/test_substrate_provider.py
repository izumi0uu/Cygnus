"""Substrate-provider mapping tests (CYG-97 Slice 0).

Covers the pure projection from substrate rows (wiki pages, ready sources)
into governed knowledge objects and support evidence. Sample fixtures stay a
test-injection concern; these tests prove the substrate-backed path.
"""

from __future__ import annotations

import unittest
import uuid

from cygnus.domain.lifecycle import LifecycleState
from cygnus.domain.objects import (
    AnswerCard,
    EscalationRoute,
    KnowledgeObjectType,
    KnownIssuePage,
    PolicyRule,
    TroubleshootingFlow,
)
from cygnus.evidence.records import EvidenceSourceType, FreshnessState
from cygnus.retrieval.substrate_provider import (
    SUBSTRATE_MAPPED_TAG,
    build_substrate_snapshot,
    resolve_object_type,
    source_to_support_evidence,
    wiki_page_to_knowledge_object,
)
from cygnus.runtime.database.models import Source, WikiPage


def _page(**overrides: object) -> WikiPage:
    defaults = dict(
        slug="refund-policy",
        title="Refund policy",
        status="mature",
        content_md="Refunds are honored within 30 days.",
        summary="Refund handling summary",
        knowledge_type_slugs=["answer_card"],
        source_ids=[],
        orphaned=False,
    )
    defaults.update(overrides)
    return WikiPage(**defaults)


def _source(**overrides: object) -> Source:
    defaults = dict(
        id=uuid.uuid4(),
        title="Billing SOP",
        full_text="How to process refunds end to end.",
        status="ready",
        file_name="billing-sop.pdf",
    )
    defaults.update(overrides)
    return Source(**defaults)


class ResolveObjectTypeTests(unittest.TestCase):
    def test_underscore_and_hyphen_slugs_resolve(self) -> None:
        self.assertIs(
            resolve_object_type(["answer_card"]), KnowledgeObjectType.ANSWER_CARD
        )
        self.assertIs(
            resolve_object_type(["troubleshooting-flow"]),
            KnowledgeObjectType.TROUBLESHOOTING_FLOW,
        )
        self.assertIs(
            resolve_object_type(["known-issue"]), KnowledgeObjectType.KNOWN_ISSUE_PAGE
        )

    def test_non_support_slugs_resolve_to_none(self) -> None:
        self.assertIsNone(resolve_object_type(["sop", "product"]))
        self.assertIsNone(resolve_object_type([]))
        self.assertIsNone(resolve_object_type(None))


class WikiPageMappingTests(unittest.TestCase):
    def test_answer_card_projection(self) -> None:
        object_ = wiki_page_to_knowledge_object(_page(), evidence_ids=("ev-src-x",))
        assert isinstance(object_, AnswerCard)
        self.assertEqual(object_.object_id, "ko-refund-policy")
        self.assertEqual(object_.title, "Refund policy")
        self.assertIs(object_.lifecycle_state, LifecycleState.PUBLISHED)
        self.assertEqual(object_.evidence_ids, ("ev-src-x",))
        self.assertIn(SUBSTRATE_MAPPED_TAG, object_.tags)
        self.assertIn("answer_card", object_.tags)
        self.assertEqual(len(object_.supported_audiences), 1)
        self.assertEqual(object_.supported_audiences[0].visibility.value, "internal")

    def test_seed_and_developing_pages_stay_draft(self) -> None:
        for status in ("seed", "developing", None):
            with self.subTest(status=status):
                object_ = wiki_page_to_knowledge_object(_page(status=status))
                assert object_ is not None
                self.assertIs(object_.lifecycle_state, LifecycleState.DRAFT)

    def test_troubleshooting_flow_takes_steps_from_markdown_lists(self) -> None:
        object_ = wiki_page_to_knowledge_object(
            _page(
                slug="vpn-drops",
                knowledge_type_slugs=["troubleshooting_flow"],
                content_md="Intro\n\n- restart client\n- rotate credentials\n1. escalate",
            )
        )
        assert isinstance(object_, TroubleshootingFlow)
        self.assertEqual(
            object_.steps,
            ("restart client", "rotate credentials", "escalate"),
        )

    def test_troubleshooting_flow_without_lists_gets_pointer_step(self) -> None:
        object_ = wiki_page_to_knowledge_object(
            _page(
                slug="vpn-drops",
                knowledge_type_slugs=["troubleshooting_flow"],
                content_md="prose only",
            )
        )
        assert isinstance(object_, TroubleshootingFlow)
        self.assertEqual(object_.steps, ("See wiki page: vpn-drops",))

    def test_policy_rule_and_known_issue_and_escalation_projections(self) -> None:
        policy = wiki_page_to_knowledge_object(
            _page(knowledge_type_slugs=["policy_rule"])
        )
        assert isinstance(policy, PolicyRule)
        self.assertEqual(policy.authority_source, "wiki:refund-policy")

        issue = wiki_page_to_knowledge_object(
            _page(status="developing", knowledge_type_slugs=["known-issue"])
        )
        assert isinstance(issue, KnownIssuePage)
        self.assertEqual(issue.issue_status, "developing")

        route = wiki_page_to_knowledge_object(
            _page(
                knowledge_type_slugs=["escalation_route"], content_md="- payment stuck"
            )
        )
        assert isinstance(route, EscalationRoute)
        self.assertEqual(route.trigger_conditions, ("payment stuck",))
        self.assertEqual(route.destination_team, "unassigned")

    def test_non_support_page_is_not_projected(self) -> None:
        self.assertIsNone(
            wiki_page_to_knowledge_object(_page(knowledge_type_slugs=["sop"]))
        )
        self.assertIsNone(wiki_page_to_knowledge_object(_page(knowledge_type_slugs=[])))

    def test_reserved_orphaned_and_source_pages_are_not_directly_projected(
        self,
    ) -> None:
        for page in (
            _page(slug="_index"),
            _page(slug="source/billing-sop"),
            _page(slug="orphan", orphaned=True),
        ):
            with self.subTest(slug=page.slug):
                self.assertIsNone(wiki_page_to_knowledge_object(page))


class SourceMappingTests(unittest.TestCase):
    def test_ready_source_projects_to_internal_evidence(self) -> None:
        source = _source()
        evidence = source_to_support_evidence(source, knowledge_type_slug="faq")
        self.assertEqual(evidence.evidence_id, f"ev-src-{source.id}")
        self.assertIs(evidence.source_type, EvidenceSourceType.HELP_CENTER)
        self.assertEqual(evidence.source_ref, "billing-sop.pdf")
        self.assertIn("faq", evidence.tags)
        self.assertIn(SUBSTRATE_MAPPED_TAG, evidence.tags)
        self.assertIs(evidence.freshness_state, FreshnessState.UNKNOWN)
        self.assertEqual(evidence.audience_filter.visibility.value, "internal")

    def test_unknown_knowledge_type_defaults_to_internal_sop(self) -> None:
        evidence = source_to_support_evidence(
            _source(), knowledge_type_slug="random-type"
        )
        self.assertIs(evidence.source_type, EvidenceSourceType.INTERNAL_SOP)

    def test_blank_source_fields_fall_back_without_fabricating(self) -> None:
        source = _source(title=None, full_text=None, file_name=None, url=None)
        evidence = source_to_support_evidence(source)
        self.assertEqual(evidence.source_ref, f"source:{source.id}")
        self.assertEqual(evidence.title, f"source:{source.id}")
        self.assertEqual(evidence.content, f"source:{source.id}")


class SnapshotBuildTests(unittest.TestCase):
    def test_snapshot_links_objects_to_ready_source_evidence_only(self) -> None:
        ready = _source()
        processing = _source(status="processing")
        page = _page(source_ids=[ready.id, processing.id, uuid.uuid4()])

        snapshot = build_substrate_snapshot([page], [ready, processing])

        self.assertEqual(len(snapshot.evidence), 1)
        self.assertEqual(snapshot.evidence[0].evidence_id, f"ev-src-{ready.id}")
        self.assertEqual(len(snapshot.objects), 1)
        self.assertEqual(snapshot.objects[0].evidence_ids, (f"ev-src-{ready.id}",))

    def test_snapshot_skips_reserved_orphaned_and_source_pages(self) -> None:
        pages = [
            _page(slug="_index"),
            _page(slug="_log"),
            _page(slug="source/billing-sop"),
            _page(slug="orphan", orphaned=True),
            _page(slug="non-support", knowledge_type_slugs=["sop"]),
            _page(slug="kept"),
        ]
        snapshot = build_substrate_snapshot(pages, [])
        self.assertEqual([obj.object_id for obj in snapshot.objects], ["ko-kept"])

    def test_snapshot_maps_evidence_type_via_knowledge_type_lookup(self) -> None:
        kt_id = uuid.uuid4()
        source = _source(knowledge_type_id=kt_id)
        snapshot = build_substrate_snapshot(
            [], [source], knowledge_type_slug_by_id={kt_id: "release_note"}
        )
        self.assertIs(snapshot.evidence[0].source_type, EvidenceSourceType.RELEASE_NOTE)


if __name__ == "__main__":
    unittest.main()
