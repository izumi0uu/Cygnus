from __future__ import annotations

from cygnus.domain import (
    AnswerCard,
    AudienceContext,
    AudienceFilter,
    KnownIssuePage,
    LifecycleState,
    PolicyRule,
    TroubleshootingFlow,
    Visibility,
)
from .contracts import EvalCase, EvalExpectation, PolicyExpectation
from cygnus.evidence import EvidenceSourceType, FreshnessState, SupportEvidence


def _plan_tier_refund_cases() -> tuple[EvalCase, ...]:
    free_external = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("free",),
        languages=("en",),
    )
    free_refund_evidence = SupportEvidence(
        evidence_id="ev-refund-free-help",
        source_type=EvidenceSourceType.HELP_CENTER,
        source_ref="help-center/refunds/free-plan",
        title="Free-plan first-payment refund window",
        content=(
            "Free-plan customers may request a refund within 14 days of their "
            "first paid upgrade."
        ),
        audience_filter=free_external,
        product_lines=("billing",),
        plans=("free",),
        languages=("en",),
        tags=("refund", "free-plan"),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-01T09:00:00Z",
    )
    free_refund_answer = AnswerCard(
        object_id="ko-refund-free-plan",
        title="Free-plan first-payment refunds",
        summary="Explains the supported refund window for a free-plan upgrade.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(free_external,),
        evidence_ids=(free_refund_evidence.evidence_id,),
        tags=("billing", "refund", "free-plan"),
        question="Can a free-plan customer refund their first paid upgrade?",
        canonical_answer=(
            "Yes. The customer may request a refund within 14 days of the first "
            "paid upgrade."
        ),
        constraints=("The request must concern the first paid upgrade.",),
        publish_targets=("help_center", "copilot"),
    )

    enterprise_internal = AudienceFilter(
        visibility=Visibility.INTERNAL,
        product_lines=("billing",),
        plans=("enterprise",),
        languages=("en",),
    )
    enterprise_refund_evidence = SupportEvidence(
        evidence_id="ev-refund-enterprise-sop",
        source_type=EvidenceSourceType.INTERNAL_SOP,
        source_ref="sop/billing/enterprise-refund-exceptions",
        title="Enterprise refund exception approval",
        content=(
            "Enterprise annual-contract refund exceptions require Billing Ops "
            "approval and must not be promised to customers."
        ),
        audience_filter=enterprise_internal,
        product_lines=("billing",),
        plans=("enterprise",),
        languages=("en",),
        tags=("refund", "enterprise", "approval"),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-02T11:30:00Z",
    )
    enterprise_refund_policy = PolicyRule(
        object_id="ko-refund-enterprise-policy",
        title="Enterprise refund exception policy",
        summary="Defines the internal approval boundary for enterprise refunds.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(enterprise_internal,),
        evidence_ids=(enterprise_refund_evidence.evidence_id,),
        tags=("billing", "refund", "enterprise"),
        rule_domain="enterprise_refund",
        rule_statement=(
            "Only Billing Ops may approve an enterprise annual-contract refund "
            "exception."
        ),
        effective_conditions=("The account uses an enterprise annual contract.",),
        exceptions=("No self-serve or frontline exception is authorized.",),
        authority_source="billing-policy-2026-08",
        human_override_notes=("Escalate with contract and payment references.",),
    )

    return (
        EvalCase(
            case_id="plan-tier-refund-01-free-supported",
            family="plan_tier_refund",
            title="Free-plan refund guidance is answerable",
            query="free plan first paid upgrade refund window",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="billing",
                plan="free",
                language="en",
            ),
            objects=(free_refund_answer,),
            evidence=(free_refund_evidence,),
            expectation=EvalExpectation(
                disposition="answerable",
                object_refs=(free_refund_answer.object_id,),
                evidence_refs=(free_refund_evidence.evidence_id,),
                trace_refs=(f"trace:{free_refund_answer.object_id}",),
                citation_refs=(free_refund_evidence.evidence_id,),
                freshness=FreshnessState.FRESH,
                policy=PolicyExpectation(
                    draft_status="approved",
                    page_version=3,
                    expected_version=3,
                    is_admin=True,
                    expected_status="success",
                ),
            ),
            citation_text=(
                "The 14-day first-upgrade window is documented in "
                "[ev-refund-free-help]."
            ),
        ),
        EvalCase(
            case_id="plan-tier-refund-02-enterprise-restricted",
            family="plan_tier_refund",
            title="Internal enterprise refund policy stays restricted",
            query="enterprise annual contract refund exception approval",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="billing",
                plan="enterprise",
                language="en",
            ),
            objects=(enterprise_refund_policy,),
            evidence=(enterprise_refund_evidence,),
            expectation=EvalExpectation(
                disposition="restricted",
                forbidden_object_refs=(enterprise_refund_policy.object_id,),
                policy=PolicyExpectation(
                    draft_status="pending",
                    page_version=2,
                    expected_version=2,
                    expected_status="approval_required",
                    expected_error="approval_required",
                ),
            ),
        ),
    )


