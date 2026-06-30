from __future__ import annotations

from pathlib import Path

RUNTIME_SPINE_FILES = [
    "cygnus/runtime/__init__.py",
    "cygnus/runtime/main.py",
    "cygnus/runtime/config.py",
    "cygnus/runtime/source_ingest.py",
    "cygnus/runtime/source_state.py",
    "cygnus/runtime/worker.py",
    "cygnus/runtime/utils/__init__.py",
    "cygnus/runtime/utils/progress.py",
    "cygnus/runtime/utils/text.py",
    "cygnus/runtime/utils/tokens.py",
]


def test_runtime_spine_files_exist() -> None:
    for relative_path in RUNTIME_SPINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored runtime file: {relative_path}"


def test_runtime_spine_files_are_syntax_valid() -> None:
    for relative_path in RUNTIME_SPINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")


def test_runtime_source_ingest_surface_exposes_ingest_entrypoint() -> None:
    source = Path("cygnus/runtime/source_ingest.py").read_text(encoding="utf-8")

    assert "Source ingest orchestration for the Cygnus runtime shell." in source
    assert "async def ingest_source(" in source
