from __future__ import annotations

"""Cygnus-owned provider-neutral agent/tool protocol.

Canonical owner for multi-turn tool-calling message shapes and provider-specific
projection helpers. Runtime AI code should import this module directly; the
runtime `agent_protocol` path remains only as a compatibility shim.
"""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("tool call id must not be blank")
        if not self.name.strip():
            raise ValueError("tool call name must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantTurn:
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    finish_reason: str = "end_turn"
    raw_provider_content: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if not self.finish_reason.strip():
            raise ValueError("finish_reason must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    risk_level: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool definition name must not be blank")
        if not self.description.strip():
            raise ValueError("tool definition description must not be blank")
        if not self.risk_level.strip():
            raise ValueError("tool definition risk_level must not be blank")

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def assistant_message_from_turn(turn: AssistantTurn) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": turn.text,
        "tool_calls": list(turn.tool_calls),
    }
    if turn.raw_provider_content is not None:
        message["_raw_content"] = turn.raw_provider_content
    return message


def tool_results_message(results: list[tuple[str, str, Any]]) -> dict[str, Any]:
    return {
        "role": "user",
        "tool_results": [
            {
                "id": call_id,
                "name": call_name,
                "content": json.dumps(result, ensure_ascii=False, default=str)
                if not isinstance(result, str)
                else result,
            }
            for call_id, call_name, result in results
        ],
    }


def neutral_to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            if "tool_results" in message:
                output.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": item["id"],
                                "content": item["content"],
                            }
                            for item in message["tool_results"]
                        ],
                    }
                )
            else:
                output.append({"role": "user", "content": message.get("content") or ""})
        elif role == "assistant":
            content_blocks: list[dict[str, Any]] = []
            if message.get("content"):
                content_blocks.append({"type": "text", "text": message["content"]})
            for tool_call in message.get("tool_calls", []):
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.arguments,
                    }
                )
            output.append(
                {
                    "role": "assistant",
                    "content": content_blocks or [{"type": "text", "text": ""}],
                }
            )
    return output


def neutral_to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            if "tool_results" in message:
                for item in message["tool_results"]:
                    output.append(
                        {
                            "role": "tool",
                            "tool_call_id": item["id"],
                            "content": item["content"],
                        }
                    )
            else:
                output.append({"role": "user", "content": message.get("content") or ""})
        elif role == "assistant":
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content"),
            }
            if message.get("tool_calls"):
                assistant_message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments),
                        },
                    }
                    for tool_call in message["tool_calls"]
                ]
            output.append(assistant_message)
    return output


def neutral_to_gemini_contents(messages: list[dict[str, Any]]):
    """Convert neutral messages to Gemini Content objects.

    Assistant messages may carry `_raw_content` so the originating provider can
    replay thought-signature-bearing content without lossy reconstruction.
    """
    from google.genai import types as gtypes

    output = []
    for message in messages:
        role = message["role"]
        if role == "user":
            if "tool_results" in message:
                parts = [
                    gtypes.Part(
                        function_response=gtypes.FunctionResponse(
                            name=item["name"],
                            response={"result": item["content"]},
                        )
                    )
                    for item in message["tool_results"]
                ]
                output.append(gtypes.Content(role="user", parts=parts))
            else:
                output.append(
                    gtypes.Content(
                        role="user",
                        parts=[gtypes.Part(text=message.get("content") or "")],
                    )
                )
        elif role == "assistant":
            if "_raw_content" in message:
                output.append(message["_raw_content"])
                continue

            parts = []
            if message.get("content"):
                parts.append(gtypes.Part(text=message["content"]))
            for tool_call in message.get("tool_calls", []):
                parts.append(
                    gtypes.Part(
                        function_call=gtypes.FunctionCall(
                            name=tool_call.name,
                            args=tool_call.arguments,
                        )
                    )
                )
            if not parts:
                parts = [gtypes.Part(text="")]
            output.append(gtypes.Content(role="model", parts=parts))
    return output


def openai_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "input_schema": tool["function"].get(
                "parameters",
                {"type": "object", "properties": {}},
            ),
        }
        for tool in tools
    ]


def openai_tools_to_gemini(tools: list[dict[str, Any]]):
    from google.genai import types as gtypes

    declarations = []
    for tool in tools:
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        declarations.append(
            gtypes.FunctionDeclaration(
                name=function["name"],
                description=function.get("description", ""),
                parameters=_json_schema_to_gemini_schema(parameters),
            )
        )
    return [gtypes.Tool(function_declarations=declarations)]


def _json_schema_to_gemini_schema(schema: dict[str, Any]):
    from google.genai import types as gtypes

    type_map = {
        "string": gtypes.Type.STRING,
        "number": gtypes.Type.NUMBER,
        "integer": gtypes.Type.INTEGER,
        "boolean": gtypes.Type.BOOLEAN,
        "array": gtypes.Type.ARRAY,
        "object": gtypes.Type.OBJECT,
    }
    gemini_type = type_map.get((schema.get("type") or "string").lower(), gtypes.Type.STRING)

    properties = None
    if schema.get("properties"):
        properties = {
            name: _json_schema_to_gemini_schema(value)
            for name, value in schema["properties"].items()
        }

    items = None
    if schema.get("items"):
        items = _json_schema_to_gemini_schema(schema["items"])

    return gtypes.Schema(
        type=gemini_type,
        description=schema.get("description"),
        properties=properties,
        required=schema.get("required"),
        items=items,
        enum=schema.get("enum"),
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