def _product_version_known_issue_cases() -> tuple[EvalCase, ...]:
    desktop_v42_external = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("desktop",),
        product_versions=("4.2.1",),
        languages=("en",),
    )
    v42_issue_evidence = SupportEvidence(
        evidence_id="ev-desktop-v421-sync-release",
        source_type=EvidenceSourceType.RELEASE_NOTE,
        source_ref="release-notes/desktop/4.2.1",
        title="Desktop 4.2.1 sync repair",
        content=(
            "Desktop 4.2.1 can stall during the first sync. Restarting once after "
            "the migration completes restores normal sync."
        ),
        audience_filter=desktop_v42_external,
        product_lines=("desktop",),
        product_versions=("4.2.1",),
        languages=("en",),
        tags=("desktop", "sync", "known-issue"),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-03T15:00:00Z",
    )
    v42_issue = KnownIssuePage(
        object_id="ko-desktop-v421-sync-issue",
        title="Desktop 4.2.1 first-sync stall",
        summary="Tracks the supported workaround for the 4.2.1 first-sync stall.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(desktop_v42_external,),
        evidence_ids=(v42_issue_evidence.evidence_id,),
        tags=("desktop", "sync", "known-issue"),
        issue_summary="The first sync can stall after upgrading to desktop 4.2.1.",
        workaround="Let migration finish, then restart the desktop app once.",
        issue_status="monitoring",
        affected_products=("desktop",),
        affected_versions=("4.2.1",),
        expected_next_update="2026-08-15",
    )
    unsupported_evidence = SupportEvidence(
        evidence_id="ev-desktop-v421-sync-unsupported-query",
        source_type=EvidenceSourceType.RELEASE_NOTE,
        source_ref="release-notes/desktop/4.2.1",
        title="Desktop 4.2.1 first-sync stall",
        content="Desktop 4.2.1 may stall during its first sync.",
        audience_filter=desktop_v42_external,
        product_lines=("desktop",),
        product_versions=("4.2.1",),
        languages=("en",),
        tags=("desktop", "sync", "known-issue"),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-03T15:00:00Z",
    )
    unsupported_issue = KnownIssuePage(
        object_id="ko-desktop-v421-sync-unsupported-query",
        title="Desktop 4.2.1 first-sync stall",
        summary="Tracks the supported workaround for the 4.2.1 first-sync stall.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(desktop_v42_external,),
        evidence_ids=(unsupported_evidence.evidence_id,),
        tags=("desktop", "sync", "known-issue"),
        issue_summary="The first sync can stall after upgrading to desktop 4.2.1.",
        workaround="Let migration finish, then restart the desktop app once.",
        issue_status="monitoring",
        affected_products=("desktop",),
        affected_versions=("4.2.1",),
        expected_next_update="2026-08-15",
    )

    return (
        EvalCase(
            case_id="product-version-known-issue-01-v42-supported",
            family="product_version_known_issue",
            title="Known desktop issue resolves for the affected version",
            query="desktop 4.2.1 first sync stall workaround",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="desktop",
                language="en",
                product_version="4.2.1",
            ),
            objects=(v42_issue,),
            evidence=(v42_issue_evidence,),
            expectation=EvalExpectation(
                disposition="answerable",
                object_refs=(v42_issue.object_id,),
                evidence_refs=(v42_issue_evidence.evidence_id,),
                trace_refs=(f"trace:{v42_issue.object_id}",),
                citation_refs=(v42_issue_evidence.evidence_id,),
                freshness=FreshnessState.FRESH,
            ),
            citation_text=(
                "The restart workaround is grounded in [ev-desktop-v421-sync-release]."
            ),
        ),
        EvalCase(
            case_id="product-version-known-issue-02-legacy-unsupported",
            family="product_version_known_issue",
            title="Unrecognized legacy crash has no governed answer",
            query="legacy 3.9 cobalt renderer deadlock remedy",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="desktop",
                language="en",
                product_version="3.9.0",
            ),
            objects=(unsupported_issue,),
            evidence=(unsupported_evidence,),
            expectation=EvalExpectation(disposition="fallback"),
        ),
    )


