"""
ScopedToolsMiddleware — filters MCP `tools/list` by bearer-token identity.

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
and drop tools whose `ToolRequirement.predicate(identity)` returns False.

Authenticated → return only the tools the identity could actually use.
Unauthenticated / invalid token → return the public (`ANY_AUTHENTICATED`)
tools with a one-line "authenticate to use" hint prepended to each
description, so a client that hasn't configured a token yet still sees
the read surface and a path to fixing the config.

What this is NOT
----------------
This is a UX gate, not a security boundary. A client can still invoke any
tool by name regardless of whether it appears in `tools/list` — the per-
tool body checks in `app/mcp/tools.py` remain the authoritative gate.
Removing those checks would create a real vulnerability; do not.
"""

from collections.abc import Sequence

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.tools.base import Tool

from app.mcp.permissions import (
    ANY_AUTHENTICATED,
    requirement_for,
)

# Prepended to public-tool descriptions when the caller has no valid token.
# Plain ASCII so it renders cleanly in every MCP client.
_AUTH_HINT = (
    "[Authenticate to use] Configure your MCP bearer token in your client "
    "(headers.Authorization: \"Bearer <token>\"). Without a valid token, "
    "calling this tool will return an authentication error.\n\n"
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


class ScopedToolsMiddleware(Middleware):
    """Hide tools the caller's identity can't use; hint when unauthenticated."""

    async def on_list_tools(self, context, call_next) -> Sequence[Tool]:
        tools = await call_next(context)

        # Lazy import: avoid eager DB / FastMCP-dependency wiring at module load.
        from app.mcp.tools import _get_identity

        identity, _err = await _get_identity()

        if identity is None:
            # Unauthenticated or invalid token. Show only the public surface
            # (ANY_AUTHENTICATED-gated tools), annotated with an auth hint.
            return [
                _hint_description(t)
                for t in tools
                if requirement_for(t.fn) is ANY_AUTHENTICATED
            ]

        return [t for t in tools if requirement_for(t.fn).allows(identity)]
