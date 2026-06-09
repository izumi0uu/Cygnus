from __future__ import annotations

import unittest

from cygnus.domain import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.review.briefing import (
    OwnerState,
    ReviewRiskType,
    WhyNowFrame,
    risk_item_from_proposal,
)
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)


class ReviewBriefingTests(unittest.TestCase):
    def test_risk_item_from_proposal_preserves_governance_shape(self) -> None:
        proposal = CompilationProposal(
            proposal_id="cp-brief-1",
            object_type=KnowledgeObjectType.ANSWER_CARD,
            action=PlanAction.UPDATE,
            title="Invoice export drift",
            summary="Reflect current rollout constraints.",
            evidence_ids=("ev-1",),
            urgency=UrgencyLevel.HIGH,
            evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
            review_owner="support-ops",
            why_now="Ticket rewrite pressure rose after release delta.",
        )
        item = risk_item_from_proposal(
            proposal,
            risk_id="risk-1",
            risk_type=ReviewRiskType.DRIFT,
            affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
            owner_state=OwnerState.ASSIGNED,
            affected_surfaces=("copilot",),
            trigger_signals=("release_delta",),
        )

        payload = item.to_dict()
        self.assertEqual(payload["risk_type"], "drift")
        self.assertEqual(payload["object_type"], "answer_card")
        self.assertIn("why_now", payload)
        self.assertNotIn("chunk", payload)

    def test_why_now_requires_summary(self) -> None:
        with self.assertRaises(ValueError):
            WhyNowFrame(summary=" ")

