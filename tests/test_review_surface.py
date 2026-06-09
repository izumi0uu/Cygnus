from __future__ import annotations

import unittest

from cygnus.domain import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.review import OwnerState, PriorityStackCard, ReviewCommandBrief, ReviewCommandSurface, ReviewRiskItem, ReviewRiskType, SituationFrame, build_review_command_brief
from cygnus.review.briefing import WhyNowFrame
from cygnus.substrate import UrgencyLevel


class ReviewSurfaceTests(unittest.TestCase):
    def test_review_command_surface_to_dict_includes_situation_frame_and_priority_stack(self) -> None:
        item = ReviewRiskItem(
            risk_id="risk-1",
            title="Source blindness",
            risk_type=ReviewRiskType.SOURCE_BLINDNESS,
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            object_ref="cp-1",
            affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
            owner_state=OwnerState.UNASSIGNED,
            urgency=UrgencyLevel.URGENT,
            why_now=WhyNowFrame(
                summary="Incident feed failed during active support pressure.",
                affected_surfaces=("help_center", "copilot"),
            ),
            recommended_actions=("open_review", "assign_owner"),
        )
        brief = build_review_command_brief(
            brief_id="brief-1",
            headline="Today’s highest-leverage governance risks",
            items=(item,),
        )
        surface = ReviewCommandSurface(
            surface_id="review-home",
            headline=brief.headline,
            situation_frame=SituationFrame(
                briefing_note="Morning command brief before opening any draft detail.",
                summary="1 governance risk is stacked for command attention.",
                primary_tension="Incident feed failed during active support pressure.",
                urgent_items=1,
                owner_gaps=1,
                affected_surfaces=("help_center", "copilot"),
                recommended_commands=("open_review", "assign_owner"),
            ),
            priority_stack=(
                PriorityStackCard(
                    risk_id="risk-1",
                    title="Source blindness",
                    risk_type=ReviewRiskType.SOURCE_BLINDNESS,
                    urgency=UrgencyLevel.URGENT,
                    object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
                    object_ref="cp-1",
                    why_now_summary="Incident feed failed during active support pressure.",
                    audience_labels=("external · global",),
                    affected_audiences=(AudienceFilter(visibility=Visibility.EXTERNAL),),
                    affected_surfaces=("help_center", "copilot"),
                    owner_state=OwnerState.UNASSIGNED,
                    queue_owner=None,
                    command_actions=("open_review", "assign_owner"),
                    primary_command="assign_owner",
                ),
            ),
            available_commands=("open_review", "assign_owner"),
            command_brief=brief,
        )

        payload = surface.to_dict()
        self.assertEqual(payload["surface_id"], "review-home")
        self.assertIn("situation_frame", payload)
        self.assertEqual(payload["priority_stack"][0]["owner_state"], "unassigned")
        self.assertEqual(payload["command_brief"]["brief_id"], "brief-1")
