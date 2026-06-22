from __future__ import annotations

from pathlib import Path

SURFACE_BASELINE_FILES = [
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
    "cygnus/backend/mcp/__init__.py",
    "cygnus/backend/mcp/logging.py",
    "cygnus/backend/mcp/middleware.py",
    "cygnus/backend/mcp/permissions.py",
    "cygnus/backend/mcp/resources.py",
    "cygnus/backend/mcp/server.py",
    "cygnus/backend/mcp/tools.py",
]


def test_surface_baseline_files_exist() -> None:
    for relative_path in SURFACE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored surface file: {relative_path}"


def test_surface_baseline_files_are_syntax_valid() -> None:
    for relative_path in SURFACE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
