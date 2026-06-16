from __future__ import annotations

import unittest

from cygnus.substrate.agent_protocol import (
    AssistantTurn,
    ToolCall,
    ToolDefinition,
    assistant_message_from_turn,
    neutral_to_openai_messages,
    openai_tools_to_anthropic,
    tool_results_message,
)
from cygnus.substrate.tool_runtime import ToolRegistry, dispatch_tool_calls


class AgentProtocolTests(unittest.TestCase):
    def test_assistant_turn_and_tool_results_use_neutral_shapes(self) -> None:
        turn = AssistantTurn(
            text="I need Cygnus to validate before publish.",
            tool_calls=(
                ToolCall(
                    id="call-1",
                    name="validate_publish_policy",
                    arguments={"draft_id": "draft-1", "target_channel": "help_center"},
                ),
            ),
            finish_reason="tool_use",
        )

        assistant_message = assistant_message_from_turn(turn)
        tool_message = tool_results_message(
            [("call-1", "validate_publish_policy", {"status": "approval_required"})]
        )
        openai_messages = neutral_to_openai_messages([assistant_message, tool_message])

        self.assertEqual(assistant_message["role"], "assistant")
        self.assertEqual(assistant_message["tool_calls"][0].name, "validate_publish_policy")
        self.assertEqual(tool_message["tool_results"][0]["id"], "call-1")
        self.assertEqual(openai_messages[0]["tool_calls"][0]["function"]["name"], "validate_publish_policy")
        self.assertEqual(openai_messages[1]["role"], "tool")

    def test_openai_tools_can_be_projected_to_anthropic_shape(self) -> None:
        definition = ToolDefinition(
            name="search_support_evidence",
            description="Search evidence",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            risk_level="R0",
        )

        anthropic_tools = openai_tools_to_anthropic([definition.to_openai_tool()])

        self.assertEqual(anthropic_tools[0]["name"], "search_support_evidence")
        self.assertIn("input_schema", anthropic_tools[0])

    def test_registry_dispatches_tools_without_provider_specific_message_shape(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="request_review",
                description="Request review",
                parameters={"type": "object", "properties": {"draft_id": {"type": "string"}}},
                risk_level="R1",
            ),
            lambda *, draft_id: {"status": "success", "draft_id": draft_id},
        )

        results = dispatch_tool_calls(
            registry,
            (
                ToolCall(
                    id="call-2",
                    name="request_review",
                    arguments={"draft_id": "draft-2"},
                ),
            ),
        )

        self.assertEqual(results[0][0], "call-2")
        self.assertEqual(results[0][1], "request_review")
        self.assertEqual(results[0][2]["draft_id"], "draft-2")
