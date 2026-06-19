from __future__ import annotations

from pathlib import Path

RUNTIME_SPINE_FILES = [
    "app/__init__.py",
    "app/main.py",
    "app/config.py",
    "app/worker.py",
    "app/utils/__init__.py",
    "app/utils/progress.py",
    "app/utils/text.py",
    "app/utils/tokens.py",
]


def test_runtime_spine_files_exist() -> None:
    for relative_path in RUNTIME_SPINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored runtime file: {relative_path}"


def test_runtime_spine_files_are_syntax_valid() -> None:
    for relative_path in RUNTIME_SPINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
