from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from cygnus.runtime.main import app
from cygnus.runtime.services.auth_service import get_current_user, require_admin
from cygnus.publish import clear_publish_projections


class CommandCenterApiTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_publish_projections()
        self.fake_user = types.SimpleNamespace(id="test-admin", role="admin")
        self.patches = [
            patch("cygnus.runtime.main.seed_default_admin", AsyncMock(return_value=None)),
            patch(
                "cygnus.runtime.services.storage_service.storage_service.ensure_bucket",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.scripts.seed_skills.seed_builtin_skills",
                AsyncMock(return_value=None),
            ),
        ]
        for patcher in self.patches:
            patcher.start()
        self.client = TestClient(app)

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
        self.assertEqual(len(payload["priority_stack"]), 4)
        self.assertEqual(payload["situation_frame"]["urgent_items"], 1)

    def test_review_intake_payload_shape(self) -> None:
        self.enable_auth()
        payload = self.client.get("/api/review-intake").json()
        self.assertIn("review_home", payload)
        self.assertIn("pressure_surface", payload)
        self.assertIn("source_blindness_surface", payload)
        self.assertEqual(payload["review_home"]["surface_id"], "review-home")
        self.assertEqual(payload["pressure_surface"]["surface_id"], "review-pressure")
        self.assertEqual(payload["source_blindness_surface"]["surface_id"], "source-health")

    def test_review_queue_item_returns_intake_drilldown_surface(self) -> None:
        self.enable_auth()
        payload = self.client.get(
            "/api/review-queue/refund-enterprise-rewrite",
        ).json()
        self.assertEqual(payload["surface_id"], "review-queue-drilldown")
        self.assertEqual(payload["selected_card"]["object_ref"], "refund-enterprise-rewrite")
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
            params={"object_ref": "refund-enterprise-rewrite", "action_key": "hold_external"},
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
        self.assertEqual(payload["selected_card"]["object_ref"], "billing-verification-w25")
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
            json={"object_ref": "refund-enterprise-rewrite", "action_key": "hold_external"},
        )
        self.assertEqual(unauth.status_code, 401)

    def test_publish_apply_runs_executor_and_returns_full_result(self) -> None:
        self.enable_auth()
        payload = self.client.post(
            "/api/publish/apply",
            json={"object_ref": "refund-enterprise-rewrite", "action_key": "hold_external"},
        ).json()
        self.assertTrue(payload["action_log"])
        self.assertTrue(any("hold_external" in entry for entry in payload["action_log"]))
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
            json={"object_ref": "refund-enterprise-rewrite", "action_key": "not-a-real-command"},
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

    def test_traceability_rejects_unknown_object(self) -> None:
        self.enable_auth()
        response = self.client.get(
            "/api/traceability/does-not-exist",
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
