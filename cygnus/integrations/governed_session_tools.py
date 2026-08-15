from __future__ import annotations

from cygnus.integrations.governed_feedback_tools import feedback_tool_definitions
from cygnus.integrations.governed_draft_review_tools import (
    draft_review_tool_definitions,
)
from cygnus.integrations.governed_drift_tools import drift_tool_definitions
from cygnus.integrations.governed_publish_tools import publish_tool_definitions
from cygnus.integrations.nanobot_tools import knowledge_tool_definitions
from cygnus.substrate.agent_protocol import ToolDefinition


_GOVERNED_SESSION_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    *knowledge_tool_definitions(),
    *drift_tool_definitions(),
    *draft_review_tool_definitions(),
    *feedback_tool_definitions(),
    *publish_tool_definitions(),
)
_GOVERNED_SESSION_TOOL_DEFINITIONS_BY_NAME = {
    definition.name: definition for definition in _GOVERNED_SESSION_TOOL_DEFINITIONS
}
if len(_GOVERNED_SESSION_TOOL_DEFINITIONS_BY_NAME) != len(
    _GOVERNED_SESSION_TOOL_DEFINITIONS
):
    raise RuntimeError("governed session tool definitions must have unique names")


def governed_session_tool_definitions() -> tuple[ToolDefinition, ...]:
    """The sole ready-tool contract consumed by MCP and session capabilities."""
    return _GOVERNED_SESSION_TOOL_DEFINITIONS


def governed_session_tool_definition(name: str) -> ToolDefinition:
    """Return the exact canonical definition singleton for one governed tool."""
    try:
        return _GOVERNED_SESSION_TOOL_DEFINITIONS_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"unknown governed session tool: {name}") from exc
