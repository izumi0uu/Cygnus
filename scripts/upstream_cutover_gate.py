#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = ("cygnus", "frontend")
CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json"}
FORBIDDEN_CODE_PATTERNS = (
    re.compile(r"__arkon_requires__"),
    re.compile(r"arkon@localhost"),
    re.compile(r"\bfrom\s+arkon\b"),
    re.compile(r"\bimport\s+arkon\b"),
    re.compile(r'"mcpServers"\s*:\s*\{\s*"arkon"'),
)
IGNORED_CODE_PARTS = {"dist", "__pycache__"}
REMOVED_COMPAT_FILES = (
    "cygnus/api/__init__.py",
    "cygnus/api/app.py",
    "cygnus/api/auth.py",
    "cygnus/api/config.py",
    "cygnus/api/governance_router.py",
)
REQUIRED_DOC_SNIPPETS = {
    "docs/zh/arkon-internalization-plan.md": [
        "### 5.5 Upstream deletion readiness",
        "#### 5.5.1 Readiness gate checklist",
        "所有 gate item 都为 green",
        "`scripts/upstream_cutover_gate.py` 通过",
        "Jira 不再把“继续依赖外部 Arkon”当成默认前提",
    ],
    "docs/en/arkon-internalization-plan.md": [
        "### 5.5 Upstream deletion readiness",
        "#### 5.5.1 Readiness gate checklist",
        "all gate items remain green",
        "`scripts/upstream_cutover_gate.py` passes",
        "Jira no longer assumes “continue depending on external Arkon” as the default premise",
    ],
    "docs/agent/zh/execution-context.md": [
        "deletion-readiness gate",
        "`scripts/upstream_cutover_gate.py` 通过之前",
        "不能把 cutover 叙事写成 shell parity 或 P3",
    ],
    "docs/agent/en/execution-context.md": [
        "deletion-readiness gate",
        "before `scripts/upstream_cutover_gate.py` passes",
        "must not describe cutover as shell parity or P3",
    ],
    ".codex/skills/cygnus-jira-execution/SKILL.md": [
        "deletion-readiness gate",
        "upstream cutover started",
        "must not imply support verticalization or shell parity",
    ],
}


def iter_code_files(repo_root: Path):
    for relative_root in CODE_ROOTS:
        root = repo_root / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir() or any(part in IGNORED_CODE_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            yield path


def scan_forbidden_code_residue(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for path in iter_code_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in FORBIDDEN_CODE_PATTERNS:
                if pattern.search(line):
                    rel = path.relative_to(repo_root)
                    failures.append(f"{rel}:{lineno}: forbidden upstream residue `{pattern.pattern}`")
                    break
    return failures


def check_removed_compat_files(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for relative_path in REMOVED_COMPAT_FILES:
        if (repo_root / relative_path).exists():
            failures.append(f"{relative_path}: removed legacy api file reappeared")
    return failures


def check_removed_legacy_api_package(repo_root: Path) -> list[str]:
    api_root = repo_root / "cygnus/api"
    if not api_root.exists():
        return []

    actual = sorted(
        path.relative_to(repo_root).as_posix()
        for path in api_root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    if actual:
        return [
            "cygnus/api: removed legacy package must not contain Python modules "
            f"({', '.join(actual)})"
        ]

    return []


def check_required_docs(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for relative_path, snippets in REQUIRED_DOC_SNIPPETS.items():
        path = repo_root / relative_path
        if not path.exists():
            failures.append(f"{relative_path}: missing required boundary doc")
            continue
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                failures.append(f"{relative_path}: missing snippet `{snippet}`")
    return failures


def collect_failures(repo_root: Path | None = None) -> list[str]:
    resolved_root = repo_root or REPO_ROOT
    failures: list[str] = []
    failures.extend(scan_forbidden_code_residue(resolved_root))
    failures.extend(check_removed_compat_files(resolved_root))
    failures.extend(check_removed_legacy_api_package(resolved_root))
    failures.extend(check_required_docs(resolved_root))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Cygnus upstream-cutover readiness before deleting standalone Arkon."
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print failures.",
    )
    args = parser.parse_args()

    failures = collect_failures()
    if failures:
        if not args.quiet:
            print("[cutover-gate] FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if not args.quiet:
        print("[cutover-gate] OK")
        print("- no external Arkon code residue under runtime/product code roots")
        print("- legacy api package removed; no public compat facade remains")
        print("- deletion-readiness docs and agent/Jira contracts are present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
