"""Focused tests for CYG-139: governed MCP profile, bearer parsing, dispatch deny.

Covers:
- Shared case-insensitive Bearer parsing (`parse_bearer_token`) and uniform
  rejection of malformed credentials, including at the `_get_identity` seam.
- The governed canonical-tool allowlist and its lockstep with the tool
  definition contract.
- `tools/list` role subsets (viewer / contributor / reviewer / admin) over the
  canonical twelve, with legacy generic wiki / raw source / direct mutation /
  legacy approval names never advertised.
- `tools/call` mechanical deny of non-canonical names (even for admin) and
  role gating of canonical names.
- No handler may depend on identity fields undeclared on `ResolvedIdentity`.
"""

from __future__ import annotations

import ast
import asyncio
import unittest
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult
from fastmcp.tools.function_tool import FunctionTool
from mcp.types import CallToolRequestParams, TextContent

from cygnus.integrations.mcp_auth import ResolvedIdentity, parse_bearer_token
from cygnus.runtime.mcp.middleware import ScopedToolsMiddleware
from cygnus.runtime.mcp.permissions import (
    ADMIN_ONLY,
    ANY_AUTHENTICATED,
    CAN_CONTRIBUTE_WIKI,
    governed_tool_names,
    requirement_for,
    requirement_for_name,
)
from cygnus.runtime.mcp.server import create_mcp_server

ALL_CANONICAL_NAMES = frozenset(
    {
        "search_knowledge_objects",
        "read_knowledge_object",
        "search_support_evidence",
        "get_source_trace",
        "list_drift_alerts",
        "record_feedback_signal",
        "validate_publish_policy",
        "publish_knowledge_object",
        "propose_knowledge_object",
        "update_draft_object",
        "request_review",
        "read_review_feedback",
    }
)

# Canonical tools any authenticated identity may use.
PUBLIC_CANONICAL_NAMES = ALL_CANONICAL_NAMES - {
    "publish_knowledge_object",
    "propose_knowledge_object",
    "update_draft_object",
    "request_review",
}

# Canonical tools the contributor tier adds on top of the public surface.
CONTRIBUTOR_CANONICAL_NAMES = frozenset(
    {"propose_knowledge_object", "update_draft_object", "request_review"}
)

# Registered-but-denied legacy surface: generic wiki, raw source, direct
# edit/create, and legacy approval tool names.
LEGACY_TOOL_NAMES = frozenset(
    {
        "search_wiki",
        "read_wiki_index",
        "read_wiki_page",
        "list_wiki_pages",
        "get_source",
        "get_source_outline",
        "get_source_pages",
        "search_source_content",
        "list_sources",
        "list_knowledge_types",
        "get_knowledge_type_docs",
        "propose_wiki_edit",
        "edit_wiki_page",
        "list_pending_drafts",
        "review_draft",
        "approve_draft",
        "reject_draft",
        "request_changes_on_draft",
        "resubmit_draft",
        "withdraw_draft",
        "propose_wiki_create",
        "create_wiki_page",
    }
)


def _identity(*, role: str, is_admin: bool = False) -> ResolvedIdentity:
    permissions = {
        "viewer": [],
        "contributor": ["wiki:write:own_dept"],
        "reviewer": ["wiki:write:all"],
    }[role]
    return ResolvedIdentity(
        employee_id=uuid.uuid4(),
        employee_name=role,
        permissions=permissions,
        is_admin=is_admin,
    )


def _list_context() -> MiddlewareContext:
    return MiddlewareContext(
        message=None,
        source="client",
        type="request",
        method="tools/list",
    )


def _call_context(name: str) -> MiddlewareContext:
    return MiddlewareContext(
        message=CallToolRequestParams(name=name, arguments={}),
        source="client",
        type="request",
        method="tools/call",
    )


def _registered_tools() -> Sequence[Tool]:
    mcp = create_mcp_server()
    return asyncio.run(mcp.list_tools(run_middleware=False))


def _list_names(result) -> set[str]:
    return {tool.name for tool in result}


def _tool_fn(tool: Tool | None) -> Callable[..., Any]:
    """Callable backing a registered FastMCP tool (FunctionTool.fn)."""
    assert isinstance(tool, FunctionTool)
    return tool.fn


def _denied_text(result: ToolResult) -> str:
    """Text of the first content item (MCP content variant narrowing)."""
    content = result.content[0]
    assert isinstance(content, TextContent)
    return content.text


