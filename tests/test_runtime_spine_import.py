from __future__ import annotations

from pathlib import Path

RUNTIME_SPINE_FILES = [
    "cygnus/backend/__init__.py",
    "cygnus/backend/main.py",
    "cygnus/backend/config.py",
    "cygnus/backend/worker.py",
    "cygnus/backend/utils/__init__.py",
    "cygnus/backend/utils/progress.py",
    "cygnus/backend/utils/text.py",
    "cygnus/backend/utils/tokens.py",
]


def test_runtime_spine_files_exist() -> None:
    for relative_path in RUNTIME_SPINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored runtime file: {relative_path}"


def test_runtime_spine_files_are_syntax_valid() -> None:
    for relative_path in RUNTIME_SPINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
