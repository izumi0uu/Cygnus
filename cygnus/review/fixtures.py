from __future__ import annotations

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.review.briefing import OwnerState, ReviewRiskType, risk_item_from_proposal
from cygnus.review.queries import build_review_command_brief
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)



def sample_review_command_brief() -> dict[str, object]:
    eu_enterprise = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("enterprise",),
        regions=("eu",),
    )
    internal_billing = AudienceFilter(
        visibility=Visibility.INTERNAL,
        product_lines=("billing",),
    )

    drift_proposal = CompilationProposal(
        proposal_id="cp-drift-1",
        object_type=KnowledgeObjectType.ANSWER_CARD,
        action=PlanAction.UPDATE,
        title="Invoice export answer is drifting from current rollout",
        summary="External answer must reflect EU enterprise rollout constraints.",
        evidence_ids=("ev-release-1", "ev-ticket-2"),
        urgency=UrgencyLevel.HIGH,
        evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
        review_owner="support-ops",
        why_now="Release-note delta and repeated rewrites indicate active drift.",
    )
    source_proposal = CompilationProposal(
        proposal_id="cp-source-1",
        object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
        action=PlanAction.UPDATE,
        title="Known issue page is now partially blind due to source sync failure",
        summary="Incident source interruption weakens confidence in current workaround status.",
        evidence_ids=("ev-incident-1",),
        urgency=UrgencyLevel.URGENT,
        evidence_sufficiency=EvidenceSufficiency.PARTIAL,
        review_owner="knowledge-manager",
        why_now="The incident update source failed during an active customer-facing issue.",
    )

    items = (
        risk_item_from_proposal(
            source_proposal,
            risk_id="risk-2",
            risk_type=ReviewRiskType.SOURCE_BLINDNESS,
            affected_audiences=(eu_enterprise, internal_billing),
            owner_state=OwnerState.UNASSIGNED,
            affected_surfaces=("help_center", "copilot"),
            trigger_signals=("source_sync_failed", "active_incident"),
            recommended_actions=("open_review", "restrict_publish", "assign_owner"),
        ),
        risk_item_from_proposal(
            drift_proposal,
            risk_id="risk-1",
            risk_type=ReviewRiskType.DRIFT,
            affected_audiences=(eu_enterprise,),
            owner_state=OwnerState.ASSIGNED,
            affected_surfaces=("copilot", "help_center"),
            trigger_signals=("release_delta", "rewrite_cluster", "ticket_pressure"),
            recommended_actions=("open_review", "mark_urgent"),
        ),
    )
    brief = build_review_command_brief(
        brief_id="brief-1",
        headline="Today’s highest-leverage governance risks",
        items=items,
    )
    return brief.to_dict()
