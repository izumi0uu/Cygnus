"""Compatibility shim for the legacy runtime agent_protocol path.

Canonical owner now lives in `cygnus.substrate.agent_protocol`. Keep this file
only so mirrored baseline imports remain valid during cutover.
"""

from cygnus.substrate.agent_protocol import (
    AssistantTurn,
    ToolCall,
    ToolDefinition,
    assistant_message_from_turn,
    neutral_to_anthropic_messages,
    neutral_to_gemini_contents,
    neutral_to_openai_messages,
    openai_tools_to_anthropic,
    openai_tools_to_gemini,
    tool_results_message,
)

__all__ = [
    "AssistantTurn",
    "ToolCall",
    "ToolDefinition",
    "assistant_message_from_turn",
    "neutral_to_anthropic_messages",
    "neutral_to_gemini_contents",
    "neutral_to_openai_messages",
    "openai_tools_to_anthropic",
    "openai_tools_to_gemini",
    "tool_results_message",
]
