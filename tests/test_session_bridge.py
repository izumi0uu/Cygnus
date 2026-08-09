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
from cygnus.integrations.session_bridge import (
    GovernanceDisposition,
    GovernedQueryRequest,
    GovernedSessionBridge,
    PriorGovernanceContext,
    session_bridge_capabilities,
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

    def test_query_selects_audience_variant_and_returns_governance_frame(self) -> None:
        payload = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-eu-export",
                session_ref="session-1",
                query="invoice export rollout",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="enterprise",
                    region="eu",
                ),
            )
        )

        self.assertEqual(payload["status"], "denied")
        data = payload["data"]
        self.assertEqual(data["governance"]["state"], "restricted")
        self.assertIn("stale_evidence", data["governance"]["codes"])
        self.assertEqual(
            data["answer"]["content"]["variant_label"],
            "eu-rollout-delay",
        )
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
        self.assertEqual(data["continuity"]["state"], "started")
        self.assertFalse(data["continuity"]["session_memory_used_as_truth"])

    def test_fresh_published_answer_is_directly_answerable(self) -> None:
        payload = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-cancel",
                query="cancel subscription",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="free",
                ),
            )
        )

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
        first = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-first",
                query="cancel subscription",
                audience_context=audience,
            )
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

        same = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-same",
                query="cancel subscription",
                audience_context=audience,
                previous_governance_context=previous,
            )
        )
        changed = self.bridge.query(
            GovernedQueryRequest(
                request_ref="req-changed",
                query="cancel subscription",
                audience_context=AudienceContext(
                    visibility=Visibility.EXTERNAL,
                    product_line="billing",
                    plan="free",
                    region="eu",
                ),
                previous_governance_context=previous,
            )
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
        payload = session_bridge_capabilities(self.snapshot)
        governed_tools = cast(list[dict[str, object]], payload["governed_tools"])
        not_exposed = cast(list[dict[str, object]], payload["not_exposed"])
        query_handoff = cast(dict[str, object], payload["query_handoff"])

        self.assertEqual(
            {tool["name"] for tool in governed_tools},
            {
                "search_knowledge_objects",
                "read_knowledge_object",
                "search_support_evidence",
                "get_source_trace",
                "validate_publish_policy",
                "publish_knowledge_object",
            },
        )
        unavailable_names = {tool["name"] for tool in not_exposed}
        self.assertNotIn("validate_publish_policy", unavailable_names)
        self.assertNotIn("publish_knowledge_object", unavailable_names)
        self.assertIn("request_review", unavailable_names)
        self.assertFalse(query_handoff["session_memory_is_truth"])

    def test_http_query_handoff_serializes_the_same_contract(self) -> None:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_governance_knowledge_snapshot] = lambda: (
            self.snapshot
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/session-bridge/query",
                json={
                    "request_ref": "req-http",
                    "session_ref": "session-http",
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
        self.assertEqual(payload["data"]["session_ref"], "session-http")


if __name__ == "__main__":
    unittest.main()