class SharedBearerParsingTests(unittest.TestCase):
    """Shared case-insensitive Bearer parsing, uniform malformed rejection."""

    def test_accepts_any_scheme_casing(self) -> None:
        for header in (
            "Bearer ark_token_1",
            "bearer ark_token_1",
            "BEARER ark_token_1",
            "BeArEr ark_token_1",
        ):
            with self.subTest(header=header):
                self.assertEqual(parse_bearer_token(header), "ark_token_1")

    def test_tolerates_collapsed_internal_whitespace(self) -> None:
        # Multiple spaces/tabs between scheme and token are tolerated the same
        # way every bearer consumer sees them.
        self.assertEqual(parse_bearer_token("Bearer   ark_token_1"), "ark_token_1")
        self.assertEqual(parse_bearer_token("bearer\tark_token_1"), "ark_token_1")

    def test_rejects_malformed_or_non_bearer_uniformly(self) -> None:
        malformed = (
            None,
            "",
            "   ",
            "Bearer",
            "Bearer ",
            "bearer",
            "BEARER",
            "Bearer a b",
            "bearer a b c",
            "Basic dXNlcjpwYXNz",
            "Digest username=u, realm=r",
            "Token abc",
        )
        for header in malformed:
            with self.subTest(header=header):
                self.assertIsNone(
                    parse_bearer_token(header), f"accepted malformed header {header!r}"
                )

    def test_get_identity_extracts_token_from_lowercase_scheme(self) -> None:
        """Tool-layer auth interoperates with any Bearer casing."""
        identity = _identity(role="viewer")
        request = MagicMock()
        request.headers.get.return_value = "bearer ark_lowercase-scheme-token"

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def commit(self) -> None:
                return None

        fake_service = MagicMock()
        fake_service.verify_token = AsyncMock(return_value=identity)
        fake_service.bumped_last_connected = False

        with (
            patch("fastmcp.server.dependencies.get_http_request", return_value=request),
            patch(
                "cygnus.integrations.mcp_auth.MCPAuthService",
                return_value=fake_service,
            ),
            patch(
                "cygnus.runtime.database.async_session_factory",
                return_value=FakeSession(),
            ),
        ):
            from cygnus.runtime.mcp.tools import _get_identity

            resolved, error = asyncio.run(_get_identity())

        self.assertIsNone(error)
        self.assertIs(resolved, identity)
        fake_service.verify_token.assert_awaited_once_with("ark_lowercase-scheme-token")

    def test_get_identity_rejects_bare_scheme_without_db_hit(self) -> None:
        """A malformed credential yields the uniform auth error, never a lookup."""
        request = MagicMock()
        request.headers.get.return_value = "Bearer"

        fake_service = MagicMock()
        fake_service.verify_token = AsyncMock()

        with (
            patch("fastmcp.server.dependencies.get_http_request", return_value=request),
            patch(
                "cygnus.integrations.mcp_auth.MCPAuthService",
                return_value=fake_service,
            ),
        ):
            from cygnus.runtime.mcp.tools import _get_identity

            resolved, error = asyncio.run(_get_identity())

        self.assertIsNone(resolved)
        self.assertIn("Authentication required", error or "")
        fake_service.verify_token.assert_not_awaited()


class GovernedAllowlistTests(unittest.TestCase):
    """Canonical allowlist matches the tool definition contract and registration."""

    def test_allowlist_is_exactly_the_canonical_twelve(self) -> None:
        from cygnus.integrations.governed_session_tools import (
            governed_session_tool_definitions,
        )

        definition_names = {
            definition.name for definition in governed_session_tool_definitions()
        }
        self.assertEqual(governed_tool_names(), frozenset(definition_names))
        self.assertEqual(len(governed_tool_names()), 12)
        self.assertEqual(governed_tool_names(), ALL_CANONICAL_NAMES)

    def test_legacy_names_are_registered_but_not_canonical(self) -> None:
        self.assertTrue(LEGACY_TOOL_NAMES.isdisjoint(governed_tool_names()))

    def test_every_canonical_tool_registers_with_its_requirement(self) -> None:
        mcp = create_mcp_server()
        for name in sorted(governed_tool_names()):
            tool = asyncio.run(mcp.get_tool(name))
            self.assertIsNotNone(tool, f"{name} was not registered")
            self.assertIs(
                requirement_for(_tool_fn(tool)),
                requirement_for_name(name),
                f"registration-derived requirement mismatch for {name}",
            )

    def test_registration_derived_requirements_match_roles(self) -> None:
        self.assertIs(requirement_for_name("publish_knowledge_object"), ADMIN_ONLY)
        self.assertIs(
            requirement_for_name("propose_knowledge_object"), CAN_CONTRIBUTE_WIKI
        )
        self.assertIs(requirement_for_name("update_draft_object"), CAN_CONTRIBUTE_WIKI)
        self.assertIs(requirement_for_name("request_review"), CAN_CONTRIBUTE_WIKI)
        self.assertIs(
            requirement_for_name("search_knowledge_objects"), ANY_AUTHENTICATED
        )


