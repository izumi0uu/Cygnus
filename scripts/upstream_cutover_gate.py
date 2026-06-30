#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = ("cygnus", "frontend")
LINK_SCAN_ROOTS = ("cygnus", "frontend", "scripts", "tests")
MANIFEST_FILES = ("pyproject.toml", "uv.lock")
CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json"}
FORBIDDEN_CODE_PATTERNS = (
    re.compile(r"__arkon_requires__"),
    re.compile(r"arkon@localhost"),
    re.compile(r"\bfrom\s+arkon\b"),
    re.compile(r"\bimport\s+arkon\b"),
    re.compile(r'"mcpServers"\s*:\s*\{\s*"arkon"'),
)
FORBIDDEN_EXTERNAL_CHECKOUT_PATTERNS = (
    re.compile(r"nduckmink/arkon"),
    re.compile(r"github\.com[:/][^\"'\s]*/arkon"),
    re.compile(r"git@github\.com:[^\"'\s]*/arkon"),
    re.compile(r"(?:^|[\"'=\s])\.\./[^\"'\s]*arkon(?:[\"'\s]|$)"),
    re.compile(r"(?:^|[\"'=\s])/[^\"'\s]*/arkon(?:[\"'\s]|$)"),
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
OWNER_TRUTH_FILES = {
    "cygnus/runtime/main.py": [
        "from cygnus.runtime.governance_router import router as governance_router",
        'title="Cygnus API"',
        "app = create_app(app_settings=settings)",
    ],
    "cygnus/runtime/governance_router.py": [
        'router = APIRouter(tags=["governance"])',
        "router.include_router(command_center_router, tags=[\"governance\"])",
        "router.include_router(knowledge_graph_router, tags=[\"governance\"])",
    ],
    "cygnus/runtime/config.py": [
        "def get_settings() -> Settings:",
        "settings = get_settings()",
    ],
    "cygnus/runtime/services/auth_service.py": [
        "from cygnus.runtime.config import settings",
        "def require_admin(",
        "def require_permission(permission: str):",
    ],
}
EXECUTABLE_PATH_FILES = (
    "scripts/governance_golden_path_gate.py",
    "cygnus/workflows/golden_path.py",
    "tests/test_workflows_golden_path.py",
    "tests/test_app_assembly_recovery.py",
)


class GateSectionResult:
    def __init__(self, *, name: str, description: str, failures: tuple[str, ...]) -> None:
        self.name = name
        self.description = description
        self.failures = failures

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "failures": list(self.failures),
            "ok": self.ok,
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


def _is_within_repo(repo_root: Path, target: Path) -> bool:
    try:
        target.relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def check_external_checkout_dependencies(repo_root: Path) -> list[str]:
    failures: list[str] = []

    gitmodules = repo_root / ".gitmodules"
    if gitmodules.exists() and gitmodules.read_text(encoding="utf-8").strip():
        failures.append(".gitmodules: submodule configuration must be absent before upstream deletion")

    for relative_path in MANIFEST_FILES:
        path = repo_root / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_EXTERNAL_CHECKOUT_PATTERNS:
            if pattern.search(text):
                failures.append(
                    f"{relative_path}: forbidden external checkout reference `{pattern.pattern}`"
                )
                break

    for relative_root in LINK_SCAN_ROOTS:
        root = repo_root / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_symlink():
                continue
            resolved = path.resolve()
            rel = path.relative_to(repo_root)
            if not _is_within_repo(repo_root, resolved):
                failures.append(f"{rel}: symlink escapes repo root -> {resolved}")

    return failures


def check_owner_truth(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for relative_path, snippets in OWNER_TRUTH_FILES.items():
        path = repo_root / relative_path
        if not path.exists():
            failures.append(f"{relative_path}: missing owner-truth file")
            continue
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                failures.append(f"{relative_path}: missing owner-truth snippet `{snippet}`")
    return failures


def check_executable_path(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for relative_path in EXECUTABLE_PATH_FILES:
        path = repo_root / relative_path
        if not path.exists():
            failures.append(f"{relative_path}: missing executable-path artifact")
    return failures


def build_gate_suite(repo_root: Path | None = None) -> list[GateSectionResult]:
    resolved_root = repo_root or REPO_ROOT
    return [
        GateSectionResult(
            name="code_residue_gate",
            description="No forbidden external Arkon runtime residue remains under code roots.",
            failures=tuple(scan_forbidden_code_residue(resolved_root)),
        ),
        GateSectionResult(
            name="compat_shrink_gate",
            description="Removed compat/api surfaces stay removed and do not reappear.",
            failures=tuple(
                [
                    *check_removed_compat_files(resolved_root),
                    *check_removed_legacy_api_package(resolved_root),
                ]
            ),
        ),
        GateSectionResult(
            name="owner_truth_gate",
            description="Canonical Cygnus runtime owners and package boundaries remain frozen.",
            failures=tuple(check_owner_truth(resolved_root)),
        ),
        GateSectionResult(
            name="executable_path_gate",
            description="The cutover stop-line still points at executable golden-path and boot artifacts.",
            failures=tuple(check_executable_path(resolved_root)),
        ),
        GateSectionResult(
            name="external_checkout_gate",
            description="No manifest, submodule, or symlink still depends on an external Arkon checkout.",
            failures=tuple(check_external_checkout_dependencies(resolved_root)),
        ),
        GateSectionResult(
            name="docs_truth_gate",
            description="Docs, agent context, and Jira execution skill preserve cutover language and stop-line truth.",
            failures=tuple(check_required_docs(resolved_root)),
        ),
    ]


def build_gate_report(repo_root: Path | None = None) -> dict[str, object]:
    suite = build_gate_suite(repo_root)
    return {
        "gate_name": "upstream_cutover_gate",
        "ok": all(section.ok for section in suite),
        "sections": [section.to_dict() for section in suite],
    }


def collect_failures(repo_root: Path | None = None) -> list[str]:
    report = build_gate_report(repo_root)
    failures: list[str] = []
    for section in report["sections"]:
        section_name = section["name"]
        for failure in section["failures"]:
            failures.append(f"[{section_name}] {failure}")
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the structured gate report as JSON.",
    )
    args = parser.parse_args()

    report = build_gate_report()
    failures = collect_failures()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    if failures:
        if not args.quiet:
            print("[cutover-gate] FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if not args.quiet:
        print("[cutover-gate] OK")
        for section in report["sections"]:
            print(f"- {section['name']}: OK")
        print("- deletion readiness remains backed by one structured stop-line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
