from __future__ import annotations

import unittest
from typing import cast

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
    ReviewRiskType,
)


class ReviewIntakeTests(unittest.TestCase):
    def test_ticket_cluster_compiles_into_support_domain_troubleshooting_proposal(
        self,
    ) -> None:
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
        self.assertIn("internal", cast(list[str], payload["audience_notes"])[0])

    def test_compiled_ticket_and_rewrite_records_feed_pressure_surface_without_manual_reentry(
        self,
    ) -> None:
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

        surface = build_review_pressure_surface(
            compile_pressure_proposal_bundles(records)
        ).to_dict()
        pressure_lines = cast(list[dict[str, object]], surface["pressure_lines"])
        refs = {cast(str, line["proposal_ref"]): line for line in pressure_lines}

        self.assertIn("billing-verification-w25", refs)
        self.assertIn("refund-enterprise-rewrite", refs)
        self.assertEqual(
            refs["billing-verification-w25"]["suggested_object_type"],
            "troubleshooting_flow",
        )
        self.assertEqual(
            refs["refund-enterprise-rewrite"]["suggested_object_type"], "policy_rule"
        )
        self.assertEqual(
            refs["billing-verification-w25"]["evidence_sufficiency"], "sufficient"
        )
        self.assertIn(
            "internal surfaces",
            cast(str, refs["billing-verification-w25"]["visibility_consequence"]),
        )
        self.assertIn(
            "external audience",
            cast(str, refs["refund-enterprise-rewrite"]["visibility_consequence"]),
        )
        self.assertIn(
            "route_to_review",
            cast(list[str], refs["billing-verification-w25"]["command_actions"]),
        )
        self.assertIn(
            "macro",
            cast(list[str], refs["refund-enterprise-rewrite"]["affected_surfaces"]),
        )

    def test_ticket_pressure_does_not_require_fixture_trigger_labels(self) -> None:
        record = PressureIntakeRecord(
            signal_type=PressureSignalType.TICKET_CLUSTER,
            signal_ref="persisted-refund-cluster",
            title="Persisted refund pressure",
            summary="Repeated refund questions crossed the governance threshold.",
            source_ref="source:persisted-refund-cluster",
            source_type=EvidenceSourceType.RESOLVED_TICKET,
            audience_filter=AudienceFilter(visibility=Visibility.INTERNAL),
            object_type=KnowledgeObjectType.ANSWER_CARD,
            affected_surfaces=("agent-copilot",),
            trigger_signals=("refund-escalation",),
            evidence_excerpt="Reviewers confirmed repeated refund questions.",
        )

        surface = build_review_pressure_surface(
            compile_pressure_proposal_bundles((record,))
        ).to_dict()
        pressure_lines = cast(list[dict[str, object]], surface["pressure_lines"])
        self.assertEqual(
            pressure_lines[0]["proposal_ref"],
            "persisted-refund-cluster",
        )

    def test_consumption_feedback_compiles_conservatively_for_review(self) -> None:
        cases = (
            (
                PressureSignalType.LOW_RATING,
                FreshnessState.UNKNOWN,
                ReviewRiskType.TICKET_PRESSURE,
                "medium",
                "low answer rating",
                ("urgent", "hot"),
            ),
            (
                PressureSignalType.STALE_ANSWER,
                FreshnessState.STALE,
                ReviewRiskType.DRIFT,
                "high",
                "may be out of date",
                ("stale_answer",),
            ),
        )

        for (
            signal_type,
            freshness_state,
            risk_type,
            urgency,
            why_now_phrase,
            trigger_signals,
        ) in cases:
            with self.subTest(signal_type=signal_type.value):
                bundle = compile_pressure_intake(
                    PressureIntakeRecord(
                        signal_type=signal_type,
                        signal_ref=f"feedback-route:{signal_type.value}",
                        title=f"{signal_type.value} feedback requires review",
                        summary="Consumer feedback requires governed review.",
                        source_ref=f"feedback-route:{signal_type.value}",
                        source_type=EvidenceSourceType.CONSUMPTION_FEEDBACK,
                        audience_filter=AudienceFilter(
                            visibility=Visibility.EXTERNAL,
                            product_lines=("billing",),
                        ),
                        object_type=KnowledgeObjectType.ANSWER_CARD,
                        affected_surfaces=("feedback", "review_queue"),
                        trigger_signals=trigger_signals,
                        freshness_state=freshness_state,
                        queue_owner="support-ops",
                        evidence_excerpt="A concrete feedback observation was recorded.",
                    )
                )

                self.assertEqual(bundle.signal.risk_type, risk_type)
                self.assertEqual(bundle.proposal.urgency.value, urgency)
                self.assertEqual(
                    bundle.proposal.evidence_sufficiency.value,
                    "partial",
                )
                self.assertEqual(
                    bundle.signal.recommended_actions,
                    ("open_review", "assign_owner"),
                )
                self.assertEqual(
                    bundle.evidence[0].source_type,
                    EvidenceSourceType.CONSUMPTION_FEEDBACK,
                )
                self.assertEqual(
                    bundle.evidence[0].freshness_state,
                    freshness_state,
                )
                self.assertIn(
                    why_now_phrase,
                    bundle.proposal.why_now.lower(),
                )
                self.assertNotIn(
                    "restrict_publish",
                    bundle.signal.recommended_actions,
                )

        stale_bundle = compile_pressure_intake(
            PressureIntakeRecord(
                signal_type=PressureSignalType.STALE_ANSWER,
                signal_ref="feedback-route:stale-unknown-freshness",
                title="Stale answer feedback requires review",
                summary="Consumer feedback requires governed review.",
                source_ref="feedback-route:stale-unknown-freshness",
                source_type=EvidenceSourceType.CONSUMPTION_FEEDBACK,
                audience_filter=AudienceFilter(visibility=Visibility.EXTERNAL),
                object_type=KnowledgeObjectType.ANSWER_CARD,
                affected_surfaces=("feedback", "review_queue"),
                freshness_state=FreshnessState.UNKNOWN,
            )
        )
        self.assertEqual(
            stale_bundle.evidence[0].freshness_state,
            FreshnessState.UNKNOWN,
        )
        self.assertNotIn("release", stale_bundle.proposal.why_now.lower())
        self.assertNotIn("incident", stale_bundle.proposal.why_now.lower())

    def test_source_failure_compiles_into_source_blindness_governance_context(
        self,
    ) -> None:
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

        surface = build_source_blindness_surface(
            compile_pressure_proposal_bundles((record,))
        ).to_dict()
        context = cast(list[dict[str, object]], surface["contexts"])[0]

        self.assertEqual(context["proposal_ref"], "incident-sync-eu-billing")
        self.assertEqual(context["risk_type"], "source_blindness")
        self.assertEqual(context["suggested_object_type"], "known_issue_page")
        self.assertIn(
            "incident/sev2-eu-billing", cast(list[str], context["source_refs"])
        )
        self.assertIn(
            "external", cast(list[str], context["affected_audience_labels"])[0]
        )
        self.assertIn("help_center", cast(list[str], context["affected_surfaces"]))

    def test_build_pressure_intake_surfaces_returns_review_home_and_specialized_surfaces(
        self,
    ) -> None:
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

        review_home = cast(dict[str, object], surfaces["review_home"])
        self.assertEqual(review_home["surface_id"], "review-home")
        priority_stack = cast(list[dict[str, object]], review_home["priority_stack"])
        self.assertEqual(len(priority_stack), 2)
        self.assertIsNotNone(surfaces["pressure_surface"])
        self.assertIsNotNone(surfaces["source_blindness_surface"])
        pressure_surface = cast(dict[str, object], surfaces["pressure_surface"])
        pressure_lines = cast(
            list[dict[str, object]], pressure_surface["pressure_lines"]
        )
        self.assertEqual(
            pressure_lines[0]["proposal_ref"],
            "billing-verification-w25",
        )
        source_blindness_surface = cast(
            dict[str, object], surfaces["source_blindness_surface"]
        )
        contexts = cast(list[dict[str, object]], source_blindness_surface["contexts"])
        self.assertEqual(
            contexts[0]["proposal_ref"],
            "incident-sync-eu-billing",
        )

    def test_pressure_intake_review_brief_surface_is_ranked_from_compiled_intake(
        self,
    ) -> None:
        payload = get_pressure_intake_review_brief_surface().to_dict()

        self.assertEqual(payload["surface_id"], "review-home")
        # 3 ticket_pressure signals: two create-proposals + one governance
        # signal on the EXISTING published object ko-billing-refund-policy.
        command_brief = cast(dict[str, object], payload["command_brief"])
        summary_counts = cast(dict[str, int], command_brief["summary_counts"])
        self.assertEqual(summary_counts["ticket_pressure"], 3)
        priority_stack = cast(list[dict[str, object]], payload["priority_stack"])
        self.assertEqual(priority_stack[0]["risk_type"], "source_blindness")
        self.assertEqual(priority_stack[0]["object_ref"], "incident-sync-eu-billing")
        self.assertIn(
            "assign_owner", cast(list[str], priority_stack[1]["command_actions"])
        )
        # The publish write-path keys on object_ref; an existing ko-* object in
        # the queue bridges APPLY to traceability (same id resolves on both sides).
        existing_refs = {cast(str, card["object_ref"]) for card in priority_stack}
        self.assertIn("ko-billing-refund-policy", existing_refs)

    def test_existing_published_object_is_compiled_as_update_not_create(self) -> None:
        record = PressureIntakeRecord(
            signal_type=PressureSignalType.HUMAN_REWRITE,
            signal_ref="refund-policy-rewrite",
            proposal_id="ko-billing-refund-policy",
            title="Refund policy rewrite pressure should stay on the existing governed object",
            summary="Existing refund policy must be revised without pretending it is net-new.",
            source_ref="rewrite/refund-policy-rewrite",
            source_type=EvidenceSourceType.CHAT_TRANSCRIPT,
            audience_filter=AudienceFilter(
                visibility=Visibility.INTERNAL,
                product_lines=("billing",),
            ),
            object_type=KnowledgeObjectType.POLICY_RULE,
            affected_surfaces=("copilot", "macro"),
        )

        payload = (
            compile_pressure_intake(record).as_proposal_bundle().proposal.to_dict()
        )

        self.assertEqual(payload["proposal_id"], "ko-billing-refund-policy")
        self.assertEqual(payload["action"], "update")


if __name__ == "__main__":
    unittest.main()
