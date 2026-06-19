from __future__ import annotations

from pathlib import Path

SERVICE_BASELINE_FILES = sorted(
    str(path)
    for path in Path("app/services").rglob("*.py")
    if "__pycache__" not in path.parts
)


def test_services_baseline_files_exist() -> None:
    assert SERVICE_BASELINE_FILES, "expected mirrored service files"
    for relative_path in SERVICE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored service file: {relative_path}"


def test_services_baseline_files_are_syntax_valid() -> None:
    for relative_path in SERVICE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
