from __future__ import annotations

from pathlib import Path

SURFACE_BASELINE_FILES = [
    "app/routers/__init__.py",
    "app/routers/admin_embeddings.py",
    "app/routers/admin_models.py",
    "app/routers/admin_settings.py",
    "app/routers/admin_stats.py",
    "app/routers/audit.py",
    "app/routers/auth.py",
    "app/routers/knowledge_types.py",
    "app/routers/notes.py",
    "app/routers/notifications.py",
    "app/routers/oauth.py",
    "app/routers/rbac.py",
    "app/routers/scopes.py",
    "app/routers/skill_contributions.py",
    "app/routers/skills.py",
    "app/routers/sources.py",
    "app/routers/wiki.py",
    "app/routers/wiki_branches.py",
    "app/routers/wiki_drafts.py",
    "app/routers/wiki_images.py",
    "app/mcp/__init__.py",
    "app/mcp/logging.py",
    "app/mcp/middleware.py",
    "app/mcp/permissions.py",
    "app/mcp/resources.py",
    "app/mcp/server.py",
    "app/mcp/tools.py",
]


def test_surface_baseline_files_exist() -> None:
    for relative_path in SURFACE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored surface file: {relative_path}"


def test_surface_baseline_files_are_syntax_valid() -> None:
    for relative_path in SURFACE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
