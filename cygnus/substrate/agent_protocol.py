from __future__ import annotations

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
