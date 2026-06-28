#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = ("cygnus", "frontend")
IGNORED_PARTS = {"dist", "__pycache__", ".git", ".venv", ".omx", "node_modules"}
TEXT_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt"}
FORBIDDEN_RUNTIME_PATTERNS = (
    re.compile(r"__arkon_requires__"),
    re.compile(r"arkon@localhost"),
    re.compile(r"\bfrom\s+arkon\b"),
    re.compile(r"\bimport\s+arkon\b"),
    re.compile(r'"mcpServers"\s*:\s*\{\s*"arkon"'),
)


@dataclass(frozen=True)
class InventoryItem:
    path: str
    state: str
    lane: str
    note: str


SURFACE_MANIFEST = [
    InventoryItem(
        path="cygnus/api/__init__.py",
        state="removed",
        lane="retired-legacy-api-package",
        note="legacy api package removed after the final facade shrink",
    ),
    InventoryItem(
        path="cygnus/api/app.py",
        state="removed",
        lane="retired-legacy-api-package",
        note="legacy api app entry removed after the final facade shrink",
    ),
    InventoryItem(
        path="cygnus/api/auth.py",
        state="removed",
        lane="retired-compat-facade",
        note="retired during the backend/app-owner convergence batch",
    ),
    InventoryItem(
        path="cygnus/api/config.py",
        state="removed",
        lane="retired-compat-facade",
        note="retired during the backend/app-owner convergence batch",
    ),
    InventoryItem(
        path="cygnus/api/governance_router.py",
        state="removed",
        lane="retired-compat-facade",
        note="retired during the backend/governance-router convergence batch",
    ),
    InventoryItem(
        path="cygnus/runtime/__init__.py",
        state="kept",
        lane="runtime-shell-owner",
        note="runtime shell banner preserving imported upstream topology",
    ),
    InventoryItem(
        path="cygnus/runtime/governance_router.py",
        state="kept",
        lane="canonical-governance-router-owner",
        note="canonical owner for the governance surface routers",
    ),
    InventoryItem(
        path="cygnus/runtime/main.py",
        state="kept",
        lane="canonical-app-owner",
        note="single public FastAPI assembly owner",
    ),
    InventoryItem(
        path="cygnus/substrate/__init__.py",
        state="kept",
        lane="cygnus-owned-substrate-contracts",
        note="provider-neutral substrate contracts, not an app shell",
    ),
    InventoryItem(
        path="scripts/upstream_cutover_gate.py",
        state="kept",
        lane="deletion-readiness-gate",
        note="executable stop-line before deleting standalone Arkon",
    ),
]

GUARDRAIL_MANIFEST = [
    "tests/test_app_assembly_recovery.py",
    "tests/test_boundary_freeze_truth.py",
    "tests/test_internalization_identity_cutover.py",
    "tests/test_package_boundary_convergence.py",
    "tests/test_upstream_cutover_gate.py",
]


def iter_code_files(repo_root: Path):
    for relative_root in CODE_ROOTS:
        root = repo_root / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir() or any(part in IGNORED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            yield path


def scan_forbidden_runtime_residue(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for path in iter_code_files(repo_root):
        rel = path.relative_to(repo_root)
        if rel.as_posix() in {item.path for item in SURFACE_MANIFEST if item.state == "removed"}:
            continue

        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in FORBIDDEN_RUNTIME_PATTERNS:
                if pattern.search(line):
                    failures.append(f"{rel}:{lineno}: {pattern.pattern}")
                    break
    return failures


def build_inventory(repo_root: Path | None = None) -> dict[str, object]:
    resolved_root = repo_root or REPO_ROOT
    kept = [asdict(item) for item in SURFACE_MANIFEST if item.state == "kept" and (resolved_root / item.path).exists()]
    removed = [
        {
            **asdict(item),
            "exists": (resolved_root / item.path).exists(),
        }
        for item in SURFACE_MANIFEST
        if item.state == "removed"
    ]

    return {
        "summary": {
            "kept_surfaces": len(kept),
            "removed_surfaces": len(removed),
            "guardrail_files": len(GUARDRAIL_MANIFEST),
        },
        "kept_surfaces": kept,
        "removed_surfaces": removed,
        "guardrails": GUARDRAIL_MANIFEST,
        "unexpected_runtime_residue": scan_forbidden_runtime_residue(resolved_root),
        "next_replacement_target": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show the current standalone-Arkon replacement inventory."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable summary.",
    )
    args = parser.parse_args()

    inventory = build_inventory()
    if args.json:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 0

    print("[arkon-inventory] current replacement surfaces")
    print(f"- kept: {inventory['summary']['kept_surfaces']}")
    print(f"- removed: {inventory['summary']['removed_surfaces']}")
    print(f"- guardrails: {inventory['summary']['guardrail_files']}")
    next_targets = inventory["next_replacement_target"]
    if next_targets:
        print("- next replacement target:", ", ".join(next_targets))
    else:
        print("- next replacement target: none")
    if inventory["unexpected_runtime_residue"]:
        print("- unexpected runtime residue:")
        for item in inventory["unexpected_runtime_residue"]:
            print(f"  - {item}")
    else:
        print("- no unexpected runtime residue in runtime/product code roots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
