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
    us_free = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("free",),
        regions=("us",),
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
    ticket_pressure_proposal = CompilationProposal(
        proposal_id="cp-ticket-1",
        object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
        action=PlanAction.CREATE,
        title="Billing verification tickets now repeat the same workaround path",
        summary="Recurring escalations suggest a reusable troubleshooting flow should enter review.",
        evidence_ids=("ev-ticket-cluster-1",),
        urgency=UrgencyLevel.MEDIUM,
        evidence_sufficiency=EvidenceSufficiency.PARTIAL,
        review_owner="escalation-lead",
        why_now="A repeated ticket cluster is consuming frontline handling time without a canonical flow.",
    )
    audience_mismatch_proposal = CompilationProposal(
        proposal_id="cp-audience-1",
        object_type=KnowledgeObjectType.POLICY_RULE,
        action=PlanAction.UPDATE,
        title="Refund policy answer is leaking enterprise exceptions to free-plan users",
        summary="Audience split must be corrected before external publish continues unchanged.",
        evidence_ids=("ev-policy-1",),
        urgency=UrgencyLevel.HIGH,
        evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
        review_owner="support-ops",
        why_now="A frontline rewrite shows the current answer path is crossing the wrong plan boundary.",
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
            proposal=audience_mismatch_proposal,
            signal=ReviewSignal(
                proposal_id="cp-audience-1",
                risk_type=ReviewRiskType.AUDIENCE_MISMATCH,
                affected_audiences=(us_free, eu_enterprise),
                affected_surfaces=("help_center", "copilot", "macro"),
                trigger_signals=("rewrite_cluster", "audience_boundary_conflict"),
                recommended_actions=("open_review", "restrict_publish", "split_variant"),
            ),
            evidence=(
                SupportEvidence(
                    evidence_id="ev-policy-1",
                    source_type=EvidenceSourceType.INTERNAL_SOP,
                    source_ref="policy/refund-enterprise-exceptions",
                    title="Refund exception policy",
                    content="Enterprise-only exceptions must not appear in free-plan external answers.",
                    audience_filter=internal_billing,
                    freshness_state=FreshnessState.FRESH,
                ),
            ),
            owner_state=OwnerState.ASSIGNED,
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
        ProposalBundle(
            proposal=ticket_pressure_proposal,
            signal=ReviewSignal(
                proposal_id="cp-ticket-1",
                risk_type=ReviewRiskType.TICKET_PRESSURE,
                affected_audiences=(internal_billing,),
                affected_surfaces=("copilot", "queue-sidebar"),
                trigger_signals=("ticket_pressure", "rewrite_cluster"),
                recommended_actions=("open_review", "assign_owner", "request_more_evidence"),
            ),
            evidence=(
                SupportEvidence(
                    evidence_id="ev-ticket-cluster-1",
                    source_type=EvidenceSourceType.RESOLVED_TICKET,
                    source_ref="cluster/billing-verification-2026w24",
                    title="Billing verification cluster",
                    content="Agents keep reconstructing the same workaround from memory during escalations.",
                    audience_filter=internal_billing,
                    freshness_state=FreshnessState.UNKNOWN,
                ),
            ),
            owner_state=OwnerState.UNASSIGNED,
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
