from __future__ import annotations

from pathlib import Path

KNOWLEDGE_BASELINE_FILES = [
    "app/ai/__init__.py",
    "app/ai/embedding_catalog.py",
    "app/ai/llm_catalog.py",
    "app/ai/registry.py",
    "app/ai/vision_catalog.py",
    "app/ai/wiki_agent.py",
    "app/ai/wiki_agent_tools.py",
    "app/ai/wiki_analyzer.py",
    "app/ai/wiki_compiler.py",
]


def test_knowledge_baseline_files_exist() -> None:
    for relative_path in KNOWLEDGE_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored knowledge substrate file: {relative_path}"


def test_knowledge_baseline_files_are_syntax_valid() -> None:
    for relative_path in KNOWLEDGE_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
