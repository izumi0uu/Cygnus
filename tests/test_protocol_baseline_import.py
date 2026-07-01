from __future__ import annotations

from pathlib import Path

from cygnus.runtime.ai import agent_protocol as runtime_protocol
from cygnus.substrate import agent_protocol as substrate_protocol

PROTOCOL_BASELINE_FILES = [
    "cygnus/runtime/ai/agent_protocol.py",
    "cygnus/runtime/ai/providers/__init__.py",
    "cygnus/runtime/ai/providers/base.py",
    "cygnus/runtime/ai/providers/openai_provider.py",
    "cygnus/runtime/ai/providers/anthropic_provider.py",
    "cygnus/runtime/ai/providers/google.py",
]


def test_protocol_baseline_files_exist() -> None:
    for relative_path in PROTOCOL_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored protocol file: {relative_path}"


def test_protocol_baseline_files_are_syntax_valid() -> None:
    for relative_path in PROTOCOL_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")


def test_runtime_protocol_module_reexports_substrate_owner() -> None:
    assert runtime_protocol.AssistantTurn is substrate_protocol.AssistantTurn
    assert runtime_protocol.ToolCall is substrate_protocol.ToolCall
    assert runtime_protocol.assistant_message_from_turn is substrate_protocol.assistant_message_from_turn
    assert runtime_protocol.neutral_to_anthropic_messages is substrate_protocol.neutral_to_anthropic_messages


def test_runtime_ai_code_prefers_substrate_protocol_owner() -> None:
    allowed_runtime_shims = {"cygnus/runtime/ai/agent_protocol.py"}
    forbidden_patterns = (
        "from cygnus.runtime.ai.agent_protocol import",
        "import cygnus.runtime.ai.agent_protocol",
        "from cygnus.runtime.ai import agent_protocol",
        "from .agent_protocol import",
    )
    hits: list[str] = []

    for path in Path("cygnus").rglob("*.py"):
        relative_path = path.as_posix()
        if relative_path in allowed_runtime_shims:
            continue

        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in forbidden_patterns:
                if pattern in line:
                    hits.append(f"{relative_path}:{lineno}: {pattern}")

    assert hits == []
