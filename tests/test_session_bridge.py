from __future__ import annotations

import unittest
from typing import cast, final

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cygnus.domain import (
    AnswerCard,
    AudienceContext,
    AudienceFilter,
    LifecycleState,
    Visibility,
)
from cygnus.evidence.records import FreshnessState
from cygnus.integrations.governed_session_tools import (
    governed_session_tool_definitions,
)
from cygnus.integrations.session_bridge import (
    GovernanceDisposition,
    GovernedQueryRequest,
    GovernedSessionBridge,
    PriorGovernanceContext,
    delivered_truth_for_objects,
    session_bridge_capabilities,
    session_bridge_openapi_projection,
)
from cygnus.retrieval import (
    SubstrateKnowledgeSnapshot,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.runtime.routers.governance.dependencies import (
    get_governance_knowledge_snapshot,
)
from cygnus.runtime.routers.governance.session_bridge import router


@final
class GovernedSessionBridgeTests(unittest.TestCase):
    snapshot = SubstrateKnowledgeSnapshot(
        objects=sample_knowledge_objects(),
        evidence=sample_support_evidence(),
    )
    bridge = GovernedSessionBridge(snapshot)
    delivery_truth = delivered_truth_for_objects(snapshot.objects)

    def test_query_selects_audience_variant_and_returns_governance_frame(self) -> None:
        payload = self.bridge.query_with_fixture_delivery(
            GovernedQueryRequest(
                request_ref="req-eu-export",
                session_ref="session-1",
                query="invoice export rollout",
                channel="copilot",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="enterprise",
                    region="eu",
                ),
            ),
            delivery_truth=self.delivery_truth,
        )

        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["status"], "denied")
        data = payload["data"]
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("stale_evidence", data["governance"]["codes"])
        self.assertIsNone(data["answer"]["content"])
        self.assertEqual(data["answer"]["usage"], "withheld")
        self.assertFalse(data["answer"]["direct_external_use"])
        self.assertEqual(data["source_trace"]["freshness"], "stale")
        self.assertEqual(
            [entry["name"] for entry in data["tool_trace"]],
            [
                "search_knowledge_objects",
                "read_knowledge_object",
                "get_source_trace",
            ],
        )
        # Tool trace risk is derived from the manifest, never invented.
        self.assertEqual(
            [entry["risk_level"] for entry in data["tool_trace"]],
            ["R0", "R0", "R0"],
        )
        self.assertEqual(data["continuity"]["state"], "started")
        self.assertFalse(data["continuity"]["session_memory_used_as_truth"])

    def test_fresh_published_answer_is_directly_answerable(self) -> None:
        payload = self.bridge.query_with_fixture_delivery(
            GovernedQueryRequest(
                request_ref="req-cancel",
                query="cancel subscription",
                channel="copilot",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="free",
                ),
            ),
            delivery_truth=self.delivery_truth,
        )

        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["governance"]["state"], "answerable")
        self.assertTrue(payload["data"]["answer"]["direct_external_use"])
        self.assertEqual(
            payload["data"]["answer"]["content"]["answer"],
            "Go to Billing > Plan and choose Cancel subscription.",
        )

    def test_unpublished_match_returns_pending_review_instead_of_answer(self) -> None:
        payload = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-verification",
                query="verification troubleshooting flow",
                channel="copilot",
                audience_context=AudienceContext(
                    visibility=Visibility.INTERNAL,
                    product_line="billing",
                ),
            )
        )

        self.assertEqual(payload["status"], "denied")
        self.assertIsNone(payload["data"]["answer"])
        self.assertEqual(payload["data"]["governance"]["state"], "restricted")
        self.assertEqual(payload["data"]["governance"]["codes"], ["pending_review"])

    def test_audience_mismatch_does_not_expose_restricted_object(self) -> None:
        payload = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-wrong-audience",
                query="enterprise invoice export",
                channel="copilot",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="free",
                ),
            )
        )

        self.assertEqual(payload["status"], "denied")
        self.assertIsNone(payload["data"]["answer"])
        self.assertEqual(
            payload["data"]["governance"]["codes"],
            ["audience_restricted"],
        )

    def test_source_blindness_withholds_content_and_requires_escalation(self) -> None:
        audience = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("free",),
        )
        blind_object = AnswerCard(
            object_id="ko-blind-answer",
            title="Blind billing answer",
            summary="An answer without evidence must never look safe.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(audience,),
            question="What is the blind billing answer?",
            canonical_answer="This content must be withheld.",
        )
        bridge = GovernedSessionBridge(
            SubstrateKnowledgeSnapshot(objects=(blind_object,), evidence=())
        )

        payload = bridge.query(
            GovernedQueryRequest(
                request_ref="req-blind",
                query="blind billing answer",
                channel="copilot",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="free",
                ),
            )
        )

        self.assertEqual(payload["data"]["governance"]["state"], "escalate")
        self.assertIn("source_blindness", payload["data"]["governance"]["codes"])
        self.assertIsNone(payload["data"]["answer"]["content"])
        self.assertEqual(payload["data"]["answer"]["usage"], "withheld")

    def test_continuity_revalidates_and_audience_change_invalidates_prior_frame(
        self,
    ) -> None:
        audience = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="free",
        )
        first = self.bridge.query_with_fixture_delivery(
            GovernedQueryRequest(
                request_ref="req-first",
                query="cancel subscription",
                channel="copilot",
                audience_context=audience,
            ),
            delivery_truth=self.delivery_truth,
        )
        context = first["data"]["governance_context"]
        previous = PriorGovernanceContext(
            governance_state=GovernanceDisposition(context["governance_state"]),
            audience_context=audience,
            object_id=context["object_id"],
            object_version=context["object_version"],
            trace_ref=context["trace_ref"],
            freshness=FreshnessState(context["freshness"]),
        )

        same = self.bridge.query_with_fixture_delivery(
            GovernedQueryRequest(
                request_ref="req-same",
                query="cancel subscription",
                channel="copilot",
                audience_context=audience,
                previous_governance_context=previous,
            ),
            delivery_truth=self.delivery_truth,
        )
        changed = self.bridge.query_with_fixture_delivery(
            GovernedQueryRequest(
                request_ref="req-changed",
                query="cancel subscription",
                channel="copilot",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="free",
                    region="eu",
                ),
                previous_governance_context=previous,
            ),
            delivery_truth=self.delivery_truth,
        )

        self.assertEqual(same["data"]["continuity"]["state"], "revalidated")
        self.assertEqual(
            same["data"]["continuity"]["reasons"],
            ["governed_truth_rechecked"],
        )
        self.assertEqual(changed["data"]["continuity"]["state"], "invalidated")
        self.assertEqual(
            changed["data"]["continuity"]["reasons"],
            ["audience_context_changed"],
        )

    def test_capabilities_are_truthful_about_ready_and_unexposed_tools(self) -> None:
        from cygnus.substrate.agent_protocol import (
            SessionActorScope,
            build_session_manifest,
        )

        actor = SessionActorScope(authenticated=True, is_admin=True)
        payload = session_bridge_capabilities(self.snapshot, actor=actor)
        governed_tools = cast(list[dict[str, object]], payload["governed_tools"])
        visible_tools = cast(list[dict[str, object]], payload["visible_tools"])
        denied_tools = cast(list[dict[str, object]], payload["denied_tools"])
        not_exposed = cast(list[dict[str, object]], payload["not_exposed"])
        query_handoff = cast(dict[str, object], payload["query_handoff"])
        manifest = build_session_manifest(governed_session_tool_definitions())

        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["schema_fingerprint"], manifest.schema_fingerprint)
        self.assertEqual(len(governed_tools), 12)
        self.assertEqual(
            {tool["name"] for tool in governed_tools},
            {
                "search_knowledge_objects",
                "read_knowledge_object",
                "search_support_evidence",
                "get_source_trace",
                "list_drift_alerts",
                "propose_knowledge_object",
                "update_draft_object",
                "request_review",
                "read_review_feedback",
                "validate_publish_policy",
                "publish_knowledge_object",
                "record_feedback_signal",
            },
        )
        # Admin sees every governed tool as available; nothing is denied.
        self.assertEqual(len(visible_tools), 12)
        self.assertEqual(denied_tools, [])
        # A viewer without wiki write permission sees only authenticated tools.
        viewer = SessionActorScope(
            authenticated=True, permissions=frozenset({"wiki:read:own_dept"})
        )
        viewer_payload = session_bridge_capabilities(self.snapshot, actor=viewer)
        viewer_visible_tools = cast(
            list[dict[str, object]], viewer_payload["visible_tools"]
        )
        viewer_denied_tools = cast(
            list[dict[str, object]], viewer_payload["denied_tools"]
        )
        self.assertEqual(len(viewer_visible_tools), 8)
        self.assertEqual(len(viewer_denied_tools), 4)
        self.assertEqual(not_exposed, [])
        self.assertFalse(query_handoff["session_memory_is_truth"])
        self.assertTrue(query_handoff["channel_required"])
        self.assertTrue(query_handoff["answerability_requires_synced_propagation"])

    def test_capabilities_require_contract_header_and_fail_before_work(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from cygnus.runtime.services.auth_service import get_current_user

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_governance_knowledge_snapshot] = lambda: (
            self.snapshot
        )
        app.dependency_overrides[get_current_user] = lambda: type(
            "FakeUser", (), {"role": "admin", "global_role": "admin"}
        )()
        with TestClient(app) as client:
            missing = client.get("/api/session-bridge/capabilities")
            incompatible = client.get(
                "/api/session-bridge/capabilities",
                headers={"X-Cygnus-Session-Contract-Version": "2.0"},
            )
            compatible = client.get(
                "/api/session-bridge/capabilities",
                headers={"X-Cygnus-Session-Contract-Version": "1.0"},
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(
            missing.json()["detail"]["errors"], ["missing_contract_version"]
        )
        self.assertEqual(incompatible.status_code, 409)
        self.assertEqual(
            incompatible.json()["detail"]["errors"],
            ["incompatible_contract_version"],
        )
        self.assertEqual(compatible.status_code, 200)
        self.assertEqual(compatible.json()["contract_version"], "1.0")

    def test_openapi_manifest_endpoint_derives_from_manifest(self) -> None:
        from cygnus.substrate.agent_protocol import build_session_manifest

        projection = session_bridge_openapi_projection()
        manifest = build_session_manifest(governed_session_tool_definitions())
        projection_tools = cast(list[dict[str, object]], projection["tools"])
        self.assertEqual(projection["contract_version"], manifest.contract_version)
        self.assertEqual(projection["schema_fingerprint"], manifest.schema_fingerprint)
        self.assertEqual(len(projection_tools), 12)
        self.assertEqual(
            {tool["name"] for tool in projection_tools},
            {tool.name for tool in manifest.tools},
        )

    def test_contract_negotiation_fails_deterministically_before_work(self) -> None:
        from cygnus.substrate.agent_protocol import (
            SessionContractVersionError,
            negotiate_session_contract_version,
        )

        with self.assertRaises(SessionContractVersionError) as missing:
            negotiate_session_contract_version(None)
        self.assertEqual(missing.exception.code, "missing_contract_version")
        with self.assertRaises(SessionContractVersionError) as blank:
            negotiate_session_contract_version("  ")
        self.assertEqual(blank.exception.code, "missing_contract_version")
        with self.assertRaises(SessionContractVersionError) as incompatible:
            negotiate_session_contract_version("2.0")
        self.assertEqual(incompatible.exception.code, "incompatible_contract_version")
        with self.assertRaises(SessionContractVersionError) as malformed:
            negotiate_session_contract_version("not-semver")
        self.assertEqual(malformed.exception.code, "incompatible_contract_version")
        self.assertEqual(negotiate_session_contract_version("1.5"), "1.0")

    def test_manifest_is_the_only_schema_source(self) -> None:
        from cygnus.substrate.agent_protocol import (
            ToolDefinition,
            build_session_manifest,
        )

        definitions = governed_session_tool_definitions()
        manifest = build_session_manifest(definitions)
        # A second construction is byte-identical: no drift, one source.
        self.assertEqual(
            build_session_manifest(definitions).schema_fingerprint,
            manifest.schema_fingerprint,
        )
        # The canonical twelve names are enforced; a renamed tool fails loudly
        # instead of silently widening the contract.
        renamed = tuple(
            ToolDefinition(
                name="not_a_governed_tool"
                if d.name == "search_knowledge_objects"
                else d.name,
                description=d.description,
                parameters=d.parameters,
                risk_level=d.risk_level,
            )
            for d in definitions
        )
        with self.assertRaises(ValueError):
            build_session_manifest(renamed)

    def test_query_contract_version_echoes_negotiated_version(self) -> None:
        from cygnus.substrate.agent_protocol import (
            session_contract_error_envelope,
            session_tool_manifest_result_envelope,
        )

        payload = session_tool_manifest_result_envelope(
            status="success",
            summary="ok",
            data={"answer": "x"},
            warnings=("w",),
            errors=(),
            trace_ref="trace-1",
        )
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["warnings"], ["w"])
        self.assertEqual(payload["trace_ref"], "trace-1")

        from cygnus.substrate.agent_protocol import SessionContractVersionError

        error = SessionContractVersionError("2.0", code="incompatible_contract_version")
        envelope = session_contract_error_envelope(error)
        envelope_data = cast(dict[str, object], envelope["data"])
        self.assertEqual(envelope["contract_version"], "1.0")
        self.assertEqual(envelope["errors"], ["incompatible_contract_version"])
        self.assertEqual(envelope_data["supported_major"], "1")

    def test_http_query_handoff_serializes_the_same_contract(self) -> None:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_governance_knowledge_snapshot] = lambda: (
            self.snapshot
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/session-bridge/query",
                headers={"X-Cygnus-Session-Contract-Version": "1.0"},
                json={
                    "request_ref": "req-http",
                    "session_ref": "session-http",
                    "query": "cancel subscription",
                    "channel": "copilot",
                    "audience_context": {
                        "visibility": "external",
                        "product_line": "billing",
                        "plan_tier": "free",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["data"]["governance"]["state"], "restricted")
        self.assertEqual(payload["data"]["session_ref"], "session-http")


if __name__ == "__main__":
    unittest.main()
