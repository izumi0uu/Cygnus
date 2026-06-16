from __future__ import annotations

from cygnus.domain import (
    AnswerCard,
    AudienceFilter,
    AudienceVariant,
    EscalationRoute,
    KnowledgeObject,
    KnownIssuePage,
    LifecycleState,
    PolicyRule,
    TroubleshootingFlow,
    Visibility,
)
from cygnus.evidence import EvidenceSourceType, FreshnessState, SupportEvidence



def sample_support_evidence() -> tuple[SupportEvidence, ...]:
    external_enterprise_eu = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("enterprise",),
        regions=("eu",),
    )
    external_free = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("free",),
    )
    internal_billing = AudienceFilter(
        visibility=Visibility.INTERNAL,
        product_lines=("billing",),
    )

    return (
        SupportEvidence(
            evidence_id="ev-help-refund",
            source_type=EvidenceSourceType.HELP_CENTER,
            source_ref="help-center/billing-refunds",
            title="Billing refund policy",
            content="Self-serve monthly plans can request a refund within 14 days of the first payment.",
            audience_filter=external_free,
            product_lines=("billing",),
            plans=("free",),
            freshness_state=FreshnessState.FRESH,
            updated_at="2026-06-10",
            tags=("billing", "refund"),
        ),
        SupportEvidence(
            evidence_id="ev-sop-refund-exception",
            source_type=EvidenceSourceType.INTERNAL_SOP,
            source_ref="sop/refund-enterprise-exception",
            title="Enterprise refund exception",
            content="Enterprise annual contracts require support ops approval before any refund exception is granted.",
            audience_filter=internal_billing,
            product_lines=("billing",),
            plans=("enterprise",),
            freshness_state=FreshnessState.FRESH,
            updated_at="2026-06-11",
            tags=("billing", "refund", "exception"),
        ),
        SupportEvidence(
            evidence_id="ev-release-export-eu",
            source_type=EvidenceSourceType.RELEASE_NOTE,
            source_ref="release/2026-06-invoice-export-eu",
            title="EU invoice export rollout",
            content="Enterprise EU workspaces receive invoice PDF export in a staged rollout behind a feature flag.",
            audience_filter=external_enterprise_eu,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
            product_versions=("2026.06",),
            freshness_state=FreshnessState.FRESH,
            updated_at="2026-06-09",
            tags=("billing", "invoice", "export"),
        ),
        SupportEvidence(
            evidence_id="ev-incident-export-delay",
            source_type=EvidenceSourceType.INCIDENT_UPDATE,
            source_ref="incident/eu-invoice-export-delay",
            title="EU invoice export delay",
            content="Current export jobs may be delayed for some EU enterprise workspaces; use manual invoice delivery as the workaround.",
            audience_filter=external_enterprise_eu,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
            freshness_state=FreshnessState.STALE,
            updated_at="2026-06-12",
            tags=("billing", "invoice", "incident"),
        ),
        SupportEvidence(
            evidence_id="ev-ticket-verification",
            source_type=EvidenceSourceType.RESOLVED_TICKET,
            source_ref="ticket-cluster/billing-verification-2026w24",
            title="Billing verification workaround cluster",
            content="Agents repeatedly resolved verification failures by rechecking billing admin role and invoice ownership.",
            audience_filter=internal_billing,
            product_lines=("billing",),
            freshness_state=FreshnessState.UNKNOWN,
            tags=("billing", "verification", "ticket"),
        ),
    )



def sample_knowledge_objects() -> tuple[KnowledgeObject, ...]:
    external_enterprise_eu = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("enterprise",),
        regions=("eu",),
    )
    external_free = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("free",),
    )
    internal_billing = AudienceFilter(
        visibility=Visibility.INTERNAL,
        product_lines=("billing",),
    )

    escalation = EscalationRoute(
        object_id="ko-billing-escalation-route",
        title="Billing operations escalation route",
        summary="Escalate entitlement mismatches to the billing operations queue.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(internal_billing,),
        trigger_conditions=("Customer plan data and UI state disagree.",),
        destination_team="billing-ops",
        required_context=("account_id", "plan_id"),
        evidence_ids=("ev-ticket-verification",),
        tags=("billing", "escalation"),
    )

    return (
        PolicyRule(
            object_id="ko-billing-refund-policy",
            title="Billing refund policy",
            summary="Defines when frontline support may honor a refund request.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(internal_billing,),
            evidence_ids=("ev-help-refund", "ev-sop-refund-exception"),
            tags=("billing", "refund"),
            rule_domain="refund",
            rule_statement="Support may grant refunds within 14 days, but enterprise exceptions require support ops approval.",
            effective_conditions=("Only the first payment qualifies for self-serve refunds.",),
            exceptions=("Enterprise annual contracts are approval-gated.",),
            authority_source="billing-policy-v3",
        ),
        AnswerCard(
            object_id="ko-invoice-export-enterprise-eu",
            title="Invoice export for enterprise EU customers",
            summary="Explains export behavior and staged rollout constraints for enterprise EU workspaces.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(external_enterprise_eu,),
            evidence_ids=("ev-release-export-eu",),
            tags=("billing", "invoice", "export"),
            question="How do I export an invoice PDF?",
            canonical_answer="Go to Billing > Invoices and select the invoice you need. Availability depends on the staged EU rollout.",
            constraints=("Requires billing admin role.",),
            audience_variants=(
                AudienceVariant(
                    audience_filter=external_enterprise_eu,
                    label="eu-rollout-delay",
                    content="If export is delayed, support can offer manual invoice delivery while rollout stabilizes.",
                    evidence_ids=("ev-incident-export-delay",),
                ),
            ),
            publish_targets=("help_center", "copilot"),
        ),
        KnownIssuePage(
            object_id="ko-eu-invoice-delay",
            title="EU invoice export delay",
            summary="Tracks the current workaround for delayed invoice export jobs.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(external_enterprise_eu,),
            evidence_ids=("ev-incident-export-delay",),
            tags=("billing", "incident", "invoice"),
            issue_summary="Some EU enterprise workspaces experience delayed invoice PDF export jobs.",
            workaround="Use manual invoice delivery from support tooling until the incident is resolved.",
            issue_status="monitoring",
            affected_products=("billing",),
            affected_versions=("2026.06",),
            expected_next_update="2026-06-16",
        ),
        TroubleshootingFlow(
            object_id="ko-billing-verification-flow",
            title="Billing verification troubleshooting flow",
            summary="Guides internal agents through repeated verification failures.",
            lifecycle_state=LifecycleState.IN_REVIEW,
            supported_audiences=(internal_billing,),
            evidence_ids=("ev-ticket-verification",),
            tags=("billing", "verification", "troubleshooting"),
            problem_statement="Customer cannot pass billing verification during invoice export.",
            prerequisites=("Customer is signed in.",),
            steps=("Check billing admin role.", "Check invoice ownership.", "Retry export."),
            stop_conditions=("Customer can export the invoice.",),
            escalation_route_id=escalation.object_id,
        ),
        escalation,
        AnswerCard(
            object_id="ko-cancel-free-plan",
            title="Cancel a free-plan subscription",
            summary="Explains the self-serve cancel path for free-plan customers.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(external_free,),
            evidence_ids=("ev-help-refund",),
            tags=("billing", "cancel", "subscription"),
            question="How do I cancel my subscription?",
            canonical_answer="Go to Billing > Plan and choose Cancel subscription.",
            publish_targets=("copilot",),
        ),
    )
