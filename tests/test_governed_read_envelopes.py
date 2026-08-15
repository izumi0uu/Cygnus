from __future__ import annotations

import unittest
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from cygnus.domain import (
    AnswerCard,
    AudienceContext,
    AudienceFilter,
    LifecycleState,
    Visibility,
    governed_object_ref,
)
from cygnus.evidence.records import (
    EVIDENCE_INJECTION_WARNING,
    EVIDENCE_TRUST_CLASSIFICATION,
    EvidenceSourceType,
    FreshnessState,
    SupportEvidence,
)
from cygnus.retrieval import (
    AnswerabilityVerdict,
    AudienceVerdict,
    EvidenceIndex,
    GovernedReadEnvelope,
    PersistedDeliveryRecord,
    PersistedObjectTruth,
    SourceTrace,
    SourceTraceResolver,
    audience_verdict_for,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.retrieval.contracts import PublicationRecord


def _mapping(value: object) -> Mapping[str, Any]:
    """Typed envelope assertion: a decoded envelope field is a mapping."""
    assert isinstance(value, Mapping)
    return value


def _sequence(value: object) -> Sequence[Any]:
    """Sequence-aware helper: a decoded envelope field is a sequence."""
    assert isinstance(value, Sequence)
    return value


class GovernedReadEnvelopeTests(unittest.TestCase):
    """Typed schema-versioned read envelopes (CYG-139 structured output)."""

    def test_envelope_is_schema_versioned_and_structured(self) -> None:
        envelope = GovernedReadEnvelope(
            status="success",
            summary="2 matching knowledge objects found",
            audience=AudienceVerdict(
                role="viewer",
                scope="eu",
                match="exact",
                visibility="external",
                product_line="billing",
                plan="enterprise",
            ),
            answerability=AnswerabilityVerdict(
                answerable=False,
                reason="stale_evidence",
                codes=("stale_evidence",),
            ),
            data={"results": []},
            trace_ref="trace:ko-invoice-export-enterprise-eu",
            warnings=("stale_evidence_present",),
            errors=(),
        )

        payload = envelope.to_dict()
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["summary"], "2 matching knowledge objects found")
        self.assertEqual(payload["trace_ref"], "trace:ko-invoice-export-enterprise-eu")
        self.assertEqual(payload["warnings"], ["stale_evidence_present"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["data"], {"results": []})

        audience = _mapping(payload["audience"])
        self.assertEqual(audience["role"], "viewer")
        self.assertEqual(audience["scope"], "eu")
        self.assertEqual(audience["match"], "exact")
        self.assertEqual(audience["visibility"], "external")
        self.assertEqual(audience["plan"], "enterprise")

        answerability = _mapping(payload["answerability"])
        self.assertFalse(answerability["answerable"])
        self.assertEqual(answerability["reason"], "stale_evidence")
        self.assertEqual(answerability["codes"], ["stale_evidence"])

    def test_envelope_negotiates_shared_contract_major(self) -> None:
        envelope = GovernedReadEnvelope(
            status="success",
            summary="ok",
            audience=audience_verdict_for(
                None, role="viewer", scope="dept-a", match="none"
            ),
            answerability=None,
            data={},
        )
        self.assertEqual(envelope.contract_version, "1.0")

        with self.assertRaises(ValueError):
            GovernedReadEnvelope(
                status="success",
                summary="ok",
                audience=audience_verdict_for(
                    None, role="viewer", scope="dept-a", match="none"
                ),
                answerability=None,
                data={},
                contract_version="2.0",
            )

    def test_audience_verdict_is_never_omitted(self) -> None:
        verdict = audience_verdict_for(
            AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="billing",
                plan="free",
            ),
            role="contributor",
            scope="dept-billing",
            match="partial",
        )
        payload = verdict.to_dict()
        self.assertEqual(payload["role"], "contributor")
        self.assertEqual(payload["scope"], "dept-billing")
        self.assertEqual(payload["match"], "partial")
        self.assertEqual(payload["visibility"], "external")
        self.assertEqual(payload["product_line"], "billing")
        self.assertEqual(payload["plan"], "free")
        self.assertTrue(payload["required"])

        envelope = GovernedReadEnvelope(
            status="denied",
            summary="audience restricted",
            audience=verdict,
            answerability=None,
            data={},
        )
        self.assertIn("audience", envelope.to_dict())

    def test_envelope_cannot_be_constructed_without_an_audience_verdict(self) -> None:
        with self.assertRaises(TypeError):
            GovernedReadEnvelope(  # type: ignore[call-arg]
                status="success",
                summary="audience omitted",
                answerability=None,
                data={},
            )

    def test_answerability_verdict_serializes_reason_and_codes(self) -> None:
        verdict = AnswerabilityVerdict(
            answerable=False,
            reason="source_blindness",
            codes=("source_blindness", "escalate_required"),
        )
        self.assertEqual(
            verdict.to_dict(),
            {
                "answerable": False,
                "reason": "source_blindness",
                "codes": ["source_blindness", "escalate_required"],
            },
        )


