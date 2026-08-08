from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from cygnus.runtime.main import app
from cygnus.runtime.services.auth_service import get_current_user, require_admin
from cygnus.publish import clear_publish_projections
from cygnus.retrieval import (
    SubstrateKnowledgeSnapshot,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.review.source_blindness import SourceFailureObservation
from cygnus.runtime.routers.governance.dependencies import (
    GovernanceReadSnapshot,
    get_durable_publish_projection,
    get_governance_read_snapshot,
)


class CommandCenterApiTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_publish_projections()
        self.fake_user = types.SimpleNamespace(id="test-admin", role="admin")
        self.patches = [
            patch(
                "cygnus.runtime.main.seed_default_admin", AsyncMock(return_value=None)
            ),
            patch(
                "cygnus.runtime.services.storage_service.storage_service.ensure_bucket",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.bootstrap.seed_builtin_skills.seed_builtin_skills",
                AsyncMock(return_value=None),
            ),
        ]
        for patcher in self.patches:
            patcher.start()
        self.client = TestClient(app)
        self.snapshot = GovernanceReadSnapshot(
            knowledge=SubstrateKnowledgeSnapshot(
                objects=sample_knowledge_objects(),
                evidence=sample_support_evidence(),
            ),
            source_observations=(),
            visible_source_count=0,
        )
        app.dependency_overrides[get_governance_read_snapshot] = lambda: self.snapshot
        app.dependency_overrides[get_durable_publish_projection] = lambda: None

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        for patcher in reversed(self.patches):
            patcher.stop()
        clear_publish_projections()

    def enable_auth(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: self.fake_user
        app.dependency_overrides[require_admin] = lambda: self.fake_user

    def test_healthz_ok(self) -> None:
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})

    def test_governance_reads_require_auth(self) -> None:
        app.dependency_overrides.pop(get_governance_read_snapshot)
        protected_paths = (
            "/api/command-center",
            "/api/drift",
            "/api/source-blindness",
            "/api/review-intake",
            "/api/publish-preview",
            "/api/publish-propagation",
            "/api/recovery-proof",
            "/api/recovery/overview",
            "/api/knowledge-graph",
            "/api/traceability/ko-eu-invoice-delay",
        )
        for path in protected_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)

    def test_command_center_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/command-center").json()
        self.assertIn("situation_frame", payload)
        self.assertIn("priority_stack", payload)
        self.assertIn("available_commands", payload)
        self.assertEqual(payload["priority_stack"], [])
        self.assertEqual(payload["situation_frame"]["urgent_items"], 0)
        self.assertEqual(payload["observation"]["state"], "partial")
        self.assertEqual(
            payload["observation"]["reason"], "review_signal_coverage_partial"
        )
        self.assertIn("ticket_pressure", payload["observation"]["missing_signals"])

    def test_review_intake_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/review-intake").json()
        self.assertIn("review_home", payload)
        self.assertIn("pressure_surface", payload)
        self.assertIn("source_blindness_surface", payload)
        self.assertEqual(payload["review_home"]["surface_id"], "review-home")
        self.assertIsNone(payload["pressure_surface"])
        self.assertEqual(
            payload["source_blindness_surface"]["surface_id"], "source-health"
        )
        self.assertEqual(payload["source_blindness_surface"]["contexts"], [])
        self.assertEqual(payload["source_blindness_surface"]["source_observations"], [])

    def test_drift_payload_marks_unavailable_detectors(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/drift").json()
        self.assertEqual(payload["contexts"], [])
        self.assertEqual(payload["available_commands"], [])
        self.assertEqual(payload["observation"]["state"], "unavailable")
        self.assertEqual(
            payload["observation"]["reason"], "drift_detectors_unavailable"
        )
        self.assertEqual(
            payload["observation"]["missing_signals"],
            ["release_delta", "incident_delta", "ticket_pressure"],
        )

    def test_target_governance_routes_do_not_fall_back_to_sample_fixtures(self) -> None:
        self.enable_auth()
        with (
            patch(
                "cygnus.review.home.sample_review_bundles", side_effect=AssertionError
            ),
            patch(
                "cygnus.review.drift.sample_review_bundles", side_effect=AssertionError
            ),
            patch(
                "cygnus.review.source_blindness.sample_review_bundles",
                side_effect=AssertionError,
            ),
            patch(
                "cygnus.review.intake.sample_pressure_intake_records",
                side_effect=AssertionError,
            ),
        ):
            for path in (
                "/api/command-center",
                "/api/drift",
                "/api/source-blindness",
                "/api/review-intake",
            ):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

    def test_source_failure_remains_fact_without_fabricated_impact_or_command(
        self,
    ) -> None:
        self.snapshot = GovernanceReadSnapshot(
            knowledge=self.snapshot.knowledge,
            source_observations=(
                SourceFailureObservation(
                    source_id="source-failed",
                    title="Incident feed",
                    source_ref="https://status.example/feed",
                    status="error",
                    error_message="upstream timeout",
                    linked_wiki_refs=("wiki-incident",),
                    linked_object_refs=("ko-incident",),
                    observed_at="2026-07-26T10:00:00Z",
                ),
            ),
            visible_source_count=1,
        )
        self.enable_auth()

        source_payload = self.client.get("/api/source-blindness").json()
        self.assertEqual(source_payload["contexts"], [])
        self.assertEqual(source_payload["available_commands"], [])
        self.assertEqual(source_payload["observation"]["state"], "partial")
        self.assertEqual(
            source_payload["observation"]["missing_signals"], ["source_impact"]
        )
        self.assertEqual(
            source_payload["source_observations"][0]["source_id"], "source-failed"
        )
        self.assertEqual(
            source_payload["source_observations"][0]["impact_state"], "unknown"
        )

        intake_payload = self.client.get("/api/review-intake").json()
        self.assertEqual(intake_payload["review_home"]["priority_stack"], [])
        self.assertIsNone(intake_payload["pressure_surface"])
        self.assertEqual(
            intake_payload["source_blindness_surface"]["source_observations"][0][
                "source_id"
            ],
            "source-failed",
        )

    def test_review_queue_item_returns_intake_drilldown_surface(self) -> None:
        self.enable_auth()
        payload = self.client.get(
            "/api/review-queue/refund-enterprise-rewrite",
        ).json()
        self.assertEqual(payload["surface_id"], "review-queue-drilldown")
        self.assertEqual(
            payload["selected_card"]["object_ref"], "refund-enterprise-rewrite"
        )
        self.assertIn("queue_surface", payload)

    def test_publish_preview_returns_blast_radius_surface(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/publish-preview").json()
        self.assertEqual(payload["surface_id"], "publish-preview")
        self.assertIn("selected_preview", payload)
        self.assertIn("situation_frame", payload)

    def test_publish_propagation_returns_supporting_surface_theater(self) -> None:
        self.enable_auth()
        payload = self.client.get(
            "/api/publish-propagation",
            params={
                "object_ref": "refund-enterprise-rewrite",
                "action_key": "hold_external",
            },
        ).json()
        self.assertEqual(payload["surface_id"], "publish-propagation")
        self.assertEqual(payload["selected_action"], "hold_external")
        self.assertIn("propagation_ledger", payload)

    def test_recovery_proof_returns_frontline_reality_check(self) -> None:
        self.enable_auth()
        payload = self.client.get(
            "/api/recovery-proof",
            params={"object_ref": "billing-verification-w25"},
        ).json()
        self.assertEqual(payload["surface_id"], "recovery-proof")
        self.assertEqual(
            payload["selected_card"]["object_ref"], "billing-verification-w25"
        )
        self.assertIn("recovery_window", payload)
        self.assertIn("signals", payload)

    def test_downstream_reality_check_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get(
            "/api/recovery/downstream-reality-check/cmd-publish-1",
        ).json()
        self.assertEqual(payload["surface_id"], "downstream-reality-check")
        self.assertIn("reality_check_strip", payload)
        self.assertIn("feedback_feed", payload)
        self.assertIn("mismatch_by_audience", payload)

    def test_recovery_window_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get(
            "/api/recovery/window/cmd-publish-1",
        ).json()
        self.assertEqual(payload["surface_id"], "recovery-window")
        self.assertIn("before_after_alignment_view", payload)
        self.assertIn("rewrite_delta", payload)
        self.assertIn("closure_judge", payload)

    def test_governance_overview_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/recovery/overview").json()
        self.assertEqual(payload["surface_id"], "governance-overview")
        self.assertIn("open_loops", payload)
        self.assertIn("open_loop_ranks", payload)
        self.assertIn("highest_leverage_command", payload)
        self.assertEqual(len(payload["open_loops"]), 2)
        self.assertEqual(payload["highest_leverage_command"], "cmd-restrict-2")
        self.assertTrue(payload["rehearsal"])

    def test_knowledge_graph_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/knowledge-graph").json()
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertIn("stats", payload)
        self.assertGreater(payload["stats"]["objects"], 0)
        self.assertGreater(payload["stats"]["evidence"], 0)
        self.assertGreater(payload["stats"]["audiences"], 0)
        node_kinds = {node["kind"] for node in payload["nodes"]}
        edge_kinds = {edge["kind"] for edge in payload["edges"]}
        self.assertTrue({"object", "evidence", "audience"}.issubset(node_kinds))
        self.assertTrue({"cites", "serves"}.issubset(edge_kinds))

    def test_publish_apply_requires_admin_auth(self) -> None:
        unauth = self.client.post(
            "/api/publish/apply",
            json={
                "object_ref": "refund-enterprise-rewrite",
                "action_key": "hold_external",
            },
        )
        self.assertEqual(unauth.status_code, 401)

    def test_publish_apply_runs_executor_and_returns_full_result(self) -> None:
        self.enable_auth()
        payload = self.client.post(
            "/api/publish/apply",
            json={
                "object_ref": "refund-enterprise-rewrite",
                "action_key": "hold_external",
            },
        ).json()
        self.assertTrue(payload["action_log"])
        self.assertTrue(
            any("hold_external" in entry for entry in payload["action_log"])
        )
        self.assertIn("opened_bindings", payload)
        self.assertIn("removed_bindings", payload)
        self.assertIn("held_bindings", payload)
        self.assertIn("updated_candidate", payload)
        self.assertEqual(payload["selected_action"], "hold_external")
        self.assertFalse(payload["persisted"])
        self.assertTrue(payload["rehearsal"])
        self.assertTrue(all("reason" in item for item in payload["held_bindings"]))

    def test_publish_apply_rejects_unknown_action_key(self) -> None:
        self.enable_auth()
        response = self.client.post(
            "/api/publish/apply",
            json={
                "object_ref": "refund-enterprise-rewrite",
                "action_key": "not-a-real-command",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_traceability_returns_full_evidence_chain_and_projection(self) -> None:
        self.enable_auth()
        apply_response = self.client.post(
            "/api/publish/apply",
            json={"object_ref": "ko-billing-refund-policy", "action_key": "republish"},
        )
        self.assertEqual(apply_response.status_code, 200)

        payload = self.client.get(
            "/api/traceability/ko-billing-refund-policy",
        ).json()
        self.assertEqual(payload["surface_id"], "traceability-chain")
        self.assertEqual(payload["object"]["object_id"], "ko-billing-refund-policy")
        trace = payload["trace"]
        self.assertIn("evidence_refs", trace)
        self.assertGreater(len(trace["evidence_refs"]), 0)
        ref = trace["evidence_refs"][0]
        self.assertIn("source_type", ref)
        self.assertIn("source_ref", ref)
        self.assertIn("freshness", ref)
        projection = payload["projection"]
        self.assertIsNotNone(projection)
        self.assertEqual(projection["selected_action"], "republish")
        self.assertFalse(projection["persisted"])
        self.assertTrue(projection["rehearsal"])

    def test_traceability_prefers_restart_durable_projection(self) -> None:
        self.enable_auth()
        rehearsal = self.client.post(
            "/api/publish/apply",
            json={
                "object_ref": "ko-billing-refund-policy",
                "action_key": "republish",
            },
        )
        self.assertEqual(rehearsal.status_code, 200)
        clear_publish_projections()

        durable_projection = {
            "selected_action": "publish",
            "persisted": True,
            "rehearsal": False,
            "publication_record_id": "publication-after-restart",
        }
        app.dependency_overrides[get_durable_publish_projection] = lambda: (
            durable_projection
        )

        payload = self.client.get(
            "/api/traceability/ko-billing-refund-policy",
        ).json()
        self.assertEqual(payload["projection"], durable_projection)

    def test_traceability_rejects_unknown_object(self) -> None:
        self.enable_auth()
        response = self.client.get(
            "/api/traceability/does-not-exist",
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
