from __future__ import annotations

import unittest

from cygnus.integrations.nanobot_tools import (
    build_default_tool_registry,
    get_source_trace,
    list_drift_alerts,
    propose_knowledge_object,
    publish_knowledge_object,
    read_knowledge_object,
    request_review,
    search_knowledge_objects,
    search_support_evidence,
    validate_publish_policy,
)
from cygnus.substrate.agent_protocol import ToolCall
from cygnus.substrate.tool_runtime import dispatch_tool_calls


class NanobotToolIntegrationTests(unittest.TestCase):
    def test_tools_return_structured_contracts(self) -> None:
        retrieval = search_knowledge_objects(
            query="invoice export rollout",
            audience_context={
                "visibility": "external",
                "product_line": "billing",
                "plan_tier": "enterprise",
                "region": "eu",
            },
        )
        knowledge_object = read_knowledge_object(
            id_or_slug="ko-invoice-export-enterprise-eu"
        )
        evidence = search_support_evidence(
            query="refund exception",
            filters={"source_type": "internal_sop"},
        )
        trace = get_source_trace(object_id="ko-invoice-export-enterprise-eu")
        proposal = propose_knowledge_object(
            object_type="policy_rule",
            title="Refund policy",
            summary="Draft a governed refund rule",
            evidence_ids=["ev-1"],
        )
        review = request_review(draft_id=proposal["data"]["draft_id"])
        validation = validate_publish_policy(
            draft_id=proposal["data"]["draft_id"],
            target_channel="help_center",
        )
        publish = publish_knowledge_object(
            draft_id=proposal["data"]["draft_id"],
            target_channel="help_center",
        )
        drift = list_drift_alerts()

        self.assertEqual(retrieval["status"], "success")
        self.assertEqual(retrieval["data"]["results"][0]["object_type"], "answer_card")
        self.assertEqual(knowledge_object["status"], "success")
        self.assertEqual(knowledge_object["data"]["source_trace_summary"]["freshness"], "stale")
        self.assertEqual(evidence["status"], "success")
        self.assertEqual(evidence["data"]["results"][0]["source_type"], "internal_sop")
        self.assertEqual(trace["status"], "success")
        self.assertEqual(len(trace["data"]["evidence_refs"]), 2)
        self.assertEqual(proposal["data"]["lifecycle_state"], "draft")
        self.assertEqual(review["data"]["review_status"], "requested")
        self.assertTrue(validation["data"]["approval_required"])
        self.assertEqual(publish["status"], "approval_required")
        self.assertGreaterEqual(drift["data"]["alert_count"], 1)

    def test_default_registry_exposes_governed_tool_surface(self) -> None:
        registry = build_default_tool_registry()
        definitions = {definition.name: definition for definition in registry.list_definitions()}

        self.assertIn("search_knowledge_objects", definitions)
        self.assertIn("read_knowledge_object", definitions)
        self.assertIn("get_source_trace", definitions)
        self.assertIn("publish_knowledge_object", definitions)
        self.assertEqual(definitions["publish_knowledge_object"].risk_level, "R3")

        results = dispatch_tool_calls(
            registry,
            (
                ToolCall(
                    id="tool-1",
                    name="request_review",
                    arguments={"draft_id": "draft-123"},
                ),
            ),
        )

        self.assertEqual(results[0][2]["status"], "success")
