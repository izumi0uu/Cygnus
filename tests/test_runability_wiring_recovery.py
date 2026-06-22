from __future__ import annotations

import ast
from pathlib import Path
import tomllib


def test_pyproject_carries_imported_backend_dependency_surface() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]

    expected_prefixes = [
        "fastapi",
        "uvicorn",
        "sqlalchemy[asyncio]",
        "asyncpg",
        "fastmcp",
        "arq",
        "redis[hiredis]",
        "minio",
        "pydantic-settings",
        "openai",
        "anthropic",
        "google-genai",
    ]

    for prefix in expected_prefixes:
        assert any(dep.startswith(prefix) for dep in deps), f"missing dependency wiring for {prefix}"


def test_seed_skills_wiring_module_exists() -> None:
    script = Path("cygnus/backend/scripts/seed_skills.py")
    assert script.is_file(), "expected cygnus/backend/scripts/seed_skills.py to exist for app.main startup wiring"

    text = script.read_text(encoding="utf-8")
    assert "async def seed_builtin_skills" in text
    assert "Skills directory not found" in text


def test_main_references_existing_seed_skills_module() -> None:
    main_text = Path("cygnus/backend/main.py").read_text(encoding="utf-8")
    assert "from cygnus.backend.scripts.seed_skills import seed_builtin_skills" in main_text
    assert Path("cygnus/backend/scripts/__init__.py").is_file()


def test_all_local_app_imports_have_structural_targets() -> None:
    root = Path("cygnus/backend")
    local_modules: set[str] = set()

    for path in root.rglob("*.py"):
        dotted = path.with_suffix("").as_posix().replace("/", ".")
        local_modules.add(dotted)
        if path.name == "__init__.py":
            local_modules.add(path.parent.as_posix().replace("/", "."))

    missing: list[tuple[str, str]] = []

    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("cygnus.backend."):
                if node.module not in local_modules:
                    missing.append((str(path), node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("cygnus.backend.") and alias.name not in local_modules:
                        missing.append((str(path), alias.name))

    assert not missing, f"missing local app module targets: {missing}"
