from __future__ import annotations

import importlib
import unittest
from pathlib import Path

ROUTER_BASELINE_FILES = [
    "cygnus/runtime/routers/__init__.py",
    "cygnus/runtime/routers/admin_embeddings.py",
    "cygnus/runtime/routers/admin_models.py",
    "cygnus/runtime/routers/admin_settings.py",
    "cygnus/runtime/routers/admin_stats.py",
    "cygnus/runtime/routers/audit.py",
    "cygnus/runtime/routers/auth.py",
    "cygnus/runtime/routers/governance/__init__.py",
    "cygnus/runtime/routers/governance/command_center.py",
    "cygnus/runtime/routers/governance/knowledge_graph.py",
    "cygnus/runtime/routers/governance/publish.py",
    "cygnus/runtime/routers/governance/recovery.py",
    "cygnus/runtime/routers/governance/review.py",
    "cygnus/runtime/routers/knowledge_types.py",
    "cygnus/runtime/routers/notes.py",
    "cygnus/runtime/routers/notifications.py",
    "cygnus/runtime/routers/oauth.py",
    "cygnus/runtime/routers/rbac.py",
    "cygnus/runtime/routers/skill_contributions.py",
    "cygnus/runtime/routers/skills.py",
    "cygnus/runtime/routers/sources.py",
    "cygnus/runtime/routers/wiki.py",
    "cygnus/runtime/routers/wiki_branches.py",
    "cygnus/runtime/routers/wiki_drafts.py",
    "cygnus/runtime/routers/wiki_images.py",
]

# Mirrors the current runtime router family. Governance seam adapters are
# intentional additions in this branch and must stay in the baseline.
# `scopes.py` was removed after internalization because the dormant legacy scope seam
# had no mounted mainline owner and no surviving current API assembly dependency.
MAIN_ASSEMBLED_ROUTER_MODULES = {
    "cygnus.runtime.routers.admin_embeddings": ["router"],
    "cygnus.runtime.routers.admin_models": ["router"],
    "cygnus.runtime.routers.admin_settings": ["router"],
    "cygnus.runtime.routers.admin_stats": ["router"],
    "cygnus.runtime.routers.audit": ["router"],
    "cygnus.runtime.routers.auth": ["router"],
    "cygnus.runtime.routers.governance.command_center": ["router"],
    "cygnus.runtime.routers.governance.knowledge_graph": ["router"],
    "cygnus.runtime.routers.governance.publish": ["router"],
    "cygnus.runtime.routers.governance.recovery": ["router"],
    "cygnus.runtime.routers.governance.review": ["router"],
    "cygnus.runtime.routers.knowledge_types": ["router"],
    "cygnus.runtime.routers.notes": ["router"],
    "cygnus.runtime.routers.notifications": ["router"],
    "cygnus.runtime.routers.oauth": ["router", "wellknown_router"],
    "cygnus.runtime.routers.rbac": ["router"],
    "cygnus.runtime.routers.skill_contributions": ["router"],
    "cygnus.runtime.routers.skills": ["router"],
    "cygnus.runtime.routers.sources": ["router"],
    "cygnus.runtime.routers.wiki": ["router"],
    "cygnus.runtime.routers.wiki_branches": ["router"],
    "cygnus.runtime.routers.wiki_drafts": ["router"],
    "cygnus.runtime.routers.wiki_images": ["router"],
}

REQUIRED_ROUTER_SURFACE_TOKENS = {
    "cygnus/runtime/routers/auth.py": ["/auth/login", "/auth/me", "/auth/status"],
    "cygnus/runtime/routers/sources.py": ["/sources", "/sources/upload", "/sources/{source_id}/plan/approve"],
    "cygnus/runtime/routers/wiki.py": ["/wiki/pages", "/wiki/index", "/wiki/graph"],
    "cygnus/runtime/routers/wiki_drafts.py": ["/wiki/drafts", "/wiki/drafts/{draft_id}/approve"],
    "cygnus/runtime/routers/wiki_branches.py": ["/wiki/branches", "/wiki/branches/{branch_id}/merge"],
    "cygnus/runtime/routers/skills.py": ["/skills", "/skills/upload"],
    "cygnus/runtime/routers/skill_contributions.py": ["/skill-contributions", "/admin/skill-contributions"],
    "cygnus/runtime/routers/rbac.py": ["/departments", "/employees", "/my/mcp-token/status"],
    "cygnus/runtime/routers/audit.py": ['prefix="/audit"', '"/log"'],
    "cygnus/runtime/routers/notifications.py": ["/notifications", "/notifications/unread-count"],
    "cygnus/runtime/routers/knowledge_types.py": ["/knowledge-types"],
}


class RouterBaselineImportTests(unittest.TestCase):
    def test_router_baseline_files_exist(self) -> None:
        for relative_path in ROUTER_BASELINE_FILES:
            self.assertTrue(Path(relative_path).is_file(), f"missing mirrored router file: {relative_path}")

    def test_router_baseline_files_are_syntax_valid(self) -> None:
        for relative_path in ROUTER_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")
            compile(source, relative_path, "exec")

    def test_router_baseline_topology_is_exactly_the_upstream_module_family(self) -> None:
        expected = {Path(path).relative_to("cygnus/runtime/routers") for path in ROUTER_BASELINE_FILES}
        actual = {
            path.relative_to("cygnus/runtime/routers")
            for path in Path("cygnus/runtime/routers").rglob("*.py")
            if "__pycache__" not in path.parts
        }

        self.assertEqual(expected, actual)

    def test_router_baseline_has_no_legacy_app_namespace_imports(self) -> None:
        for relative_path in ROUTER_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")

            self.assertNotIn("from app.", source)
            self.assertNotIn("import app.", source)
            self.assertNotIn(" app.", source)

    def test_main_assembled_router_modules_import_and_expose_apirouters(self) -> None:
        for module_name, symbols in MAIN_ASSEMBLED_ROUTER_MODULES.items():
            module = importlib.import_module(module_name)

            for symbol in symbols:
                router = getattr(module, symbol, None)
                self.assertIsNotNone(router, f"{module_name} missing router symbol: {symbol}")
                self.assertTrue(
                    hasattr(router, "routes"),
                    f"{module_name}.{symbol} should expose a FastAPI router-like object",
                )
                self.assertGreater(len(router.routes), 0, f"{module_name}.{symbol} should expose route entries")

    def test_router_baseline_preserves_key_upstream_route_surfaces(self) -> None:
        for relative_path, route_tokens in REQUIRED_ROUTER_SURFACE_TOKENS.items():
            source = Path(relative_path).read_text(encoding="utf-8")

            for route_token in route_tokens:
                self.assertIn(route_token, source, f"{relative_path} lost upstream route surface: {route_token}")

    def test_legacy_scopes_router_was_removed_from_current_runtime_tree(self) -> None:
        main_source = Path("cygnus/runtime/main.py").read_text(encoding="utf-8")

        self.assertNotIn("cygnus/runtime/routers/scopes.py", ROUTER_BASELINE_FILES)
        self.assertFalse(Path("cygnus/runtime/routers/scopes.py").exists())
        self.assertNotIn("scopes.router", main_source)


if __name__ == "__main__":
    unittest.main()