def _region_feature_availability_cases() -> tuple[EvalCase, ...]:
    analytics_eu_external = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("analytics",),
        plans=("enterprise",),
        regions=("eu",),
        languages=("en",),
    )
    eu_rollout_evidence = SupportEvidence(
        evidence_id="ev-analytics-eu-audit-export",
        source_type=EvidenceSourceType.RELEASE_NOTE,
        source_ref="release-notes/analytics/eu-audit-export",
        title="EU analytics audit export availability",
        content=(
            "Audit-log export is available to enterprise analytics workspaces in "
            "the EU region."
        ),
        audience_filter=analytics_eu_external,
        product_lines=("analytics",),
        plans=("enterprise",),
        regions=("eu",),
        languages=("en",),
        tags=("analytics", "audit-export", "eu"),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-04T08:45:00Z",
    )
    eu_rollout_answer = AnswerCard(
        object_id="ko-analytics-eu-audit-export",
        title="EU enterprise audit-log export availability",
        summary="States where enterprise audit-log export is currently available.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(analytics_eu_external,),
        evidence_ids=(eu_rollout_evidence.evidence_id,),
        tags=("analytics", "audit-export", "eu"),
        question="Is audit-log export available in this region?",
        canonical_answer=(
            "Audit-log export is available for enterprise analytics workspaces "
            "in the EU region."
        ),
        constraints=("The workspace must be on the enterprise plan.",),
        publish_targets=("help_center", "copilot"),
    )

    supported = EvalCase(
        case_id="region-feature-availability-01-eu-supported",
        family="region_feature_availability",
        title="EU enterprise feature availability is answerable",
        query="EU enterprise analytics audit log export availability",
        audience_context=AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="analytics",
            plan="enterprise",
            region="eu",
            language="en",
        ),
        objects=(eu_rollout_answer,),
        evidence=(eu_rollout_evidence,),
        expectation=EvalExpectation(
            disposition="answerable",
            object_refs=(eu_rollout_answer.object_id,),
            evidence_refs=(eu_rollout_evidence.evidence_id,),
            trace_refs=(f"trace:{eu_rollout_answer.object_id}",),
            freshness=FreshnessState.FRESH,
        ),
    )
    restricted = EvalCase(
        case_id="region-feature-availability-02-apac-restricted",
        family="region_feature_availability",
        title="EU rollout content is hidden from an APAC audience",
        query="enterprise analytics audit log export availability",
        audience_context=AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="analytics",
            plan="enterprise",
            region="apac",
            language="en",
        ),
        objects=(eu_rollout_answer,),
        evidence=(eu_rollout_evidence,),
        expectation=EvalExpectation(
            disposition="restricted",
            forbidden_object_refs=(eu_rollout_answer.object_id,),
        ),
    )
    return (supported, restricted)


