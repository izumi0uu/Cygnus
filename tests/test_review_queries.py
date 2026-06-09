from __future__ import annotations

import unittest

from cygnus.domain import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.review.briefing import OwnerState, ReviewRiskItem, ReviewRiskType, WhyNowFrame
from cygnus.review.queries import build_review_command_brief
from cygnus.substrate.compilation_plan import UrgencyLevel


class ReviewQueryTests(unittest.TestCase):
    def test_command_brief_sorts_higher_risk_first(self) -> None:
        low = ReviewRiskItem(
            risk_id="risk-low",
            title="Ticket pressure",
            risk_type=ReviewRiskType.TICKET_PRESSURE,
            object_type=KnowledgeObjectType.ANSWER_CARD,
            object_ref="cp-2",
            affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
            owner_state=OwnerState.ASSIGNED,
            urgency=UrgencyLevel.MEDIUM,
            why_now=WhyNowFrame(summary="Repeated tickets increased."),
        )
        high = ReviewRiskItem(
            risk_id="risk-high",
            title="Source blindness",
            risk_type=ReviewRiskType.SOURCE_BLINDNESS,
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            object_ref="cp-1",
            affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
            owner_state=OwnerState.UNASSIGNED,
            urgency=UrgencyLevel.URGENT,
            why_now=WhyNowFrame(summary="Incident source feed failed."),
        )
        brief = build_review_command_brief(
            brief_id="brief-1",
            headline="Top review risks",
            items=(low, high),
        )

        payload = brief.to_dict()
        self.assertEqual(payload["priority_items"][0]["risk_id"], "risk-high")
        self.assertEqual(payload["summary_counts"]["source_blindness"], 1)