class RoleListTests(unittest.TestCase):
    """tools/list returns exactly the role-permitted canonical subset."""

    def _listed_names_for(self, identity, *, hint: bool = False) -> set[str]:
        middleware = ScopedToolsMiddleware()
        tools = _registered_tools()
        identity_result = (
            (identity, None)
            if identity is not None
            else (
                None,
                "No HTTP request context available.",
            )
        )

        async def run() -> Sequence[Tool]:
            with patch(
                "cygnus.runtime.mcp.tools._get_identity",
                new=AsyncMock(return_value=identity_result),
            ):
                return await middleware.on_list_tools(_list_context(), _next)

        async def _next(_context):
            return tools

        listed = asyncio.run(run())
        names = _list_names(listed)
        if hint and identity is None:
            self.assertTrue(
                all(
                    t.description is not None
                    and t.description.startswith("[Authenticate to use]")
                    for t in listed
                )
            )
        return names

    def test_unauthenticated_lists_only_public_canonical_tools(self) -> None:
        names = self._listed_names_for(None, hint=True)
        self.assertEqual(names, PUBLIC_CANONICAL_NAMES)

    def test_viewer_lists_only_public_canonical_tools(self) -> None:
        names = self._listed_names_for(_identity(role="viewer"))
        self.assertEqual(names, PUBLIC_CANONICAL_NAMES)

    def test_contributor_lists_public_plus_contribute_tools(self) -> None:
        names = self._listed_names_for(_identity(role="contributor"))
        self.assertEqual(names, PUBLIC_CANONICAL_NAMES | CONTRIBUTOR_CANONICAL_NAMES)

    def test_reviewer_lists_same_surface_as_contributor(self) -> None:
        names = self._listed_names_for(_identity(role="reviewer"))
        self.assertEqual(names, PUBLIC_CANONICAL_NAMES | CONTRIBUTOR_CANONICAL_NAMES)

    def test_admin_lists_the_full_canonical_twelve(self) -> None:
        names = self._listed_names_for(_identity(role="viewer", is_admin=True))
        self.assertEqual(names, ALL_CANONICAL_NAMES)

    def test_legacy_names_never_advertised_for_any_role(self) -> None:
        for role, is_admin in (
            ("viewer", False),
            ("contributor", False),
            ("reviewer", False),
            ("viewer", True),
        ):
            with self.subTest(role=role, is_admin=is_admin):
                names = self._listed_names_for(_identity(role=role, is_admin=is_admin))
                self.assertTrue(names.issubset(ALL_CANONICAL_NAMES))
                self.assertTrue(LEGACY_TOOL_NAMES.isdisjoint(names))