def _freshness_conflict_cases() -> tuple[EvalCase, ...]:
    api_external = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("api",),
        plans=("developer",),
        languages=("en",),
    )
    current_evidence = SupportEvidence(
        evidence_id="ev-webhook-retry-current",
        source_type=EvidenceSourceType.RELEASE_NOTE,
        source_ref="release-notes/api/webhook-retries-2026",
        title="Current webhook retry guidance for 2026",
        content=(
            "The current webhook delivery policy retries five times with "
            "exponential backoff."
        ),
        audience_filter=api_external,
        product_lines=("api",),
        plans=("developer",),
        languages=("en",),
        tags=("webhook", "retry", "current"),
        freshness_state=FreshnessState.FRESH,
        updated_at="2026-08-06T10:00:00Z",
    )
    legacy_evidence = SupportEvidence(
        evidence_id="ev-webhook-retry-legacy",
        source_type=EvidenceSourceType.HELP_CENTER,
        source_ref="help-center/api/webhook-retries-legacy",
        title="Legacy webhook backoff article",
        content="The retired webhook policy described three retry attempts.",
        audience_filter=api_external,
        product_lines=("api",),
        plans=("developer",),
        languages=("en",),
        tags=("webhook", "legacy"),
        freshness_state=FreshnessState.STALE,
        updated_at="2025-11-20T12:00:00Z",
    )
    current_answer = AnswerCard(
        object_id="ko-webhook-retry-current",
        title="Current webhook retry guidance 2026",
        summary="Current 2026 guidance for webhook delivery retries.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(api_external,),
        evidence_ids=(current_evidence.evidence_id,),
        tags=("webhook", "retry", "current", "2026"),
        question="What is the current webhook retry guidance for 2026?",
        canonical_answer="Webhook delivery retries five times with exponential backoff.",
        publish_targets=("help_center", "copilot"),
    )
    legacy_answer = AnswerCard(
        object_id="ko-webhook-retry-legacy",
        title="Legacy webhook backoff article",
        summary="Retired webhook retry guidance retained for conflict detection.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(api_external,),
        evidence_ids=(legacy_evidence.evidence_id,),
        tags=("webhook", "legacy"),
        question="What did the legacy webhook policy say?",
        canonical_answer="The retired policy described three retry attempts.",
        publish_targets=("help_center",),
    )

    stale_status_evidence = SupportEvidence(
        evidence_id="ev-status-retention-stale",
        source_type=EvidenceSourceType.HELP_CENTER,
        source_ref="help-center/status/retention-legacy",
        title="Legacy status history retention",
        content="The old article claims status history is retained for 30 days.",
        audience_filter=api_external,
        product_lines=("api",),
        plans=("developer",),
        languages=("en",),
        tags=("status", "retention", "legacy"),
        freshness_state=FreshnessState.STALE,
        updated_at="2025-06-01T00:00:00Z",
    )
    stale_status_answer = AnswerCard(
        object_id="ko-status-retention-stale",
        title="Legacy API status history retention",
        summary="Outdated retention guidance that requires a human freshness check.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(api_external,),
        evidence_ids=(stale_status_evidence.evidence_id,),
        tags=("status", "retention", "legacy"),
        question="How long is API status history retained?",
        canonical_answer="The legacy article states 30 days.",
        publish_targets=("help_center",),
    )

    return (
        EvalCase(
            case_id="freshness-conflict-01-current-guidance",
            family="freshness_conflict",
            title="Fresh retry guidance wins over a stale alternative",
            query="current webhook retry guidance 2026",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="api",
                plan="developer",
                language="en",
            ),
            objects=(current_answer, legacy_answer),
            evidence=(current_evidence, legacy_evidence),
            expectation=EvalExpectation(
                disposition="answerable",
                object_refs=(current_answer.object_id,),
                evidence_refs=(current_evidence.evidence_id,),
                trace_refs=(f"trace:{current_answer.object_id}",),
                freshness=FreshnessState.FRESH,
            ),
        ),
        EvalCase(
            case_id="freshness-conflict-02-stale-only",
            family="freshness_conflict",
            title="Stale-only guidance is restricted",
            query="legacy API status history retention",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="api",
                plan="developer",
                language="en",
            ),
            objects=(stale_status_answer,),
            evidence=(stale_status_evidence,),
            expectation=EvalExpectation(
                disposition="restricted",
                object_refs=(stale_status_answer.object_id,),
                evidence_refs=(stale_status_evidence.evidence_id,),
                trace_refs=(f"trace:{stale_status_answer.object_id}",),
                freshness=FreshnessState.STALE,
                policy=PolicyExpectation(
                    draft_status="approved",
                    page_version=5,
                    expected_version=4,
                    is_admin=True,
                    expected_status="conflict",
                    expected_error="stale_version",
                ),
            ),
        ),
    )