class RawEvidenceTrustTests(unittest.TestCase):
    """Raw evidence stays untrusted observation data with provenance (CYG-139)."""

    def test_support_evidence_is_classified_untrusted_with_warning(self) -> None:
        evidence = sample_support_evidence()[0]
        payload = evidence.to_dict()

        trust = _mapping(payload["trust"])
        self.assertEqual(trust["classification"], EVIDENCE_TRUST_CLASSIFICATION)
        self.assertEqual(trust["classification"], "untrusted_observation")
        self.assertEqual(trust["injection_warning"], EVIDENCE_INJECTION_WARNING)
        self.assertIn("never an instruction", trust["injection_warning"])
        self.assertIn("cannot authorize any side effect", trust["injection_warning"])

        provenance = _mapping(payload["provenance"])
        self.assertEqual(provenance["source_ref"], "help-center/billing-refunds")
        self.assertEqual(provenance["source_type"], "help_center")
        self.assertEqual(provenance["captured_at"], "2026-06-10")
        self.assertEqual(provenance["revision"], "2026-06-10.3")
        self.assertEqual(payload["revision"], "2026-06-10.3")

    def test_evidence_record_is_immutable(self) -> None:
        evidence = sample_support_evidence()[0]
        with self.assertRaises(AttributeError):
            evidence.content = "mutated observation"  # type: ignore[misc]

    def test_evidence_hits_carry_untrusted_warning_by_default(self) -> None:
        index = EvidenceIndex(sample_support_evidence())
        results = index.search(query="invoice export")
        matching = next(
            item for item in results if item.evidence_id == "ev-release-export-eu"
        )
        payload = matching.to_dict()

        # Trust classification and the injection warning are immutable defaults
        # on every evidence hit; revision binding is wired at the index level.
        trust = _mapping(payload["trust"])
        self.assertEqual(trust["classification"], "untrusted_observation")
        self.assertEqual(trust["injection_warning"], EVIDENCE_INJECTION_WARNING)
        self.assertIn("revision", payload)
        self.assertIn("provenance", payload)

    def test_evidence_hit_serializes_revision_and_provenance(self) -> None:
        from cygnus.retrieval.contracts import EvidenceHit

        hit = EvidenceHit(
            evidence_id="ev-release-export-eu",
            title="EU invoice export rollout",
            source_type="release_note",
            source_ref="release/2026-06-invoice-export-eu",
            excerpt_ref="ev-release-export-eu:0-160",
            freshness=FreshnessState.FRESH,
            confidence=0.75,
            snippet="Enterprise EU workspaces receive invoice PDF export.",
            revision="2026-06-09.2",
            captured_at="2026-06-09",
        )
        payload = hit.to_dict()
        self.assertEqual(payload["revision"], "2026-06-09.2")
        self.assertEqual(payload["captured_at"], "2026-06-09")
        provenance = _mapping(payload["provenance"])
        trust = _mapping(payload["trust"])
        self.assertEqual(provenance["revision"], "2026-06-09.2")
        self.assertEqual(provenance["source_ref"], "release/2026-06-invoice-export-eu")
        self.assertEqual(trust["classification"], "untrusted_observation")
        self.assertEqual(trust["injection_warning"], EVIDENCE_INJECTION_WARNING)


