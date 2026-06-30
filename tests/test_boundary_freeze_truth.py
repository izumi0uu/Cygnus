from __future__ import annotations

from pathlib import Path
import tomllib


BOUNDARY_FILES = [
    "docs/README.md",
    "docs/zh/arkon-full-port-migration-plan.md",
    "docs/en/arkon-full-port-migration-plan.md",
    "docs/zh/arkon-internalization-plan.md",
    "docs/en/arkon-internalization-plan.md",
    "docs/agent/zh/execution-context.md",
    "docs/agent/en/execution-context.md",
    ".codex/skills/cygnus-jira-execution/SKILL.md",
    "scripts/upstream_cutover_gate.py",
]


def test_boundary_files_exist() -> None:
    for relative_path in BOUNDARY_FILES:
        assert Path(relative_path).is_file(), f"missing boundary-freeze file: {relative_path}"


def test_completion_states_remain_explicit() -> None:
    checks = {
        "docs/README.md": [
            "keep product-shell parity as a deferred non-roadmap lane by default",
            "classify `auth / admin / wiki` shell candidates before any shell-parity implementation",
        ],
        "docs/zh/arkon-full-port-migration-plan.md": [
            "Source parity completed",
            "Runability recovered",
            "Internalization completed",
            "Cygnus verticalization completed",
            "状态汇报契约",
            "Jira 父子票解释契约",
            "#### P4 当前候选分类",
            "support-relevant shell candidate",
            "generic-product shell candidate",
            "non-support shell work that stays excluded by default",
            "视觉完整度",
        ],
        "docs/en/arkon-full-port-migration-plan.md": [
            "Source parity completed",
            "Runability recovered",
            "Internalization completed",
            "Cygnus verticalization completed",
            "Status-reporting contract",
            "Jira parent-child interpretation contract",
            "#### Current P4 candidate classes",
            "support-relevant shell candidate",
            "generic-product shell candidate",
            "non-support shell work that stays excluded by default",
            "visual completeness",
        ],
        "docs/zh/arkon-internalization-plan.md": [
            "### 5.5 Upstream deletion readiness",
            "#### 5.5.1 Readiness gate checklist",
            "`scripts/upstream_cutover_gate.py` 通过",
            "Jira 不再把“继续依赖外部 Arkon”当成默认前提",
        ],
        "docs/en/arkon-internalization-plan.md": [
            "### 5.5 Upstream deletion readiness",
            "#### 5.5.1 Readiness gate checklist",
            "`scripts/upstream_cutover_gate.py` passes",
            "Jira no longer assumes “continue depending on external Arkon” as the default premise",
        ],
        "docs/zh/jira-project-configuration-plan.md": [
            "### 8.3 延期 shell parity lane",
            "`support-relevant-candidate`",
            "`generic-shell-reference`",
            "`non-support-excluded`",
        ],
        "docs/en/jira-project-configuration-plan.md": [
            "### 8.3 Deferred shell-parity lane",
            "`support-relevant-candidate`",
            "`generic-shell-reference`",
            "`non-support-excluded`",
        ],
        "docs/zh/open-questions.md": [
            "当前已冻结的边界",
            "非 support 主语页面继续隔离在 future parity lane",
        ],
        "docs/en/open-questions.md": [
            "Current frozen boundary",
            "non-support pages remain isolated in the future parity lane",
        ],
        ".codex/skills/cygnus-jira-execution/SKILL.md": [
            "Completion-state truth contract",
            "imported baseline",
            "recovered runability",
            "internalized substrate",
            "implemented support verticalization",
            "deletion-readiness gate",
            "### D. Deferred shell-parity lane",
            "classify `auth / admin / wiki` shell candidates",
            "support-relevant shell candidates",
            "generic-product shell candidates",
            "non-support pages",
        ],
        "docs/agent/zh/execution-context.md": [
            "状态语言契约",
            "CYG-23 ~ CYG-25",
            "P2.5",
            "不要把 import parity、runability recovered、internalization completed、verticalization completed 混成一个完成态",
            "LangGraph 不属于当前 Cygnus 主线",
            "deletion-readiness gate",
            "`scripts/upstream_cutover_gate.py` 通过之前",
            "不能把 cutover 叙事写成 shell parity 或 P3",
        ],
        "docs/agent/en/execution-context.md": [
            "Status-language contract",
            "CYG-23 ~ CYG-25",
            "P2.5",
            "do not merge import parity, runability recovered, internalization completed, and verticalization completed into one fuzzy done-state",
            "LangGraph is not part of the current Cygnus mainline",
            "deletion-readiness gate",
            "before `scripts/upstream_cutover_gate.py` passes",
            "must not describe cutover as shell parity or P3",
        ],
    }

    for relative_path, expected_snippets in checks.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in expected_snippets:
            assert snippet in text, f"missing boundary snippet `{snippet}` in {relative_path}"


def test_mainline_has_no_direct_langgraph_or_langchain_dependencies() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [dependency.lower() for dependency in project["project"]["dependencies"]]

    assert not any(
        dependency.startswith("langgraph") or dependency.startswith("langchain")
        for dependency in dependencies
    )


def test_mainline_docs_code_and_skills_do_not_reintroduce_langgraph_or_langchain() -> None:
    scan_roots = [Path("cygnus"), Path("docs"), Path("frontend"), Path("scripts"), Path(".codex/skills")]
    allowed_suffixes = {".py", ".md", ".toml", ".tsx", ".ts", ".js", ".jsx", ".json"}
    forbidden_hits: list[str] = []
    allowed_boundary_mentions = {
        "cygnus/__init__.py",
        "cygnus/substrate/__init__.py",
        "cygnus/workflows/__init__.py",
        "docs/agent/zh/execution-context.md",
        "docs/agent/en/execution-context.md",
        ".codex/skills/cygnus-jira-execution/SKILL.md",
    }

    for root in scan_roots:
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in allowed_suffixes:
                continue

            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            relative_path = path.as_posix()
            if "langgraph" in lowered or "langchain" in lowered:
                if relative_path not in allowed_boundary_mentions:
                    forbidden_hits.append(relative_path)

    assert forbidden_hits == []


def test_langgraph_lockfile_residue_stays_non_authoritative() -> None:
    lock_text = Path("uv.lock").read_text(encoding="utf-8")

    if 'name = "langgraph"' in lock_text or 'name = "langchain-core"' in lock_text:
        assert 'name = "content-core"' in lock_text
