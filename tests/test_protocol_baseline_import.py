from __future__ import annotations

from pathlib import Path

PROTOCOL_BASELINE_FILES = [
    "cygnus/backend/ai/agent_protocol.py",
    "cygnus/backend/ai/providers/__init__.py",
    "cygnus/backend/ai/providers/base.py",
    "cygnus/backend/ai/providers/openai_provider.py",
    "cygnus/backend/ai/providers/anthropic_provider.py",
    "cygnus/backend/ai/providers/google.py",
]


def test_protocol_baseline_files_exist() -> None:
    for relative_path in PROTOCOL_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored protocol file: {relative_path}"


def test_protocol_baseline_files_are_syntax_valid() -> None:
    for relative_path in PROTOCOL_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
