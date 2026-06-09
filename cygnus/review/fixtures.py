from __future__ import annotations

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence
from cygnus.review.briefing import OwnerState, ReviewRiskType
from cygnus.review.providers import build_review_command_surface_from_bundles
from cygnus.review.service import ProposalBundle, ReviewSignal, assemble_review_command_brief
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)


def sample_review_bundles() -> tuple[ProposalBundle, ...]:
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

    return (
        ProposalBundle(
            proposal=source_proposal,
            signal=ReviewSignal(
                proposal_id="cp-source-1",
                risk_type=ReviewRiskType.SOURCE_BLINDNESS,
                affected_audiences=(eu_enterprise, internal_billing),
                affected_surfaces=("help_center", "copilot"),
                trigger_signals=("source_sync_failed", "active_incident"),
                recommended_actions=("open_review", "restrict_publish", "assign_owner"),
            ),
            evidence=(
                SupportEvidence(
                    evidence_id="ev-incident-1",
                    source_type=EvidenceSourceType.INCIDENT_UPDATE,
                    source_ref="incident/sev2-eu-billing",
                    title="Incident stream update",
                    content="Current workaround confidence is degraded while source sync is interrupted.",
                    audience_filter=eu_enterprise,
                    freshness_state=FreshnessState.STALE,
                ),
            ),
            owner_state=OwnerState.UNASSIGNED,
        ),
        ProposalBundle(
            proposal=drift_proposal,
            signal=ReviewSignal(
                proposal_id="cp-drift-1",
                risk_type=ReviewRiskType.DRIFT,
                affected_audiences=(eu_enterprise,),
                affected_surfaces=("copilot", "help_center"),
                trigger_signals=("release_delta", "rewrite_cluster", "ticket_pressure"),
                recommended_actions=("open_review", "mark_urgent"),
            ),
            evidence=(
                SupportEvidence(
                    evidence_id="ev-release-1",
                    source_type=EvidenceSourceType.RELEASE_NOTE,
                    source_ref="release/2026-06-09-eu-billing",
                    title="EU billing rollout note",
                    content="Invoice export behavior now differs for enterprise EU tenants.",
                    audience_filter=eu_enterprise,
                    freshness_state=FreshnessState.FRESH,
                ),
            ),
            owner_state=OwnerState.ASSIGNED,
        ),
    )



def sample_review_command_brief() -> dict[str, object]:
    return assemble_review_command_brief(
        brief_id="brief-1",
        headline="Today’s highest-leverage governance risks",
        bundles=sample_review_bundles(),
    )



def sample_review_command_surface() -> dict[str, object]:
    return build_review_command_surface_from_bundles(
        surface_id="review-home",
        headline="Today’s highest-leverage governance risks",
        briefing_note="Morning command brief before opening any draft detail.",
        bundles=sample_review_bundles(),
    ).to_dict()
