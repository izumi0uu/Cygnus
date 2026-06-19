from __future__ import annotations

from pathlib import Path


BOUNDARY_FILES = [
    "docs/zh/arkon-full-port-migration-plan.md",
    "docs/en/arkon-full-port-migration-plan.md",
    "docs/agent/zh/execution-context.md",
    "docs/agent/en/execution-context.md",
    ".codex/skills/cygnus-jira-execution/SKILL.md",
]


def test_boundary_files_exist() -> None:
    for relative_path in BOUNDARY_FILES:
        assert Path(relative_path).is_file(), f"missing boundary-freeze file: {relative_path}"


def test_completion_states_remain_explicit() -> None:
    checks = {
        "docs/zh/arkon-full-port-migration-plan.md": [
            "Source parity completed",
            "Runability recovered",
            "Cygnus verticalization completed",
            "状态汇报契约",
            "Jira 父子票解释契约",
        ],
        "docs/en/arkon-full-port-migration-plan.md": [
            "Source parity completed",
            "Runability recovered",
            "Cygnus verticalization completed",
            "Status-reporting contract",
            "Jira parent-child interpretation contract",
        ],
        "docs/agent/zh/execution-context.md": [
            "状态语言契约",
            "CYG-23 ~ CYG-25",
            "不要把 import parity、runability recovered、verticalization completed 混成一个完成态",
        ],
        "docs/agent/en/execution-context.md": [
            "Status-language contract",
            "CYG-23 ~ CYG-25",
            "do not merge import parity, runability recovered, and verticalization completed into one fuzzy done-state",
        ],
        ".codex/skills/cygnus-jira-execution/SKILL.md": [
            "Completion-state truth contract",
            "imported baseline",
            "recovered runability",
            "implemented support verticalization",
        ],
    }

    for relative_path, expected_snippets in checks.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in expected_snippets:
            assert snippet in text, f"missing boundary snippet `{snippet}` in {relative_path}"