class TraceVersionFreshnessTests(unittest.TestCase):
    """Traces bind object version, evidence revision, and freshness (CYG-139)."""

    def setUp(self) -> None:
        self.resolver = SourceTraceResolver(
            sample_knowledge_objects(),
            sample_support_evidence(),
        )

    def test_trace_binds_version_freshness_revision_and_trust(self) -> None:
        trace = self.resolver.get_trace("ko-invoice-export-enterprise-eu")
        assert trace is not None
        payload = trace.to_dict()

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["freshness"], "stale")

        refs = _sequence(payload["evidence_refs"])
        self.assertEqual(len(refs), 2)
        for ref in refs:
            self.assertIn("revision", ref)
            self.assertIn("freshness", ref)
            self.assertEqual(ref["trust"]["classification"], "untrusted_observation")
            self.assertIn("never an instruction", ref["trust"]["injection_warning"])
            self.assertIn("provenance", ref)

        release_ref = next(
            ref for ref in refs if ref["evidence_id"] == "ev-release-export-eu"
        )
        self.assertEqual(release_ref["revision"], "2026-06-09.2")
        self.assertEqual(release_ref["freshness"], "fresh")

        incident_ref = next(
            ref for ref in refs if ref["evidence_id"] == "ev-incident-export-delay"
        )
        self.assertEqual(incident_ref["revision"], "2026-06-12.1")
        self.assertEqual(incident_ref["freshness"], "stale")

    def test_fixture_trace_carries_explicit_synthetic_refs(self) -> None:
        trace = self.resolver.get_trace("ko-invoice-export-enterprise-eu")
        assert trace is not None
        publications = _sequence(trace.to_dict()["publication_records"])

        self.assertEqual(
            {record["channel"] for record in publications},
            {"help_center", "copilot"},
        )
        for record in publications:
            self.assertTrue(
                record["publication_ref"].startswith(
                    "fixture-pub:ko-invoice-export-enterprise-eu:"
                )
            )
            self.assertIn(":v1", record["publication_ref"])
            self.assertEqual(
                record["propagation_refs"],
                [
                    "fixture-prop:ko-invoice-export-enterprise-eu:"
                    f"{record['channel']}:v1"
                ],
            )
            self.assertEqual(record["delivery_refs"], [])

    def test_unpublished_object_has_no_publication_records(self) -> None:
        trace = self.resolver.get_trace("ko-billing-verification-flow")
        assert trace is not None
        self.assertEqual(trace.to_dict()["publication_records"], [])


