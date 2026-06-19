from __future__ import annotations

import unittest

from cygnus.domain import AudienceFilter, KnowledgeObjectType, Visibility
from cygnus.evidence import EvidenceSourceType, FreshnessState
from cygnus.review import (
    build_pressure_intake_surfaces,
    build_review_pressure_surface,
    build_source_blindness_surface,
    compile_pressure_intake,
    compile_pressure_proposal_bundles,
    get_pressure_intake_review_brief_surface,
    PressureIntakeRecord,
    PressureSignalType,
)


class ReviewIntakeTests(unittest.TestCase):
    def test_ticket_cluster_compiles_into_support_domain_troubleshooting_proposal(self) -> None:
        record = PressureIntakeRecord(
            signal_type=PressureSignalType.TICKET_CLUSTER,
            signal_ref="billing-verification-w25",
            title="Billing verification cluster should become a governed troubleshooting flow",
            summary="Repeated escalations show a reusable support flow is missing.",
            source_ref="cluster/billing-verification-w25",
            source_type=EvidenceSourceType.RESOLVED_TICKET,
            audience_filter=AudienceFilter(
                visibility=Visibility.INTERNAL,
                product_lines=("billing",),
            ),
            object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
            affected_surfaces=("copilot", "queue-sidebar"),
            trigger_signals=("ticket_pressure", "rewrite_cluster"),
            product_lines=("billing",),
            evidence_excerpt="Agents repeatedly reconstruct the same verification steps from memory.",
        )

        bundle = compile_pressure_intake(record)
        payload = bundle.as_proposal_bundle().proposal.to_dict()

        self.assertEqual(payload["object_type"], "troubleshooting_flow")
        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["urgency"], "medium")
        self.assertEqual(payload["evidence_sufficiency"], "sufficient")
        self.assertIn("internal", payload["audience_notes"][0])

    def test_compiled_ticket_and_rewrite_records_feed_pressure_surface_without_manual_reentry(self) -> None:
        records = (
            PressureIntakeRecord(
                signal_type=PressureSignalType.TICKET_CLUSTER,
                signal_ref="billing-verification-w25",
                title="Billing verification cluster should become a governed troubleshooting flow",
                summary="Repeated escalations show a reusable support flow is missing.",
                source_ref="cluster/billing-verification-w25",
                source_type=EvidenceSourceType.RESOLVED_TICKET,
                audience_filter=AudienceFilter(
                    visibility=Visibility.INTERNAL,
                    product_lines=("billing",),
                ),
                object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
                affected_surfaces=("copilot", "queue-sidebar"),
                trigger_signals=("ticket_pressure", "rewrite_cluster"),
                product_lines=("billing",),
                evidence_excerpt="Agents repeatedly reconstruct the same verification steps from memory.",
            ),
            PressureIntakeRecord(
                signal_type=PressureSignalType.HUMAN_REWRITE,
                signal_ref="refund-enterprise-rewrite",
                title="Refund rewrite pressure should become a governed policy correction",
                summary="Frontline rewrites show enterprise exceptions are leaking into the wrong answer path.",
                source_ref="rewrite/refund-enterprise-rewrite",
                source_type=EvidenceSourceType.CHAT_TRANSCRIPT,
                audience_filter=AudienceFilter(
                    visibility=Visibility.EXTERNAL,
                    product_lines=("billing",),
                    plans=("free",),
                    regions=("us",),
                ),
                object_type=KnowledgeObjectType.POLICY_RULE,
                affected_surfaces=("copilot", "macro"),
                trigger_signals=("rewrite_cluster", "audience_boundary_conflict"),
                product_lines=("billing",),
                plans=("free",),
                regions=("us",),
                evidence_excerpt="Agents keep removing enterprise-only refund clauses before sending replies.",
                queue_owner="support-ops",
            ),
        )

        surface = build_review_pressure_surface(compile_pressure_proposal_bundles(records)).to_dict()
        refs = {line["proposal_ref"]: line for line in surface["pressure_lines"]}

        self.assertIn("billing-verification-w25", refs)
        self.assertIn("refund-enterprise-rewrite", refs)
        self.assertEqual(refs["billing-verification-w25"]["suggested_object_type"], "troubleshooting_flow")
        self.assertEqual(refs["refund-enterprise-rewrite"]["suggested_object_type"], "policy_rule")
        self.assertEqual(refs["billing-verification-w25"]["evidence_sufficiency"], "sufficient")
        self.assertIn("internal surfaces", refs["billing-verification-w25"]["visibility_consequence"])
        self.assertIn("external audience", refs["refund-enterprise-rewrite"]["visibility_consequence"])
        self.assertIn("route_to_review", refs["billing-verification-w25"]["command_actions"])
        self.assertIn("macro", refs["refund-enterprise-rewrite"]["affected_surfaces"])

    def test_source_failure_compiles_into_source_blindness_governance_context(self) -> None:
        record = PressureIntakeRecord(
            signal_type=PressureSignalType.SOURCE_FAILURE,
            signal_ref="incident-sync-eu-billing",
            title="Incident source failure should become a known-issue governance blind spot",
            summary="Source loss is weakening confidence in current EU billing workaround guidance.",
            source_ref="incident/sev2-eu-billing",
            source_type=EvidenceSourceType.INCIDENT_UPDATE,
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing",),
                plans=("enterprise",),
                regions=("eu",),
            ),
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            affected_surfaces=("help_center", "copilot"),
            trigger_signals=("source_sync_failed", "active_incident"),
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
            freshness_state=FreshnessState.STALE,
            evidence_excerpt="Incident feed is degraded while the workaround continues to be customer-facing.",
        )

        surface = build_source_blindness_surface(compile_pressure_proposal_bundles((record,))).to_dict()
        context = surface["contexts"][0]

        self.assertEqual(context["proposal_ref"], "incident-sync-eu-billing")
        self.assertEqual(context["risk_type"], "source_blindness")
        self.assertEqual(context["suggested_object_type"], "known_issue_page")
        self.assertIn("incident/sev2-eu-billing", context["source_refs"])
        self.assertIn("external", context["affected_audience_labels"][0])
        self.assertIn("help_center", context["affected_surfaces"])

    def test_build_pressure_intake_surfaces_returns_review_home_and_specialized_surfaces(self) -> None:
        records = (
            PressureIntakeRecord(
                signal_type=PressureSignalType.TICKET_CLUSTER,
                signal_ref="billing-verification-w25",
                title="Billing verification cluster should become a governed troubleshooting flow",
                summary="Repeated escalations show a reusable support flow is missing.",
                source_ref="cluster/billing-verification-w25",
                source_type=EvidenceSourceType.RESOLVED_TICKET,
                audience_filter=AudienceFilter(
                    visibility=Visibility.INTERNAL,
                    product_lines=("billing",),
                ),
                object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
                affected_surfaces=("copilot", "queue-sidebar"),
                trigger_signals=("ticket_pressure", "rewrite_cluster"),
                product_lines=("billing",),
                evidence_excerpt="Agents repeatedly reconstruct the same verification steps from memory.",
            ),
            PressureIntakeRecord(
                signal_type=PressureSignalType.SOURCE_FAILURE,
                signal_ref="incident-sync-eu-billing",
                title="Incident source failure should become a known-issue governance blind spot",
                summary="Source loss is weakening confidence in current EU billing workaround guidance.",
                source_ref="incident/sev2-eu-billing",
                source_type=EvidenceSourceType.INCIDENT_UPDATE,
                audience_filter=AudienceFilter(
                    visibility=Visibility.EXTERNAL,
                    product_lines=("billing",),
                    plans=("enterprise",),
                    regions=("eu",),
                ),
                object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
                affected_surfaces=("help_center", "copilot"),
                trigger_signals=("source_sync_failed", "active_incident"),
                product_lines=("billing",),
                plans=("enterprise",),
                regions=("eu",),
                freshness_state=FreshnessState.STALE,
                evidence_excerpt="Incident feed is degraded while the workaround continues to be customer-facing.",
            ),
        )

        surfaces = build_pressure_intake_surfaces(records).to_dict()

        self.assertEqual(surfaces["review_home"]["surface_id"], "review-home")
        self.assertEqual(len(surfaces["review_home"]["priority_stack"]), 2)
        self.assertIsNotNone(surfaces["pressure_surface"])
        self.assertIsNotNone(surfaces["source_blindness_surface"])
        self.assertEqual(surfaces["pressure_surface"]["pressure_lines"][0]["proposal_ref"], "billing-verification-w25")
        self.assertEqual(surfaces["source_blindness_surface"]["contexts"][0]["proposal_ref"], "incident-sync-eu-billing")

    def test_pressure_intake_review_brief_surface_is_ranked_from_compiled_intake(self) -> None:
        payload = get_pressure_intake_review_brief_surface().to_dict()

        self.assertEqual(payload["surface_id"], "review-home")
        self.assertEqual(payload["command_brief"]["summary_counts"]["ticket_pressure"], 2)
        self.assertEqual(payload["priority_stack"][0]["risk_type"], "source_blindness")
        self.assertEqual(payload["priority_stack"][0]["object_ref"], "incident-sync-eu-billing")
        self.assertIn("assign_owner", payload["priority_stack"][1]["command_actions"])


if __name__ == "__main__":
    unittest.main()
