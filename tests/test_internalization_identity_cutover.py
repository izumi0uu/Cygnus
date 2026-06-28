from __future__ import annotations

from pathlib import Path

from cygnus.runtime.mcp.permissions import REQUIRES_ATTR


def test_mcp_requirement_marker_uses_cygnus_identity() -> None:
    assert REQUIRES_ATTR == "__cygnus_requires__"


def test_runtime_identity_residue_is_removed_from_target_files() -> None:
    checks = {
        "cygnus/runtime/mcp/permissions.py": ["__cygnus_requires__"],
        "cygnus/runtime/routers/rbac.py": ['"mcpServers": {{"cygnus"'],
        "cygnus/runtime/services/notification_dispatch.py": ["cygnus@localhost"],
    }

    forbidden = {
        "cygnus/runtime/mcp/permissions.py": ["__arkon_requires__"],
        "cygnus/runtime/routers/rbac.py": ['"mcpServers": {{"arkon"'],
        "cygnus/runtime/services/notification_dispatch.py": ["arkon@localhost"],
    }

    for relative_path, expected_snippets in checks.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in expected_snippets:
            assert snippet in text, f"missing expected snippet `{snippet}` in {relative_path}"

    for relative_path, forbidden_snippets in forbidden.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in text, f"found forbidden snippet `{snippet}` in {relative_path}"