class PersistedTraceFreshnessTests(unittest.TestCase):
    """Durable identity and source coverage jointly gate trace freshness."""

    _PAGE_ID = uuid.UUID("00000000-0000-4000-8000-000000000101")
    _SOURCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000102")
    _PUBLICATION_ID = uuid.UUID("00000000-0000-4000-8000-000000000103")
    _PROPAGATION_ID = uuid.UUID("00000000-0000-4000-8000-000000000104")
    _DELIVERY_ID = uuid.UUID("00000000-0000-4000-8000-000000000105")
    _MISMATCHED_PAGE_ID = uuid.UUID("00000000-0000-4000-8000-000000000107")

    def _trace(
        self,
        *,
        expected_page_version: int = 4,
        source_evidence_complete: bool = True,
        publication_state: str = "synced",
        trace_delivery_id: uuid.UUID = _DELIVERY_ID,
        object_page_id: uuid.UUID = _PAGE_ID,
    ) -> SourceTrace:
        audience = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
        )
        context = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="enterprise",
        )
        object_id = governed_object_ref(object_page_id)
        evidence_id = (
            f"ev-page-{self._PAGE_ID}-src-{self._SOURCE_ID}-binding-copilot-enterprise"
        )
        object_ = AnswerCard(
            object_id=object_id,
            title="Current invoice guidance",
            summary="Current governed guidance.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(audience,),
            evidence_ids=(evidence_id,),
            question="How do I export an invoice?",
            canonical_answer="Open Billing and select the invoice.",
            publish_targets=("copilot",),
        )
        evidence = SupportEvidence(
            evidence_id=evidence_id,
            source_type=EvidenceSourceType.HELP_CENTER,
            source_ref="help-center/invoice-export",
            title="Invoice export",
            content="Enterprise invoice export is available from Billing.",
            audience_filter=audience,
            freshness_state=FreshnessState.FRESH,
            revision="2026-08-15.1",
        )
        publication = PublicationRecord(
            channel="copilot",
            publication_state=publication_state,
            publication_ref=str(self._PUBLICATION_ID),
            propagation_refs=(str(self._PROPAGATION_ID),),
            delivery_refs=(str(trace_delivery_id),),
        )
        truth = PersistedObjectTruth(
            page_id=str(self._PAGE_ID),
            page_version=4,
            approval_version=2,
            source_evidence_complete=source_evidence_complete,
            truth_token="durable-truth-v4",
            publication_records=(publication,),
        )
        delivery = PersistedDeliveryRecord(
            page_id=str(self._PAGE_ID),
            publication_id=str(self._PUBLICATION_ID),
            propagation_id=str(self._PROPAGATION_ID),
            delivery_id=str(self._DELIVERY_ID),
            channel="copilot",
            binding_key="copilot-enterprise",
            binding_version=3,
            audience_filter=audience,
            propagation_status="synced",
            delivery_status="synced",
            propagation_digest="digest-v4",
            desired_digest="digest-v4",
            acknowledged_digest="digest-v4",
            expected_page_version=expected_page_version,
            expected_approval_version=2,
            acknowledged_version=expected_page_version,
        )
        resolver = SourceTraceResolver(
            (object_,),
            (evidence,),
            persisted_truth_by_object={object_id: truth},
            delivery_records_by_object={object_id: (delivery,)},
        )
        trace = resolver.get_trace(
            object_id,
            audience_context=context,
            channel="copilot",
        )
        assert trace is not None
        return trace

    def test_current_signed_delivery_exposes_exact_trace_chain(self) -> None:
        trace = self._trace()

        self.assertIs(trace.freshness, FreshnessState.FRESH)
        self.assertEqual(trace.version, 4)
        self.assertEqual(len(trace.evidence_refs), 1)
        self.assertEqual(
            [record.to_dict() for record in trace.publication_records],
            [
                {
                    "channel": "copilot",
                    "publication_state": "synced",
                    "publication_ref": str(self._PUBLICATION_ID),
                    "propagation_refs": [str(self._PROPAGATION_ID)],
                    "delivery_refs": [str(self._DELIVERY_ID)],
                }
            ],
        )

    def test_version_or_trace_identity_mismatch_fails_closed(self) -> None:
        cases = (
            (
                {"expected_page_version": 3},
                "signed_delivery_not_current",
            ),
            (
                {
                    "trace_delivery_id": uuid.UUID(
                        "00000000-0000-4000-8000-000000000106"
                    )
                },
                "publication_delivery_trace_mismatch",
            ),
            (
                {"publication_state": "pending"},
                "publication_delivery_trace_mismatch",
            ),
            (
                {"object_page_id": self._MISMATCHED_PAGE_ID},
                "object_identity_mismatch",
            ),
        )
        for overrides, expected_blind_spot in cases:
            with self.subTest(expected_blind_spot=expected_blind_spot):
                trace = self._trace(**overrides)
                self.assertIs(trace.freshness, FreshnessState.UNKNOWN)
                self.assertEqual(trace.evidence_refs, ())
                self.assertEqual(trace.publication_records, ())
                self.assertEqual(trace.blind_spots, (expected_blind_spot,))

    def test_incomplete_sources_withhold_evidence_but_keep_current_refs(
        self,
    ) -> None:
        trace = self._trace(source_evidence_complete=False)

        self.assertIs(trace.freshness, FreshnessState.UNKNOWN)
        self.assertEqual(trace.evidence_refs, ())
        self.assertEqual(trace.blind_spots, ("source_evidence_incomplete",))
        self.assertEqual(
            trace.publication_records[0].delivery_refs,
            (str(self._DELIVERY_ID),),
        )


if __name__ == "__main__":
    unittest.main()
