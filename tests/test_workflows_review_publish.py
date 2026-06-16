from __future__ import annotations

import unittest

from cygnus.domain.objects import KnowledgeObjectType
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)
from cygnus.substrate.pipeline_phases import PipelinePhase
from cygnus.workflows.review_publish import ReviewPublishWorkflow


class ReviewPublishWorkflowTests(unittest.TestCase):
    def test_workflow_tracks_phase_and_proposals(self) -> None:
        proposal = CompilationProposal(
            proposal_id="cp-2",
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            action=PlanAction.UPDATE,
            title="Update known issue page",
            summary="Reflect new workaround in the governed issue page.",
            evidence_ids=("ev-3",),
            urgency=UrgencyLevel.URGENT,
            evidence_sufficiency=EvidenceSufficiency.PARTIAL,
            review_owner="knowledge-manager",
            why_now="Incident escalation volume is increasing.",
        )
        workflow = ReviewPublishWorkflow(workflow_id="wf-1", proposals=(proposal,))

        workflow.advance(PipelinePhase.NORMALIZE)
        workflow.advance(PipelinePhase.MAP_REDUCE)
        workflow.advance(PipelinePhase.PLAN)
        workflow.add_review_note("Need confirmation on external wording.")

        payload = workflow.to_dict()
        self.assertEqual(payload["current_phase"], "plan")
        self.assertEqual(
            payload["completed_phases"],
            ["ingest", "normalize", "map_reduce"],
        )
        self.assertEqual(payload["resume_phase"], "plan")
        self.assertFalse(payload["is_complete"])
        self.assertEqual(payload["proposals"][0]["object_type"], "known_issue_page")
        self.assertEqual(payload["review_notes"], ["Need confirmation on external wording."])
