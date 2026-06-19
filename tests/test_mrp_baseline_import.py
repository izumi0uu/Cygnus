from __future__ import annotations

from pathlib import Path

MRP_BASELINE_FILES = [
    "app/ai/mrp/__init__.py",
    "app/ai/mrp/mapper.py",
    "app/ai/mrp/merger.py",
    "app/ai/mrp/pipeline.py",
    "app/ai/mrp/reducer.py",
    "app/ai/mrp/verifier.py",
    "app/ai/mrp/writer.py",
]


def test_mrp_baseline_files_exist() -> None:
    for relative_path in MRP_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored MRP file: {relative_path}"


def test_mrp_baseline_files_are_syntax_valid() -> None:
    for relative_path in MRP_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