def _ticket_cluster_draft_cases() -> tuple[EvalCase, ...]:
    support_internal = AudienceFilter(
        visibility=Visibility.INTERNAL,
        product_lines=("support-platform",),
        languages=("en",),
    )
    ticket_cluster_evidence = SupportEvidence(
        evidence_id="ev-ticket-cluster-sso-loop",
        source_type=EvidenceSourceType.RESOLVED_TICKET,
        source_ref="ticket-cluster/sso-loop/2026-w31",
        title="SSO login-loop resolved-ticket cluster",
        content=(
            "A cluster of resolved tickets suggests clearing the stale identity "
            "handoff cookie before retrying SSO."
        ),
        audience_filter=support_internal,
        product_lines=("support-platform",),
        languages=("en",),
        tags=("ticket-cluster", "sso", "draft"),
        freshness_state=FreshnessState.UNKNOWN,
        updated_at="2026-08-05T16:20:00Z",
    )
    unpublished_flow = TroubleshootingFlow(
        object_id="ko-draft-sso-login-loop",
        title="Draft SSO login-loop troubleshooting",
        summary="An unpublished troubleshooting draft derived from resolved tickets.",
        lifecycle_state=LifecycleState.IN_REVIEW,
        supported_audiences=(support_internal,),
        evidence_ids=(ticket_cluster_evidence.evidence_id,),
        tags=("ticket-cluster", "sso", "troubleshooting"),
        problem_statement="A user returns to the sign-in page after successful SSO.",
        prerequisites=("Confirm the identity provider reports a successful login.",),
        steps=(
            "Inspect the identity handoff cookie age.",
            "Clear only the stale handoff cookie.",
            "Retry SSO once.",
        ),
        stop_conditions=("The user reaches the workspace.",),
        escalation_route_id="route-identity-platform",
    )

    source_blind_flow = TroubleshootingFlow(
        object_id="ko-published-login-loop-source-blind",
        title="Published login-loop cluster troubleshooting",
        summary="A published flow whose ticket-cluster evidence is unavailable.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(support_internal,),
        evidence_ids=("ev-ticket-cluster-login-loop-missing",),
        tags=("ticket-cluster", "login-loop", "troubleshooting"),
        problem_statement="A support agent sees a repeated login redirect loop.",
        prerequisites=("Capture the request correlation identifier.",),
        steps=("Do not apply an ungrounded workaround; escalate with the trace.",),
        stop_conditions=("Identity Platform accepts the escalation.",),
        escalation_route_id="route-identity-platform",
    )

    return (
        EvalCase(
            case_id="ticket-cluster-draft-01-unpublished",
            family="ticket_cluster_draft",
            title="Unpublished ticket-cluster draft stays pending review",
            query="SSO login loop troubleshooting stale handoff cookie",
            audience_context=AudienceContext(
                visibility=Visibility.INTERNAL,
                product_line="support-platform",
                language="en",
            ),
            objects=(unpublished_flow,),
            evidence=(ticket_cluster_evidence,),
            expectation=EvalExpectation(
                disposition="restricted",
                forbidden_object_refs=(unpublished_flow.object_id,),
            ),
        ),
        EvalCase(
            case_id="ticket-cluster-draft-02-source-blind",
            family="ticket_cluster_draft",
            title="Missing cluster evidence forces escalation",
            query="published login loop cluster troubleshooting",
            audience_context=AudienceContext(
                visibility=Visibility.INTERNAL,
                product_line="support-platform",
                language="en",
            ),
            objects=(source_blind_flow,),
            evidence=(),
            expectation=EvalExpectation(
                disposition="escalate",
                object_refs=(source_blind_flow.object_id,),
                trace_refs=(f"trace:{source_blind_flow.object_id}",),
                freshness=FreshnessState.UNKNOWN,
            ),
        ),
    )


def production_eval_cases() -> tuple[EvalCase, ...]:
    """Return the deterministic production-shaped CYG-117 evaluation corpus."""

    cases = (
        *_plan_tier_refund_cases(),
        *_product_version_known_issue_cases(),
        *_region_feature_availability_cases(),
        *_freshness_conflict_cases(),
        *_ticket_cluster_draft_cases(),
    )
    return tuple(sorted(cases, key=lambda case: case.case_id))
