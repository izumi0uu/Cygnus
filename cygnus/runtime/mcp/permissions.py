"""
MCP tool-visibility requirements.

Each `@kb_tool` declares a `ToolRequirement` saying which identities can see
the tool in `tools/list`. The `ScopedToolsMiddleware` (cygnus/runtime/mcp/middleware.py)
evaluates the predicate against the bearer-token's `ResolvedIdentity` and
hides tools whose predicate returns False.

**Visibility != security.** Predicates here gate the *listing*. Tool bodies
still perform their own per-resource permission checks (e.g. `_can_review_page`
for a specific draft's parent page) because a client can always invoke a tool
by name even if it was hidden in the catalog.

Predicates must be pure functions of `ResolvedIdentity` — no I/O — because
`on_list_tools` fires on every MCP session bootstrap.
"""

from dataclasses import dataclass
from typing import Callable

from cygnus.integrations.mcp_auth import ResolvedIdentity

# Marker attribute set by `kb_tool` on the decorated function.
REQUIRES_ATTR = "__cygnus_requires__"


@dataclass(frozen=True)
class ToolRequirement:
    """A pure predicate over ResolvedIdentity, plus a human label.

    The label is surfaced in logs and in the unauthenticated-listing hint so
    operators can tell at a glance why a tool was hidden.
    """

    predicate: Callable[[ResolvedIdentity], bool]
    label: str

    def allows(self, identity: ResolvedIdentity) -> bool:
        return self.predicate(identity)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

ANY_AUTHENTICATED = ToolRequirement(
    predicate=lambda i: True,
    label="any authenticated identity",
)

ADMIN_ONLY = ToolRequirement(
    predicate=lambda identity: identity.is_admin,
    label="administrator",
)


def _can_contribute(identity: ResolvedIdentity) -> bool:
    """Author-tier: can propose drafts somewhere, or hold a wiki:write:*."""
    return identity.is_admin or identity.has_any_permission(
        "wiki:write:own_dept", "wiki:write:all"
    )


def _can_review(identity: ResolvedIdentity) -> bool:
    """Reviewer-tier: org-wide wiki:write:all."""
    return identity.is_admin or identity.has_permission("wiki:write:all")


CAN_CONTRIBUTE_WIKI = ToolRequirement(
    predicate=_can_contribute,
    label="wiki:write:*",
)

CAN_REVIEW_WIKI = ToolRequirement(
    predicate=_can_review,
    label="wiki:write:all",
)

# `create_wiki_page` / `edit_wiki_page` bypass the review queue, so they ride
# the reviewer ladder. Aliased for readability at call sites.
CAN_CREATE_WIKI_DIRECT = CAN_REVIEW_WIKI


# ---------------------------------------------------------------------------
# Governed session profile — the ONLY tool surface /mcp advertises/dispatches
# ---------------------------------------------------------------------------

_GOVERNED_TOOL_NAMES: frozenset[str] | None = None


def governed_tool_names() -> frozenset[str]:
    """Names of the governed session tools — the only tools /mcp may list or call.

    Derived from the governed session tool contract
    (cygnus.integrations.governed_session_tools) so the allowlist stays in
    lockstep with the tool definitions. Computed once per process.
    """
    global _GOVERNED_TOOL_NAMES
    if _GOVERNED_TOOL_NAMES is None:
        from cygnus.integrations.governed_session_tools import (
            governed_session_tool_definitions,
        )

        _GOVERNED_TOOL_NAMES = frozenset(
            definition.name for definition in governed_session_tool_definitions()
        )
    return _GOVERNED_TOOL_NAMES


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

# Registration-derived name → requirement map, populated by `kb_tool` so the
# dispatch gate (middleware.on_call_tool) can role-check a tool by name
# without reaching into FastMCP internals. Filled during register_tools().
TOOL_REQUIREMENTS: dict[str, ToolRequirement] = {}


def requirement_for_name(name: str) -> ToolRequirement | None:
    """Requirement attached to the registered tool `name`, or None if no such tool."""
    return TOOL_REQUIREMENTS.get(name)


def kb_tool(mcp, *, requires: ToolRequirement = ANY_AUTHENTICATED, **fastmcp_kwargs):
    """Register an MCP tool with one governed permission and manifest contract.

    Canonical tools receive their output schema, deadline, and policy metadata
    from the immutable session manifest. Legacy registrations receive no
    manifest projection and remain mechanically denied by middleware.
    """

    def decorator(fn):
        name = fastmcp_kwargs.get("name") or fn.__name__
        setattr(fn, REQUIRES_ATTR, requires)
        TOOL_REQUIREMENTS[name] = requires

        registration_kwargs = dict(fastmcp_kwargs)
        try:
            from cygnus.substrate.tool_runtime import session_tool_manifest

            manifest = session_tool_manifest()
            tool = manifest.tool(name)
        except ValueError:
            # This is a legacy registration. Middleware denies it before its
            # handler body, and it must not gain governed metadata by name.
            pass
        else:
            metadata = tool.metadata()
            existing_meta = registration_kwargs.get("meta")
            merged_meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
            merged_meta["cygnus_contract"] = {
                "contract_version": manifest.contract_version,
                "schema_fingerprint": manifest.schema_fingerprint,
                "permission_requirement": metadata["permission_requirement"],
                "risk_class": metadata["risk_class"],
                "side_effect_class": metadata["side_effect_class"],
                "idempotency_class": metadata["idempotency_class"],
                "retry_policy": metadata["retry_policy"],
            }
            registration_kwargs.setdefault("output_schema", metadata["output_schema"])
            registration_kwargs.setdefault("timeout", metadata["timeout_seconds"])
            registration_kwargs["meta"] = merged_meta
        return mcp.tool(**registration_kwargs)(fn)

    return decorator


def requirement_for(fn) -> ToolRequirement:
    """Read the requirement attached by `kb_tool`. Defaults to ANY_AUTHENTICATED.

    Returning a default rather than raising means a tool registered via raw
    `@mcp.tool()` stays *visible* to all authed callers — the CI guard
    (tests/mcp/test_registry_completeness.py) catches the oversight separately.
    """
    return getattr(fn, REQUIRES_ATTR, ANY_AUTHENTICATED)
