from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from cygnus.runtime.main import app
from cygnus.runtime.database import get_db
from cygnus.runtime.services.auth_service import get_current_user, require_admin
from cygnus.publish import clear_publish_projections
from cygnus.retrieval import (
    SubstrateKnowledgeSnapshot,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.review import (
    compile_pressure_proposal_bundles,
    sample_pressure_intake_records,
)
from cygnus.review.source_blindness import SourceFailureObservation, SourceImpactState
from cygnus.runtime.routers.governance.dependencies import (
    GovernanceReadSnapshot,
    get_durable_publish_projection,
    get_governance_read_snapshot,
    get_governance_knowledge_snapshot,
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
        app.dependency_overrides[get_governance_knowledge_snapshot] = lambda: (
            self.snapshot.knowledge
        )
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
        app.dependency_overrides.pop(get_governance_knowledge_snapshot)
        protected_paths = (
            "/api/command-center",
            "/api/drift",
            "/api/source-blindness",
            "/api/review-intake",
            "/api/governance-signals",
            "/api/publish-preview",
            "/api/publish-propagation",
            "/api/recovery-proof",
            "/api/recovery/overview",
            "/api/knowledge-graph",
            "/api/traceability/ko-eu-invoice-delay",
            "/api/session-bridge/capabilities",
        )
        for path in protected_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
        query_response = self.client.post(
            "/api/session-bridge/query",
            json={
                "request_ref": "unauthenticated-query",
                "query": "cancel subscription",
                "audience_context": {
                    "visibility": "external",
                    "product_line": "billing",
                    "plan_tier": "free",
                },
            },
        )
        self.assertEqual(query_response.status_code, 401)

    def test_session_bridge_query_is_mounted_on_main_app(self) -> None:
        self.enable_auth()
        response = self.client.post(
            "/api/session-bridge/query",
            json={
                "request_ref": "main-app-query",
                "session_ref": "main-app-session",
                "query": "cancel subscription",
                "audience_context": {
                    "visibility": "external",
                    "product_line": "billing",
                    "plan_tier": "free",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["governance"]["state"], "answerable")
        self.assertEqual(payload["data"]["session_ref"], "main-app-session")

    def test_command_center_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/command-center").json()
        self.assertIn("situation_frame", payload)
        self.assertIn("priority_stack", payload)
        self.assertIn("available_commands", payload)
        self.assertEqual(payload["priority_stack"], [])
        self.assertEqual(payload["situation_frame"]["urgent_items"], 0)
        self.assertEqual(payload["observation"]["state"], "ready")
        self.assertEqual(
            payload["observation"]["reason"],
            "persisted_governance_signal_provider_ready",
        )
        self.assertIn("ticket_cluster", payload["observation"]["covered_signals"])
        self.assertIn("low_rating", payload["observation"]["covered_signals"])
        self.assertIn("stale_answer", payload["observation"]["covered_signals"])

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
        self.assertEqual(payload["observation"]["state"], "ready")
        self.assertEqual(
            payload["observation"]["reason"], "persisted_drift_provider_ready"
        )
        self.assertEqual(
            payload["observation"]["covered_signals"],
            [
                "release_delta",
                "incident_delta",
            ],
        )
        self.assertEqual(payload["observation"]["missing_signals"], [])

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
                    impact_state=SourceImpactState.MAPPED,
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
        self.assertEqual(source_payload["observation"]["state"], "ready")
        self.assertEqual(source_payload["observation"]["missing_signals"], [])
        self.assertEqual(
            source_payload["source_observations"][0]["source_id"], "source-failed"
        )
        self.assertEqual(
            source_payload["source_observations"][0]["impact_state"], "mapped"
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
        self.snapshot = GovernanceReadSnapshot(
            knowledge=self.snapshot.knowledge,
            source_observations=(),
            visible_source_count=0,
            review_bundles=compile_pressure_proposal_bundles(
                (sample_pressure_intake_records()[1],)
            ),
        )
        self.enable_auth()
        payload = self.client.get(
            "/api/review-queue/refund-enterprise-rewrite",
        ).json()
        self.assertEqual(payload["surface_id"], "review-queue-drilldown")
        self.assertEqual(
            payload["selected_card"]["object_ref"], "refund-enterprise-rewrite"
        )
        self.assertIn("queue_surface", payload)

    def test_publish_preview_requires_persisted_intake(self) -> None:
        self.enable_auth()
        app.dependency_overrides[get_db] = lambda: object()
        with patch(
            "cygnus.runtime.routers.governance.publish.list_governance_signals",
            AsyncMock(return_value=[]),
        ):
            response = self.client.get("/api/publish-preview")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "no persisted publish intake records are available in this scope",
        )

    def test_publish_propagation_requires_durable_selector(self) -> None:
        self.enable_auth()
        response = self.client.get("/api/publish-propagation")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "publication_id or object_ref is required for durable propagation",
        )

    def test_recovery_proof_returns_durable_selection(self) -> None:
        self.enable_auth()
        app.dependency_overrides[get_db] = lambda: object()
        durable_payload = {
            "surface_id": "recovery-proof",
            "persisted": True,
            "rehearsal": False,
            "command_id": "durable-command-1",
            "object_ref": "billing-verification-w25",
            "recovery_window": {"surface_id": "recovery-window"},
        }
        with patch(
            "cygnus.runtime.routers.governance.recovery.get_durable_recovery_proof",
            AsyncMock(return_value=durable_payload),
        ):
            response = self.client.get(
                "/api/recovery-proof",
                params={"object_ref": "billing-verification-w25"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), durable_payload)

    def test_downstream_reality_check_uses_durable_provider(self) -> None:
        self.enable_auth()
        app.dependency_overrides[get_db] = lambda: object()
        durable_surface = types.SimpleNamespace(
            to_dict=lambda: {
                "surface_id": "downstream-reality-check",
                "reality_check_strip": {"command_id": "durable-command-1"},
                "feedback_feed": [{"signal_id": "feedback-1"}],
                "mismatch_by_audience": [],
            }
        )
        with patch(
            "cygnus.runtime.routers.governance.recovery.get_durable_downstream_reality_check",
            AsyncMock(return_value=durable_surface),
        ):
            response = self.client.get(
                "/api/recovery/downstream-reality-check/durable-command-1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["persisted"])
        self.assertFalse(response.json()["rehearsal"])
        self.assertEqual(response.json()["feedback_feed"][0]["signal_id"], "feedback-1")

    def test_recovery_window_uses_durable_provider_and_alias(self) -> None:
        self.enable_auth()
        app.dependency_overrides[get_db] = lambda: object()
        durable_surface = types.SimpleNamespace(
            to_dict=lambda: {
                "surface_id": "recovery-window",
                "before_after_alignment_view": {},
                "rewrite_delta": {"before_value": 2, "after_value": 1},
                "closure_judge": {"closeable": False},
            }
        )
        with patch(
            "cygnus.runtime.routers.governance.recovery.get_durable_recovery_window",
            AsyncMock(return_value=durable_surface),
        ):
            window_response = self.client.get("/api/recovery/window/durable-command-1")
            canonical_response = self.client.get("/api/recovery/durable-command-1")

        self.assertEqual(window_response.status_code, 200)
        self.assertEqual(canonical_response.status_code, 200)
        self.assertTrue(window_response.json()["persisted"])
        self.assertFalse(window_response.json()["rehearsal"])
        self.assertEqual(
            canonical_response.json()["rewrite_delta"],
            {"before_value": 2, "after_value": 1},
        )

    def test_governance_overview_uses_durable_provider(self) -> None:
        self.enable_auth()
        app.dependency_overrides[get_db] = lambda: object()
        durable_surface = types.SimpleNamespace(
            to_dict=lambda: {
                "surface_id": "governance-overview",
                "open_loops": [{"command_id": "durable-command-1"}],
                "open_loop_ranks": [],
                "highest_leverage_command": "durable-command-1",
            }
        )
        with patch(
            "cygnus.runtime.routers.governance.recovery.get_durable_governance_overview",
            AsyncMock(return_value=durable_surface),
        ):
            response = self.client.get("/api/recovery/overview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "governance-overview")
        self.assertEqual(payload["highest_leverage_command"], "durable-command-1")
        self.assertTrue(payload["persisted"])
        self.assertFalse(payload["rehearsal"])

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
