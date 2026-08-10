from __future__ import annotations

from cygnus.integrations.governed_draft_review_tools import (
    draft_review_tool_definitions,
)
from cygnus.integrations.governed_drift_tools import drift_tool_definitions
from cygnus.integrations.governed_publish_tools import publish_tool_definitions
from cygnus.integrations.nanobot_tools import knowledge_tool_definitions
from cygnus.substrate.agent_protocol import ToolDefinition


_GOVERNED_SESSION_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    *knowledge_tool_definitions(),
    *draft_review_tool_definitions(),
    *publish_tool_definitions(),
    *drift_tool_definitions(),
)
if len({definition.name for definition in _GOVERNED_SESSION_TOOL_DEFINITIONS}) != len(
    _GOVERNED_SESSION_TOOL_DEFINITIONS
):
    raise RuntimeError("governed session tool definitions must have unique names")


def governed_session_tool_definitions() -> tuple[ToolDefinition, ...]:
    """The sole ready-tool contract consumed by MCP and session capabilities."""
    return _GOVERNED_SESSION_TOOL_DEFINITIONS


def governed_session_tool_definition(name: str) -> ToolDefinition:
    """Resolve one ready governed tool definition by its stable external name."""
    for definition in _GOVERNED_SESSION_TOOL_DEFINITIONS:
        if definition.name == name:
            return definition
    raise ValueError(f"unknown governed session tool: {name}")
