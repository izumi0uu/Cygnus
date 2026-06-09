from __future__ import annotations

import unittest

from cygnus.domain import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence import EvidenceSourceType, FreshnessState, SupportEvidence
from cygnus.review import (
    OwnerState,
    ProposalBundle,
    ReviewRiskType,
    ReviewSignal,
    assemble_review_command_brief,
    build_review_risk_item,
    rank_review_item,
)
from cygnus.substrate import CompilationProposal, EvidenceSufficiency, PlanAction, UrgencyLevel


class ReviewServiceTests(unittest.TestCase):
    def test_build_review_risk_item_enriches_why_now_and_actions(self) -> None:
        proposal = CompilationProposal(
            proposal_id="cp-risk-1",
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            action=PlanAction.UPDATE,
            title="Incident workaround confidence is degrading",
            summary="Known issue needs governance review.",
            evidence_ids=("ev-incident-1",),
            urgency=UrgencyLevel.URGENT,
            evidence_sufficiency=EvidenceSufficiency.PARTIAL,
            review_owner="knowledge-manager",
            why_now="Incident updates have changed twice in the last hour",
        )
        signal = ReviewSignal(
            proposal_id="cp-risk-1",
            risk_type=ReviewRiskType.SOURCE_BLINDNESS,
            affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
            affected_surfaces=("help_center", "copilot"),
            trigger_signals=("source_sync_failed",),
            queue_owner=None,
            recommended_actions=("open_review",),
        )
        evidence = SupportEvidence(
            evidence_id="ev-incident-1",
            source_type=EvidenceSourceType.INCIDENT_UPDATE,
            source_ref="incident/123",
            title="Incident update",
            content="Workaround is no longer globally valid.",
            audience_filter=AudienceFilter(visibility=Visibility.EXTERNAL),
            freshness_state=FreshnessState.STALE,
        )

        item = build_review_risk_item(ProposalBundle(proposal=proposal, signal=signal, evidence=(evidence,)))
        payload = item.to_dict()

        self.assertEqual(payload["risk_id"], "source_blindness:cp-risk-1")
        self.assertEqual(payload["owner_state"], "assigned")
        self.assertIn("stale_evidence", payload["why_now"]["trigger_signals"])
        self.assertIn("request_more_evidence", payload["recommended_actions"])
        self.assertIn("refresh_sources", payload["recommended_actions"])
        self.assertIn("mark_urgent", payload["recommended_actions"])
        self.assertIn("source coverage is degraded", payload["why_now"]["summary"])

    def test_assemble_review_command_brief_returns_ranked_brief_payload(self) -> None:
        external = AudienceFilter(visibility=Visibility.EXTERNAL)
        proposal_high = CompilationProposal(
            proposal_id="cp-high",
            object_type=KnowledgeObjectType.ANSWER_CARD,
            action=PlanAction.UPDATE,
            title="Enterprise billing answer is drifting",
            summary="Customer-facing answer should reflect the rollout delta.",
            evidence_ids=("ev-release-1",),
            urgency=UrgencyLevel.HIGH,
            evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
            review_owner="support-ops",
            why_now="Release note delta is causing human rewrites",
        )
        proposal_low = CompilationProposal(
            proposal_id="cp-low",
            object_type=KnowledgeObjectType.ANSWER_CARD,
            action=PlanAction.CREATE,
            title="Ticket cluster suggests reusable macro",
            summary="Potential draft for repeated tickets.",
            evidence_ids=("ev-ticket-1",),
            urgency=UrgencyLevel.MEDIUM,
            evidence_sufficiency=EvidenceSufficiency.PARTIAL,
            review_owner="support-ops",
            why_now="Escalation queue is seeing repeated variants",
        )
        bundles = (
            ProposalBundle(
                proposal=proposal_low,
                signal=ReviewSignal(
                    proposal_id="cp-low",
                    risk_type=ReviewRiskType.TICKET_PRESSURE,
                    affected_audiences=(external,),
                    affected_surfaces=("copilot",),
                    trigger_signals=("ticket_pressure",),
                ),
            ),
            ProposalBundle(
                proposal=proposal_high,
                signal=ReviewSignal(
                    proposal_id="cp-high",
                    risk_type=ReviewRiskType.DRIFT,
                    affected_audiences=(external,),
                    affected_surfaces=("help_center", "copilot"),
                    trigger_signals=("release_delta", "rewrite_cluster"),
                ),
            ),
        )

        payload = assemble_review_command_brief(
            brief_id="brief-ranked",
            headline="Review priorities for the current shift",
            bundles=bundles,
        )

        self.assertEqual(payload["priority_items"][0]["object_ref"], "cp-high")
        self.assertEqual(payload["summary_counts"]["drift"], 1)
        self.assertEqual(payload["summary_counts"]["ticket_pressure"], 1)

    def test_rank_review_item_prefers_unassigned_source_blindness_when_urgency_matches(self) -> None:
        proposal_a = CompilationProposal(
            proposal_id="cp-a",
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            action=PlanAction.UPDATE,
            title="Source blindness",
            summary="A",
            evidence_ids=("ev-a",),
            urgency=UrgencyLevel.HIGH,
            evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
            review_owner="ops",
            why_now="A",
        )
        proposal_b = CompilationProposal(
            proposal_id="cp-b",
            object_type=KnowledgeObjectType.ANSWER_CARD,
            action=PlanAction.UPDATE,
            title="Drift",
            summary="B",
            evidence_ids=("ev-b",),
            urgency=UrgencyLevel.HIGH,
            evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
            review_owner="ops",
            why_now="B",
        )
        source_item = build_review_risk_item(
            ProposalBundle(
                proposal=proposal_a,
                signal=ReviewSignal(
                    proposal_id="cp-a",
                    risk_type=ReviewRiskType.SOURCE_BLINDNESS,
                    affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
                    affected_surfaces=("help_center",),
                    trigger_signals=("source_sync_failed",),
                ),
                owner_state=OwnerState.UNASSIGNED,
            )
        )
        drift_item = build_review_risk_item(
            ProposalBundle(
                proposal=proposal_b,
                signal=ReviewSignal(
                    proposal_id="cp-b",
                    risk_type=ReviewRiskType.DRIFT,
                    affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
                    affected_surfaces=("copilot",),
                    trigger_signals=("release_delta",),
                    queue_owner="support-ops",
                ),
                owner_state=None,
            )
        )

        ranked = sorted((drift_item, source_item), key=rank_review_item)
        self.assertEqual(ranked[0].object_ref, "cp-a")
