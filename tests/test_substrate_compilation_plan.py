from __future__ import annotations

import unittest

from cygnus.domain.objects import KnowledgeObjectType
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)


class CompilationPlanTests(unittest.TestCase):
    def test_proposal_targets_support_native_object_type(self) -> None:
        proposal = CompilationProposal(
            proposal_id="cp-1",
            object_type=KnowledgeObjectType.ANSWER_CARD,
            action=PlanAction.CREATE,
            title="Create invoice export answer card",
            summary="Promote repeated export guidance into a governed answer card.",
            evidence_ids=("ev-1", "ev-2"),
            urgency=UrgencyLevel.HIGH,
            evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
            review_owner="support-ops",
            why_now="Repeated ticket cluster and release-note delta are aligned.",
            audience_notes=("EU enterprise rollout only",),
        )

        payload = proposal.to_dict()
        self.assertEqual(payload["object_type"], "answer_card")
        self.assertNotEqual(payload["object_type"], "wiki_page")
        self.assertEqual(payload["urgency"], "high")

