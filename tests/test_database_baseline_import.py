from __future__ import annotations

from pathlib import Path

DATABASE_BASELINE_FILES = [
    "app/database/__init__.py",
    "app/database/models.py",
    "app/database/oauth_models.py",
    "app/database/repository.py",
]


def test_database_baseline_files_exist() -> None:
    for relative_path in DATABASE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored database file: {relative_path}"


def test_database_baseline_files_are_syntax_valid() -> None:
    for relative_path in DATABASE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
