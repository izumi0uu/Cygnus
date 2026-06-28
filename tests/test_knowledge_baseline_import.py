from __future__ import annotations

from pathlib import Path

KNOWLEDGE_BASELINE_FILES = [
    "cygnus/runtime/ai/__init__.py",
    "cygnus/runtime/ai/embedding_catalog.py",
    "cygnus/runtime/ai/llm_catalog.py",
    "cygnus/runtime/ai/registry.py",
    "cygnus/runtime/ai/vision_catalog.py",
    "cygnus/runtime/ai/wiki_agent.py",
    "cygnus/runtime/ai/wiki_agent_tools.py",
    "cygnus/runtime/ai/wiki_analyzer.py",
    "cygnus/runtime/ai/wiki_compiler.py",
]


def test_knowledge_baseline_files_exist() -> None:
    for relative_path in KNOWLEDGE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored knowledge substrate file: {relative_path}"


def test_knowledge_baseline_files_are_syntax_valid() -> None:
    for relative_path in KNOWLEDGE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
