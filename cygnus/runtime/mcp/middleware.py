"""
ScopedToolsMiddleware — gates MCP `tools/list` and `tools/call` by bearer-token
identity against the governed session profile.

Why this exists
---------------
FastMCP registers every `@kb_tool` globally, so by default `tools/list`
returns the union to every caller. Reviewer- and contributor-tier tools
showing up for a read-only employee is noise: Claude Desktop may surface
them, the user tries to invoke them, and only then do they get an
"insufficient permission" string back.

What this does
--------------
On every `tools/list` call, resolve the bearer token to a `ResolvedIdentity`
and drop tools whose `ToolRequirement.predicate(identity)` returns False,
restricted to the governed session profile (the canonical twelve tools from
`governed_session_tool_definitions()`).

On every `tools/call`, mechanically deny any tool name outside the governed
profile — generic wiki, raw source, and direct edit/create/legacy-approval
names are rejected even for administrators. Canonical tools are additionally
role-checked so dispatch matches the advertised role subset.

Authenticated → return only the tools the identity could actually use.
Unauthenticated / invalid token → return the public (`ANY_AUTHENTICATED`)
governed tools with a one-line "authenticate to use" hint prepended to each
description, so a client that hasn't configured a token yet still sees the
read surface and a path to fixing the config.

What this is NOT
----------------
This is a UX gate plus a hard dispatch boundary for the governed profile.
Per-tool body checks in `cygnus/runtime/mcp/tools.py` remain the
authoritative per-resource gate. Removing those checks would create a real
vulnerability; do not.
"""

from collections.abc import Sequence

from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult

from cygnus.runtime.mcp.permissions import (
    ANY_AUTHENTICATED,
    governed_tool_names,
    requirement_for,
    requirement_for_name,
)

# Prepended to public-tool descriptions when the caller has no valid token.
# Plain ASCII so it renders cleanly in every MCP client.
_AUTH_HINT = (
    "[Authenticate to use] Configure your MCP bearer token in your client "
    '(headers.Authorization: "Bearer <token>"). Without a valid token, '
    "calling this tool will return an authentication error.\n\n"
)

# Reason suffix for non-canonical tool names — generic wiki / raw source /
# direct mutation / legacy approval tools are never dispatchable on /mcp.
_NOT_GOVERNED = (
    "it is not part of the governed Cygnus profile. Generic wiki, raw source, "
    "and direct mutation tools are disabled on /mcp for every role."
)


def _hint_description(tool: Tool) -> Tool:
    """Return a copy of `tool` with the auth hint prepended to its description.

    Falls back to a plain hint-only description if the tool has none. Uses
    Pydantic `model_copy` so all other fields (schema, fn, annotations, etc.)
    are preserved intact.
    """
    base = tool.description or ""
    new_description = _AUTH_HINT + base if base else _AUTH_HINT.rstrip()
    return tool.model_copy(update={"description": new_description})


def _denied_tool_result(name: str, reason: str) -> ToolResult:
    """A uniformly shaped `is_error` result for a denied tool call."""
    return ToolResult(
        content=(
            f"Tool '{name}' cannot be called: {reason} "
            "Only role-allowed governed session tools are exposed through /mcp."
        ),
        is_error=True,
    )


class ScopedToolsMiddleware(Middleware):
    """Advertise and dispatch only the role-allowed governed session tools."""

    async def on_list_tools(self, context, call_next) -> Sequence[Tool]:
        tools = await call_next(context)
        canonical = governed_tool_names()

        # Lazy import: avoid eager DB / FastMCP-dependency wiring at module load.
        from cygnus.runtime.mcp.tools import _get_identity

        identity, _err = await _get_identity()

        if identity is None:
            # Unauthenticated or invalid token. Show only the public governed
            # surface (ANY_AUTHENTICATED-gated canonical tools), annotated with
            # an auth hint.
            return [
                _hint_description(t)
                for t in tools
                if t.name in canonical and requirement_for(t.fn) is ANY_AUTHENTICATED
            ]

        return [
            t
            for t in tools
            if t.name in canonical and requirement_for(t.fn).allows(identity)
        ]

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next,
    ) -> ToolResult:
        """Deny non-governed names mechanically, role-gate canonical names."""
        name = context.message.name

        # Hard boundary: only the governed session profile is dispatchable —
        # generic wiki, raw source, direct edit/create, and legacy approval
        # names are rejected for every role, including admin.
        if name not in governed_tool_names():
            return _denied_tool_result(name, _NOT_GOVERNED)

        # Lazy import: avoid eager DB / FastMCP-dependency wiring at module load.
        from cygnus.runtime.mcp.tools import _get_identity

        identity, error = await _get_identity()
        if identity is None:
            return _denied_tool_result(name, error or "Authentication required.")

        requirement = requirement_for_name(name)
        if requirement is None:
            # Advertised by the definition contract but not registered as a
            # dispatchable handler — fail closed rather than run an ungoverned
            # call path.
            return _denied_tool_result(name, "it is not registered as a handler.")
        if not requirement.allows(identity):
            return _denied_tool_result(name, f"it requires {requirement.label}.")

        return await call_next(context)
