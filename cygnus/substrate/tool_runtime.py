from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from cygnus.substrate.agent_protocol import ToolCall, ToolDefinition

ToolHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = RegisteredTool(definition=definition, handler=handler)

    def list_definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(item.definition for item in self._tools.values())

    def call(self, tool_call: ToolCall) -> Any:
        registered = self._tools.get(tool_call.name)
        if registered is None:
            raise ValueError(f"unknown tool: {tool_call.name}")
        return registered.handler(**tool_call.arguments)


def dispatch_tool_calls(
    registry: ToolRegistry,
    tool_calls: tuple[ToolCall, ...] | list[ToolCall],
) -> list[tuple[str, str, Any]]:
    results: list[tuple[str, str, Any]] = []
    for tool_call in tool_calls:
        result = registry.call(tool_call)
        results.append((tool_call.id, tool_call.name, result))
    return results
