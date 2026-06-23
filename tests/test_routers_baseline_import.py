from __future__ import annotations

import importlib
import unittest
from pathlib import Path

ROUTER_BASELINE_FILES = [
    "cygnus/backend/routers/__init__.py",
    "cygnus/backend/routers/admin_embeddings.py",
    "cygnus/backend/routers/admin_models.py",
    "cygnus/backend/routers/admin_settings.py",
    "cygnus/backend/routers/admin_stats.py",
    "cygnus/backend/routers/audit.py",
    "cygnus/backend/routers/auth.py",
    "cygnus/backend/routers/knowledge_types.py",
    "cygnus/backend/routers/notes.py",
    "cygnus/backend/routers/notifications.py",
    "cygnus/backend/routers/oauth.py",
    "cygnus/backend/routers/rbac.py",
    "cygnus/backend/routers/scopes.py",
    "cygnus/backend/routers/skill_contributions.py",
    "cygnus/backend/routers/skills.py",
    "cygnus/backend/routers/sources.py",
    "cygnus/backend/routers/wiki.py",
    "cygnus/backend/routers/wiki_branches.py",
    "cygnus/backend/routers/wiki_drafts.py",
    "cygnus/backend/routers/wiki_images.py",
]

# Mirrors the routers assembled by upstream Arkon main.py and Cygnus main.py.
# `scopes.py` is intentionally present in the source-parity baseline but is not
# mounted by upstream main.py either; keep it as dormant baseline until a P2/P2.5
# wiring ticket decides whether to repair or remove that legacy surface.
MAIN_ASSEMBLED_ROUTER_MODULES = {
    "cygnus.backend.routers.admin_embeddings": ["router"],
    "cygnus.backend.routers.admin_models": ["router"],
    "cygnus.backend.routers.admin_settings": ["router"],
    "cygnus.backend.routers.admin_stats": ["router"],
    "cygnus.backend.routers.audit": ["router"],
    "cygnus.backend.routers.auth": ["router"],
    "cygnus.backend.routers.knowledge_types": ["router"],
    "cygnus.backend.routers.notes": ["router"],
    "cygnus.backend.routers.notifications": ["router"],
    "cygnus.backend.routers.oauth": ["router", "wellknown_router"],
    "cygnus.backend.routers.rbac": ["router"],
    "cygnus.backend.routers.skill_contributions": ["router"],
    "cygnus.backend.routers.skills": ["router"],
    "cygnus.backend.routers.sources": ["router"],
    "cygnus.backend.routers.wiki": ["router"],
    "cygnus.backend.routers.wiki_branches": ["router"],
    "cygnus.backend.routers.wiki_drafts": ["router"],
    "cygnus.backend.routers.wiki_images": ["router"],
}

REQUIRED_ROUTER_SURFACE_TOKENS = {
    "cygnus/backend/routers/auth.py": ["/auth/login", "/auth/me", "/auth/status"],
    "cygnus/backend/routers/sources.py": ["/sources", "/sources/upload", "/sources/{source_id}/plan/approve"],
    "cygnus/backend/routers/wiki.py": ["/wiki/pages", "/wiki/index", "/wiki/graph"],
    "cygnus/backend/routers/wiki_drafts.py": ["/wiki/drafts", "/wiki/drafts/{draft_id}/approve"],
    "cygnus/backend/routers/wiki_branches.py": ["/wiki/branches", "/wiki/branches/{branch_id}/merge"],
    "cygnus/backend/routers/skills.py": ["/skills", "/skills/upload"],
    "cygnus/backend/routers/skill_contributions.py": ["/skill-contributions", "/admin/skill-contributions"],
    "cygnus/backend/routers/rbac.py": ["/departments", "/employees", "/my/mcp-token/status"],
    "cygnus/backend/routers/audit.py": ['prefix="/audit"', '"/log"'],
    "cygnus/backend/routers/notifications.py": ["/notifications", "/notifications/unread-count"],
    "cygnus/backend/routers/knowledge_types.py": ["/knowledge-types"],
    "cygnus/backend/routers/scopes.py": ["/scopes/{scope_type}/{scope_id}/members", "/my/scopes"],
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
        expected = {Path(path).relative_to("cygnus/backend/routers") for path in ROUTER_BASELINE_FILES}
        actual = {
            path.relative_to("cygnus/backend/routers")
            for path in Path("cygnus/backend/routers").rglob("*.py")
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

    def test_dormant_scopes_router_is_source_baseline_not_current_api_assembly(self) -> None:
        main_source = Path("cygnus/backend/main.py").read_text(encoding="utf-8")
        scopes_source = Path("cygnus/backend/routers/scopes.py").read_text(encoding="utf-8")

        self.assertIn("cygnus/backend/routers/scopes.py", ROUTER_BASELINE_FILES)
        self.assertIn("router = APIRouter", scopes_source)
        self.assertIn("/scopes/{scope_type}/{scope_id}/members", scopes_source)
        self.assertNotIn("scopes.router", main_source)


if __name__ == "__main__":
    unittest.main()
