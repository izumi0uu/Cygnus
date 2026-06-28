from __future__ import annotations

from pathlib import Path

SURFACE_BASELINE_FILES = [
    "cygnus/runtime/routers/__init__.py",
    "cygnus/runtime/routers/admin_embeddings.py",
    "cygnus/runtime/routers/admin_models.py",
    "cygnus/runtime/routers/admin_settings.py",
    "cygnus/runtime/routers/admin_stats.py",
    "cygnus/runtime/routers/audit.py",
    "cygnus/runtime/routers/auth.py",
    "cygnus/runtime/routers/knowledge_types.py",
    "cygnus/runtime/routers/notes.py",
    "cygnus/runtime/routers/notifications.py",
    "cygnus/runtime/routers/oauth.py",
    "cygnus/runtime/routers/rbac.py",
    "cygnus/runtime/routers/scopes.py",
    "cygnus/runtime/routers/skill_contributions.py",
    "cygnus/runtime/routers/skills.py",
    "cygnus/runtime/routers/sources.py",
    "cygnus/runtime/routers/wiki.py",
    "cygnus/runtime/routers/wiki_branches.py",
    "cygnus/runtime/routers/wiki_drafts.py",
    "cygnus/runtime/routers/wiki_images.py",
    "cygnus/runtime/mcp/__init__.py",
    "cygnus/runtime/mcp/logging.py",
    "cygnus/runtime/mcp/middleware.py",
    "cygnus/runtime/mcp/permissions.py",
    "cygnus/runtime/mcp/resources.py",
    "cygnus/runtime/mcp/server.py",
    "cygnus/runtime/mcp/tools.py",
]


def test_surface_baseline_files_exist() -> None:
    for relative_path in SURFACE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored surface file: {relative_path}"


def test_surface_baseline_files_are_syntax_valid() -> None:
    for relative_path in SURFACE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
