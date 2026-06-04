from __future__ import annotations

import unittest

from cygnus.domain import (
    AnswerCard,
    AudienceFilter,
    AudienceVariant,
    EscalationRoute,
    KnownIssuePage,
    LifecycleState,
    PolicyRule,
    TroubleshootingFlow,
    Visibility,
)


def _external_audience() -> AudienceFilter:
    return AudienceFilter(visibility=Visibility.EXTERNAL, product_lines=("billing",))


class SupportObjectTests(unittest.TestCase):
    def test_answer_card_uses_support_native_shape(self) -> None:
        variant = AudienceVariant(
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                plans=("enterprise",),
                regions=("eu",),
            ),
            label="enterprise-eu",
            content="Enterprise EU customers can export invoice PDFs from billing settings.",
            caveats=("Feature flag may delay rollout.",),
            evidence_ids=("ev-2",),
        )
        answer = AnswerCard(
            object_id="ac-1",
            title="Invoice export availability",
            summary="Explains where customers can export invoices.",
            question="How do I export an invoice PDF?",
            canonical_answer="Go to Billing > Invoices and select the invoice you need.",
            constraints=("Requires billing admin role.",),
            audience_variants=(variant,),
            publish_targets=("copilot", "help_center"),
            supported_audiences=(_external_audience(),),
            evidence_ids=("ev-1",),
            tags=("billing", "invoice"),
        )

        payload = answer.to_dict()

        self.assertEqual(payload["object_type"], "answer_card")
        self.assertEqual(payload["lifecycle_state"], "draft")
        self.assertNotIn("chunk", payload)
        self.assertIn("audience_variants", payload)

    def test_all_core_support_objects_are_instantiable(self) -> None:
        escalation = EscalationRoute(
            object_id="er-1",
            title="Billing entitlements escalation",
            summary="Escalate entitlement mismatches to the billing ops queue.",
            trigger_conditions=("Customer plan data and UI state disagree.",),
            destination_team="billing-ops",
            required_context=("account_id", "plan_id"),
            supported_audiences=(
                AudienceFilter(visibility=Visibility.INTERNAL, product_lines=("billing",)),
            ),
        )
        flow = TroubleshootingFlow(
            object_id="tf-1",
            title="Invoice export flow",
            summary="Guides an agent through invoice export failures.",
            problem_statement="Customer cannot export an invoice PDF.",
            prerequisites=("Customer is signed in.",),
            steps=("Check billing role.", "Check invoice ownership.", "Retry export."),
            stop_conditions=("PDF export succeeds.",),
            escalation_route_id=escalation.object_id,
            supported_audiences=(_external_audience(),),
        )
        policy = PolicyRule(
            object_id="pr-1",
            title="Refund grace period",
            summary="Defines the billing grace period for self-serve refunds.",
            rule_domain="refund",
            rule_statement="Refunds are allowed within 14 days of first payment.",
            effective_conditions=("Only first subscription payment qualifies.",),
            exceptions=("Enterprise annual contracts require manual approval.",),
            authority_source="billing-policy-v3",
            supported_audiences=(
                AudienceFilter(visibility=Visibility.INTERNAL, product_lines=("billing",)),
            ),
        )
        issue = KnownIssuePage(
            object_id="ki-1",
            title="EU invoice export delay",
            summary="Tracks delayed invoice export jobs in the EU region.",
            issue_summary="Invoice export jobs are delayed for some EU workspaces.",
            workaround="Use manual invoice delivery from support tooling.",
            issue_status="monitoring",
            affected_products=("billing",),
            affected_versions=("2026.06",),
            expected_next_update="2026-06-05",
            supported_audiences=(_external_audience(),),
        )

        self.assertEqual(escalation.object_type.value, "escalation_route")
        self.assertEqual(flow.object_type.value, "troubleshooting_flow")
        self.assertEqual(policy.object_type.value, "policy_rule")
        self.assertEqual(issue.object_type.value, "known_issue_page")

    def test_object_lifecycle_transition_is_enforced(self) -> None:
        answer = AnswerCard(
            object_id="ac-2",
            title="Cancel subscription",
            summary="Explains self-serve subscription cancellation.",
            question="How do I cancel my subscription?",
            canonical_answer="Go to Billing > Plan and select Cancel subscription.",
        )

        answer.transition_to(LifecycleState.IN_REVIEW)
        answer.transition_to(LifecycleState.APPROVED)
        answer.transition_to(LifecycleState.PUBLISHED)

        self.assertEqual(answer.lifecycle_state, LifecycleState.PUBLISHED)

        with self.assertRaises(ValueError):
            answer.transition_to(LifecycleState.DRAFT)

    def test_object_validation_rejects_empty_semantic_content(self) -> None:
        with self.assertRaises(ValueError):
            TroubleshootingFlow(
                object_id="tf-2",
                title="Broken flow",
                summary="This should fail because it has no steps.",
                problem_statement="A failure without remediation.",
                steps=(),
            )


if __name__ == "__main__":
    unittest.main()
