from __future__ import annotations

import importlib
import unittest
from pathlib import Path

MCP_BASELINE_FILES = [
    "cygnus/runtime/mcp/__init__.py",
    "cygnus/runtime/mcp/logging.py",
    "cygnus/runtime/mcp/middleware.py",
    "cygnus/runtime/mcp/permissions.py",
    "cygnus/runtime/mcp/resources.py",
    "cygnus/runtime/mcp/server.py",
    "cygnus/runtime/mcp/tools.py",
]

MCP_BASELINE_MODULES = {
    "cygnus.runtime.mcp.logging": ["logged_tool"],
    "cygnus.runtime.mcp.middleware": ["ScopedToolsMiddleware"],
    "cygnus.runtime.mcp.permissions": [
        "ToolRequirement",
        "ANY_AUTHENTICATED",
        "CAN_CONTRIBUTE_WIKI",
        "CAN_REVIEW_WIKI",
        "CAN_CREATE_WIKI_DIRECT",
        "kb_tool",
        "requirement_for",
    ],
    "cygnus.runtime.mcp.resources": ["register_resources"],
    "cygnus.runtime.mcp.server": ["create_mcp_server"],
    "cygnus.runtime.mcp.tools": [
        "_get_identity",
        "_get_allowed_source_ids",
        "_can_review_page",
        "_can_contribute_to_page",
        "_format_oos_hint",
        "register_tools",
    ],
}

REQUIRED_MCP_SURFACE_TOKENS = {
    "cygnus/runtime/mcp/server.py": ["FastMCP", "register_tools(mcp)", "register_resources(mcp)", "ScopedToolsMiddleware"],
    "cygnus/runtime/mcp/resources.py": ["cygnus://about", "cygnus://knowledge-index"],
    "cygnus/runtime/mcp/permissions.py": ["ToolRequirement", "ANY_AUTHENTICATED", "CAN_REVIEW_WIKI", "kb_tool"],
    "cygnus/runtime/mcp/middleware.py": ["ScopedToolsMiddleware", "on_list_tools", "requirement_for"],
    "cygnus/runtime/mcp/logging.py": ["logged_tool", "MCPQueryLog", "_classify_status"],
    "cygnus/runtime/mcp/tools.py": [
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
    ],
}


class MCPBaselineImportTests(unittest.TestCase):
    def test_mcp_baseline_files_exist(self) -> None:
        for relative_path in MCP_BASELINE_FILES:
            self.assertTrue(Path(relative_path).is_file(), f"missing mirrored MCP file: {relative_path}")

    def test_mcp_baseline_files_are_syntax_valid(self) -> None:
        for relative_path in MCP_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")
            compile(source, relative_path, "exec")

    def test_mcp_baseline_topology_is_exactly_the_upstream_module_family(self) -> None:
        expected = {Path(path).relative_to("cygnus/runtime/mcp") for path in MCP_BASELINE_FILES}
        actual = {
            path.relative_to("cygnus/runtime/mcp")
            for path in Path("cygnus/runtime/mcp").rglob("*.py")
            if "__pycache__" not in path.parts
        }

        self.assertEqual(expected, actual)

    def test_mcp_baseline_has_no_legacy_app_namespace_imports(self) -> None:
        for relative_path in MCP_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")

            self.assertNotIn("from app.", source)
            self.assertNotIn("import app.", source)

    def test_mcp_modules_import_and_expose_upstream_entrypoints(self) -> None:
        for module_name, symbols in MCP_BASELINE_MODULES.items():
            module = importlib.import_module(module_name)

            for symbol in symbols:
                value = getattr(module, symbol, None)
                self.assertIsNotNone(value, f"{module_name} missing upstream MCP symbol: {symbol}")

    def test_mcp_baseline_preserves_key_tool_and_resource_surfaces(self) -> None:
        for relative_path, tokens in REQUIRED_MCP_SURFACE_TOKENS.items():
            source = Path(relative_path).read_text(encoding="utf-8")

            for token in tokens:
                self.assertIn(token, source, f"{relative_path} lost upstream MCP surface token: {token}")

    def test_mcp_server_factory_creates_fastmcp_instance_with_registered_surface(self) -> None:
        from cygnus.runtime.mcp.server import create_mcp_server

        mcp = create_mcp_server()

        self.assertTrue(hasattr(mcp, "tool"))
        self.assertTrue(hasattr(mcp, "resource"))
        self.assertTrue(hasattr(mcp, "http_app"))
        self.assertTrue(hasattr(mcp, "list_tools"))
        self.assertTrue(hasattr(mcp, "call_tool"))


if __name__ == "__main__":
    unittest.main()