class DispatchDenyTests(unittest.TestCase):
    """tools/call mechanically denies non-canonical names and role-gates canonical ones."""

    def _dispatch(self, name: str, identity=None) -> tuple[ToolResult, AsyncMock]:
        middleware = ScopedToolsMiddleware()
        call_next = AsyncMock(side_effect=AssertionError("call_next must not run"))
        identity_result = (
            (identity, None)
            if identity is not None
            else (
                None,
                "Authentication required.",
            )
        )

        async def run():
            with patch(
                "cygnus.runtime.mcp.tools._get_identity",
                new=AsyncMock(return_value=identity_result),
            ):
                return await middleware.on_call_tool(_call_context(name), call_next)

        result = asyncio.run(run())
        return result, call_next

    def test_generic_wiki_and_raw_source_names_denied_even_for_admin(self) -> None:
        admin = _identity(role="viewer", is_admin=True)
        for name in (
            "search_wiki",
            "read_wiki_page",
            "get_source",
            "get_source_pages",
            "search_source_content",
            "list_sources",
            "list_knowledge_types",
        ):
            with self.subTest(name=name):
                result, call_next = self._dispatch(name, admin)
                self.assertTrue(result.is_error)
                self.assertIn("cannot be called", _denied_text(result))
                call_next.assert_not_awaited()

    def test_direct_edit_create_and_legacy_approval_denied_even_for_admin(self) -> None:
        admin = _identity(role="viewer", is_admin=True)
        for name in (
            "edit_wiki_page",
            "create_wiki_page",
            "propose_wiki_edit",
            "propose_wiki_create",
            "approve_draft",
            "reject_draft",
            "request_changes_on_draft",
            "review_draft",
            "list_pending_drafts",
            "resubmit_draft",
            "withdraw_draft",
        ):
            with self.subTest(name=name):
                result, call_next = self._dispatch(name, admin)
                self.assertTrue(result.is_error)
                self.assertIn("cannot be called", _denied_text(result))
                call_next.assert_not_awaited()

    def test_unknown_names_denied(self) -> None:
        admin = _identity(role="viewer", is_admin=True)
        for name in ("raw_db_execute", "direct_insert", "totally_made_up_tool"):
            with self.subTest(name=name):
                result, call_next = self._dispatch(name, admin)
                self.assertTrue(result.is_error)
                self.assertIn("cannot be called", _denied_text(result))
                call_next.assert_not_awaited()

    def test_unauthenticated_canonical_call_denied(self) -> None:
        result, call_next = self._dispatch("read_knowledge_object", identity=None)
        self.assertTrue(result.is_error)
        self.assertIn("cannot be called", _denied_text(result))
        call_next.assert_not_awaited()

    def test_admin_only_publish_denied_for_non_admin(self) -> None:
        for role in ("viewer", "contributor", "reviewer"):
            with self.subTest(role=role):
                result, call_next = self._dispatch(
                    "publish_knowledge_object", _identity(role=role)
                )
                self.assertTrue(result.is_error)
                self.assertIn("administrator", _denied_text(result))
                call_next.assert_not_awaited()

    def test_admin_only_publish_allowed_for_admin(self) -> None:
        middleware = ScopedToolsMiddleware()
        call_next = AsyncMock(return_value=ToolResult(content="published"))
        admin = _identity(role="viewer", is_admin=True)

        async def run():
            with patch(
                "cygnus.runtime.mcp.tools._get_identity",
                new=AsyncMock(return_value=(admin, None)),
            ):
                return await middleware.on_call_tool(
                    _call_context("publish_knowledge_object"), call_next
                )

        result = asyncio.run(run())
        self.assertFalse(result.is_error)
        call_next.assert_awaited_once()

    def test_contribute_tools_denied_for_viewer_allowed_for_contributor(self) -> None:
        for name in (
            "propose_knowledge_object",
            "update_draft_object",
            "request_review",
        ):
            with self.subTest(name=name, role="viewer"):
                result, call_next = self._dispatch(name, _identity(role="viewer"))
                self.assertTrue(result.is_error)
                call_next.assert_not_awaited()

            middleware = ScopedToolsMiddleware()
            call_next = AsyncMock(return_value=ToolResult(content="ok"))
            contributor = _identity(role="contributor")

            async def run():
                with patch(
                    "cygnus.runtime.mcp.tools._get_identity",
                    new=AsyncMock(return_value=(contributor, None)),
                ):
                    return await middleware.on_call_tool(_call_context(name), call_next)

            with self.subTest(name=name, role="contributor"):
                result = asyncio.run(run())
                self.assertFalse(result.is_error)
                call_next.assert_awaited_once()

    def test_public_canonical_tools_allowed_for_any_authenticated_role(self) -> None:
        for name in ("read_knowledge_object", "list_drift_alerts", "get_source_trace"):
            middleware = ScopedToolsMiddleware()
            call_next = AsyncMock(return_value=ToolResult(content="ok"))
            viewer = _identity(role="viewer")

            async def run():
                with patch(
                    "cygnus.runtime.mcp.tools._get_identity",
                    new=AsyncMock(return_value=(viewer, None)),
                ):
                    return await middleware.on_call_tool(_call_context(name), call_next)

            with self.subTest(name=name):
                result = asyncio.run(run())
                self.assertFalse(result.is_error)
                call_next.assert_awaited_once()

    def test_direct_dispatch_denies_legacy_names_end_to_end(self) -> None:
        """Real FastMCP call_tool path: legacy names never reach a handler body.

        The deny fires before identity resolution, so no HTTP context or DB is
        needed and the legacy bodies (which reference undeclared identity
        fields) are unreachable.
        """
        mcp = create_mcp_server()
        for name in ("edit_wiki_page", "approve_draft", "search_wiki", "get_source"):
            with self.subTest(name=name):
                result = asyncio.run(mcp.call_tool(name, {}))
                assert isinstance(result, ToolResult)
                self.assertTrue(result.is_error)
                text = _denied_text(result)
                self.assertIn("cannot be called", text)
                self.assertIn("governed Cygnus profile", text)


class DeclaredIdentityFieldGuardTests(unittest.TestCase):
    """No MCP handler may depend on identity fields undeclared on ResolvedIdentity."""

    def test_handlers_only_use_declared_identity_fields(self) -> None:
        declared = set(ResolvedIdentity.__dataclass_fields__)
        for relative in (
            "cygnus/runtime/mcp/tools.py",
            "cygnus/runtime/mcp/middleware.py",
        ):
            source = Path(relative).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
            used: set[str] = set()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "identity"
                ):
                    used.add(node.attr)
            undeclared = used - declared
            self.assertFalse(
                undeclared,
                f"{relative} accesses undeclared identity fields: {sorted(undeclared)}",
            )


if __name__ == "__main__":
    unittest.main()
