from __future__ import annotations

import asyncio

import unittest

from cygnus.integrations.nanobot_tools import (
    GovernedKnowledgeTools,
    build_governed_tool_registry,
)
from cygnus.retrieval import (
    SubstrateKnowledgeSnapshot,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.substrate.agent_protocol import ToolCall
from cygnus.substrate.tool_runtime import dispatch_tool_calls
from cygnus.runtime.mcp.server import create_mcp_server


class NanobotToolIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = SubstrateKnowledgeSnapshot(
            objects=sample_knowledge_objects(),
            evidence=sample_support_evidence(),
        )
        self.tools = GovernedKnowledgeTools(self.snapshot)

    def test_tools_return_structured_retrieval_contracts(self) -> None:
        retrieval = self.tools.search_knowledge_objects(
            query="invoice export rollout",
            audience_context={
                "visibility": "external",
                "product_line": "billing",
                "plan_tier": "enterprise",
                "region": "eu",
            },
        )
        knowledge_object = self.tools.read_knowledge_object(
            id_or_slug="ko-invoice-export-enterprise-eu"
        )
        evidence = self.tools.search_support_evidence(
            query="refund exception",
            filters={"source_type": "internal_sop"},
        )
        trace = self.tools.get_source_trace(object_id="ko-invoice-export-enterprise-eu")

        self.assertEqual(retrieval["status"], "success")
        self.assertEqual(retrieval["data"]["results"][0]["object_type"], "answer_card")
        self.assertEqual(knowledge_object["status"], "success")
        self.assertEqual(
            knowledge_object["data"]["source_trace_summary"]["freshness"],
            "stale",
        )
        self.assertEqual(evidence["status"], "success")
        self.assertEqual(evidence["data"]["results"][0]["source_type"], "internal_sop")
        self.assertEqual(trace["status"], "success")
        self.assertEqual(len(trace["data"]["evidence_refs"]), 2)

    def test_tool_instances_do_not_share_governed_truth(self) -> None:
        empty_tools = GovernedKnowledgeTools(
            SubstrateKnowledgeSnapshot(objects=(), evidence=())
        )

        self.assertEqual(
            empty_tools.search_knowledge_objects(query="refund")["data"]["results"],
            [],
        )
        self.assertNotEqual(
            self.tools.search_knowledge_objects(query="refund")["data"]["results"],
            [],
        )

    def test_registry_exposes_only_ready_governed_retrieval_tools(self) -> None:
        registry = build_governed_tool_registry(self.snapshot)
        definitions = {
            definition.name: definition for definition in registry.list_definitions()
        }

        self.assertEqual(
            set(definitions),
            {
                "search_knowledge_objects",
                "read_knowledge_object",
                "search_support_evidence",
                "get_source_trace",
            },
        )
        self.assertTrue(
            all(definition.risk_level == "R0" for definition in definitions.values())
        )

        results = dispatch_tool_calls(
            registry,
            (
                ToolCall(
                    id="tool-1",
                    name="search_knowledge_objects",
                    arguments={
                        "query": "invoice export",
                        "audience_context": {
                            "visibility": "external",
                            "product_line": "billing",
                            "plan_tier": "enterprise",
                            "region": "eu",
                        },
                    },
                ),
                ToolCall(
                    id="tool-2",
                    name="get_source_trace",
                    arguments={"object_id": "ko-invoice-export-enterprise-eu"},
                ),
            ),
        )

        self.assertEqual(results[0][2]["status"], "success")
        self.assertEqual(
            results[1][2]["trace_ref"], "trace:ko-invoice-export-enterprise-eu"
        )

    def test_runtime_mcp_registers_governed_tools_as_the_support_default(self) -> None:
        mcp = create_mcp_server()
        tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

        self.assertTrue(
            {
                "search_knowledge_objects",
                "read_knowledge_object",
                "search_support_evidence",
                "get_source_trace",
            }.issubset(tool_names)
        )
        self.assertIn("Never treat chat history", mcp.instructions)
