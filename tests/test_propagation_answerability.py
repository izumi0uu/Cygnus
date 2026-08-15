from __future__ import annotations

import json
import unittest
import uuid

from cygnus.domain import (
    AnswerCard,
    AudienceContext,
    AudienceFilter,
    LifecycleState,
    Visibility,
    governed_object_ref,
)
from cygnus.evidence.records import (
    EvidenceSourceType,
    FreshnessState,
    SupportEvidence,
)
from cygnus.integrations.session_bridge import (
    GovernedQueryRequest,
    GovernedSessionBridge,
    PropagationDeliveryTruth,
    delivered_truth_for_objects,
)
from cygnus.publish.propagation import PropagationStatus
from cygnus.retrieval import SubstrateKnowledgeSnapshot

_OBJECT_ID = governed_object_ref(uuid.UUID("00000000-0000-0000-0000-000000000801"))
_DRAFT_OBJECT_ID = governed_object_ref(
    uuid.UUID("00000000-0000-0000-0000-000000000802")
)
_UNKNOWN_OBJECT_ID = governed_object_ref(
    uuid.UUID("00000000-0000-0000-0000-000000000803")
)


def _audience() -> AudienceFilter:
    return AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("free",),
        languages=("en",),
    )


def _audience_context() -> AudienceContext:
    return AudienceContext(
        visibility=Visibility.EXTERNAL,
        product_line="billing",
        plan="free",
        language="en",
    )


def _other_audience_context() -> AudienceContext:
    return AudienceContext(
        visibility=Visibility.EXTERNAL,
        product_line="billing",
        plan="enterprise",
        language="en",
    )


def _published_answer() -> AnswerCard:
    return AnswerCard(
        object_id=_OBJECT_ID,
        title="Cancel a free-plan subscription",
        summary="Explains the self-serve cancel path for free-plan customers.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(_audience(),),
        evidence_ids=("ev-help-refund",),
        tags=("billing", "cancel", "subscription"),
        question="How do I cancel my subscription?",
        canonical_answer="Go to Billing > Plan and choose Cancel subscription.",
        publish_targets=("copilot",),
    )


def _fresh_evidence() -> SupportEvidence:
    return SupportEvidence(
        evidence_id="ev-help-refund",
        source_type=EvidenceSourceType.HELP_CENTER,
        source_ref="help-center/billing-refunds",
        title="Billing refund policy",
        content="Self-serve monthly plans can request a refund within 14 days.",
        audience_filter=_audience(),
        product_lines=("billing",),
        plans=("free",),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-01T09:00:00Z",
    )


def _request(
    *,
    request_ref: str = "req-prop",
    query: str = "cancel subscription",
    channel: str = "copilot",
    audience_context: AudienceContext | None = None,
) -> GovernedQueryRequest:
    return GovernedQueryRequest(
        request_ref=request_ref,
        query=query,
        channel=channel,
        audience_context=audience_context or _audience_context(),
    )


def _delivery_record(
    status: str = PropagationStatus.SYNCED.value,
) -> PropagationDeliveryTruth:
    binding_refs = [
        {
            "audience_filter": _audience().to_dict(),
            "audience_label": "external:billing:free",
            "channel": "copilot",
        }
    ]
    return PropagationDeliveryTruth.from_propagation_rows(
        ((_OBJECT_ID, "copilot", status, binding_refs),)
    )


class PropagationCoupledAnswerabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = SubstrateKnowledgeSnapshot(
            objects=(_published_answer(),),
            evidence=(_fresh_evidence(),),
        )
        self.bridge = GovernedSessionBridge(self.snapshot)

    def test_answerability_requires_synced_channel_and_audience_record(self) -> None:
        payload = self.bridge.query_with_fixture_delivery(
            _request(),
            delivery_truth=_delivery_record(),
        )
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["governance"]["state"], "answerable")
        self.assertTrue(payload["data"]["answer"]["direct_external_use"])
        self.assertIsNotNone(payload["data"]["answer"]["content"])

    def test_missing_delivery_truth_fails_closed_without_content(self) -> None:
        payload = self.bridge.query(_request())
        data = payload["data"]
        self.assertEqual(payload["status"], "denied")
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("propagation_pending", data["governance"]["codes"])
        self.assertIn("not_delivered_to_channel", data["governance"]["codes"])
        self.assertIsNone(data["answer"]["content"])
        self.assertEqual(data["answer"]["usage"], "withheld")

    def test_pending_propagation_restricts_without_content(self) -> None:
        payload = self.bridge.query_with_fixture_delivery(
            _request(),
            delivery_truth=_delivery_record(PropagationStatus.PENDING.value),
        )
        data = payload["data"]
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("propagation_pending", data["governance"]["codes"])
        self.assertIsNone(data["answer"]["content"])

    def test_synced_other_channel_does_not_answer(self) -> None:
        binding_refs = [
            {
                "audience_filter": _audience().to_dict(),
                "audience_label": "external:billing:free",
                "channel": "help_center",
            }
        ]
        truth = PropagationDeliveryTruth.from_propagation_rows(
            (
                (
                    _OBJECT_ID,
                    "help_center",
                    PropagationStatus.SYNCED.value,
                    binding_refs,
                ),
            )
        )
        payload = self.bridge.query_with_fixture_delivery(
            _request(), delivery_truth=truth
        )
        data = payload["data"]
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("channel_not_synced", data["governance"]["codes"])
        self.assertIsNone(data["answer"]["content"])

    def test_synced_channel_without_audience_does_not_answer(self) -> None:
        # Audience mismatch is an object-level denial: even when propagation
        # truth exists on the channel, no restricted object metadata or trace
        # may be projected into the response.
        payload = self.bridge.query_with_fixture_delivery(
            _request(audience_context=_other_audience_context()),
            delivery_truth=_delivery_record(),
        )
        data = payload["data"]
        self.assertEqual(payload["status"], "denied")
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertEqual(tuple(data["governance"]["codes"]), ("audience_restricted",))
        self.assertIsNone(data["answer"])
        self.assertEqual(data["alternatives"], [])
        self.assertIsNone(data["source_trace"])
        self.assertIsNone(payload["trace_ref"])
        self.assertIsNone(data["governance_context"]["object_id"])
        # No restricted object identifier, title, snippet, or trace survives.
        serialized = json.dumps(payload)
        self.assertNotIn(_OBJECT_ID, serialized)
        self.assertNotIn("Cancel a free-plan subscription", serialized)
        self.assertNotIn(f"trace:{_OBJECT_ID}", serialized)

    def test_stale_but_delivered_remains_restricted_with_warning(self) -> None:
        stale_snapshot = SubstrateKnowledgeSnapshot(
            objects=(_published_answer(),),
            evidence=(
                SupportEvidence(
                    evidence_id="ev-help-refund",
                    source_type=EvidenceSourceType.HELP_CENTER,
                    source_ref="help-center/billing-refunds",
                    title="Billing refund policy",
                    content="Self-serve monthly plans can request a refund within 14 days.",
                    audience_filter=_audience(),
                    product_lines=("billing",),
                    plans=("free",),
                    freshness_state=FreshnessState.STALE,
                    updated_at="2025-11-20T12:00:00Z",
                ),
            ),
        )
        payload = GovernedSessionBridge(stale_snapshot).query_with_fixture_delivery(
            _request(),
            delivery_truth=_delivery_record(),
        )
        data = payload["data"]
        self.assertEqual(payload["status"], "denied")
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("stale_evidence", data["governance"]["codes"])
        self.assertIsNone(data["answer"]["content"])
        self.assertEqual(data["answer"]["usage"], "withheld")

    def test_empty_truth_never_answers(self) -> None:
        payload = self.bridge.query_with_fixture_delivery(
            _request(),
            delivery_truth=PropagationDeliveryTruth.empty(),
        )
        data = payload["data"]
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("channel_not_synced", data["governance"]["codes"])

    def test_delivered_truth_for_objects_covers_published_objects_only(self) -> None:
        unpublished = AnswerCard(
            object_id=_DRAFT_OBJECT_ID,
            title="Draft answer",
            summary="Not yet published.",
            lifecycle_state=LifecycleState.IN_REVIEW,
            supported_audiences=(_audience(),),
            question="Draft question?",
            canonical_answer="Draft content.",
            publish_targets=("copilot",),
        )
        truth = delivered_truth_for_objects((_published_answer(), unpublished))
        self.assertEqual(len(truth.records_for(_OBJECT_ID)), 1)
        self.assertEqual(truth.records_for(_DRAFT_OBJECT_ID), ())

    def test_records_for_unknown_object_are_empty(self) -> None:
        self.assertEqual(_delivery_record().records_for(_UNKNOWN_OBJECT_ID), ())


if __name__ == "__main__":
    unittest.main()
