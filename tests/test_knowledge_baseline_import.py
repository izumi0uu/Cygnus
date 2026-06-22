from __future__ import annotations

from pathlib import Path

KNOWLEDGE_BASELINE_FILES = [
    "cygnus/backend/ai/__init__.py",
    "cygnus/backend/ai/embedding_catalog.py",
    "cygnus/backend/ai/llm_catalog.py",
    "cygnus/backend/ai/registry.py",
    "cygnus/backend/ai/vision_catalog.py",
    "cygnus/backend/ai/wiki_agent.py",
    "cygnus/backend/ai/wiki_agent_tools.py",
    "cygnus/backend/ai/wiki_analyzer.py",
    "cygnus/backend/ai/wiki_compiler.py",
]


def test_knowledge_baseline_files_exist() -> None:
    for relative_path in KNOWLEDGE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored knowledge substrate file: {relative_path}"


def test_knowledge_baseline_files_are_syntax_valid() -> None:
    for relative_path in KNOWLEDGE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
