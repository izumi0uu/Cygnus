from __future__ import annotations

import ast
from pathlib import Path


def test_internalization_docs_freeze_package_roles() -> None:
    checks = {
        "docs/zh/arkon-internalization-plan.md": [
            "Package boundary freeze",
            "`cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**",
            "`cygnus/substrate/*` = **Cygnus-owned substrate contracts**",
            "`cygnus/domain/*` = **support-domain contracts / object vocabulary**",
            "`cygnus/evidence/*` = **evidence normalization and record layer**",
            "`cygnus/retrieval/*` = **object/evidence retrieval and source-trace query layer**",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = **governance control-plane modules**",
            "`cygnus/integrations/*` = **external/session-facing integration adapters**",
            "`cygnus/workflows/*` = **workflow composition layer, not generic runtime shell**",
            "`cygnus/api/*` = **removed legacy package**",
        ],
        "docs/en/arkon-internalization-plan.md": [
            "Package boundary freeze",
            "`cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**",
            "`cygnus/substrate/*` = **Cygnus-owned substrate contracts**",
            "`cygnus/domain/*` = **support-domain contracts / object vocabulary**",
            "`cygnus/evidence/*` = **evidence normalization and record layer**",
            "`cygnus/retrieval/*` = **object/evidence retrieval and source-trace query layer**",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = **governance control-plane modules**",
            "`cygnus/integrations/*` = **external/session-facing integration adapters**",
            "`cygnus/workflows/*` = **workflow composition layer, not generic runtime shell**",
            "`cygnus/api/*` = **removed legacy package**",
        ],
        "docs/agent/zh/execution-context.md": [
            "Package owner contract",
            "`cygnus/runtime/*` = imported runtime/app shell/reference topology",
            "`cygnus/substrate/*` = Cygnus-owned substrate contracts",
            "`cygnus/domain/*` = support-domain contracts / object vocabulary",
            "`cygnus/evidence/*` = evidence normalization and record layer",
            "`cygnus/retrieval/*` = object/evidence retrieval and source-trace query layer",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = governance control-plane modules",
            "`cygnus/integrations/*` = external/session-facing integration adapters",
            "`cygnus/workflows/*` = workflow composition layer，不是 generic runtime shell",
            "`cygnus/api/*` = 已移除的 legacy package",
            "`cygnus.runtime.main` 是 canonical app owner",
        ],
        "docs/agent/en/execution-context.md": [
            "Package owner contract",
            "`cygnus/runtime/*` = imported runtime/app shell/reference topology",
            "`cygnus/substrate/*` = Cygnus-owned substrate contracts",
            "`cygnus/domain/*` = support-domain contracts / object vocabulary",
            "`cygnus/evidence/*` = evidence normalization and record layer",
            "`cygnus/retrieval/*` = object/evidence retrieval and source-trace query layer",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = governance control-plane modules",
            "`cygnus/integrations/*` = external/session-facing integration adapters",
            "`cygnus/workflows/*` = workflow composition layer, not generic runtime shell",
            "`cygnus/api/*` = removed legacy package",
            "`cygnus.runtime.main` is the canonical app owner",
        ],
    }

    for relative_path, snippets in checks.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"missing `{snippet}` in {relative_path}"


def test_package_dunders_publish_single_owner_story() -> None:
    api_modules = sorted(path.name for path in Path("cygnus/api").glob("*.py"))
    package_snippets = {
        "cygnus/__init__.py": [
            "Cygnus support knowledge operating system package",
            "runtime shell ownership remains under ``cygnus.runtime``",
            "product boundary, not an app-shell compatibility layer",
        ],
        "cygnus/domain/__init__.py": [
            "Support-domain contracts and object vocabulary for Cygnus",
            "this package defines support-domain truth, not runtime wiring",
        ],
        "cygnus/evidence/__init__.py": [
            "Evidence normalization and record layer for Cygnus",
            "not a runtime shell or governance workflow owner",
        ],
        "cygnus/integrations/__init__.py": [
            "External and session-facing integration adapters for Cygnus",
            "adapter boundary, not the core governance domain itself",
        ],
        "cygnus/publish/__init__.py": [
            "Governance control-plane publish modules for Cygnus",
            "owns publish governance semantics, not runtime app-shell wiring",
        ],
        "cygnus/recovery/__init__.py": [
            "Governance control-plane recovery modules for Cygnus",
            "owns governance recovery semantics, not runtime app-shell wiring",
        ],
        "cygnus/retrieval/__init__.py": [
            "Object/evidence retrieval and source-trace query layer for Cygnus",
            "serves retrieval truth, not runtime entry wiring",
        ],
        "cygnus/review/__init__.py": [
            "Governance control-plane review modules for Cygnus",
            "owns governance semantics, not runtime app-shell wiring",
        ],
        "cygnus/runtime/__init__.py": [
            "runtime shell preserving imported Arkon topology",
            "not the whole Cygnus product boundary",
        ],
        "cygnus/substrate/__init__.py": [
            "Cygnus-owned substrate contracts",
            "not a second app shell or API entry layer",
        ],
        "cygnus/workflows/__init__.py": [
            "Workflow composition layer for Cygnus",
            "not a generic session runtime shell",
        ],
    }

    assert api_modules == []

    for relative_path, snippets in package_snippets.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"missing `{snippet}` in {relative_path}"


def test_governance_router_owner_converges_to_backend_router_package() -> None:
    main_text = Path("cygnus/runtime/main.py").read_text(encoding="utf-8")
    owner_text = Path("cygnus/runtime/governance_router.py").read_text(encoding="utf-8")

    assert "from cygnus.runtime.governance_router import router as governance_router" in main_text
    assert "router = APIRouter(tags=[\"governance\"])" in owner_text


def test_api_package_has_no_python_modules() -> None:
    api_modules = {
        path.name
        for path in Path("cygnus/api").glob("*.py")
        if path.name != "__pycache__"
    }

    assert api_modules == set()


def test_internal_import_policy_forbids_removed_api_facades_and_legacy_app_namespace() -> None:
    forbidden_modules = {
        "cygnus.api.auth",
        "cygnus.api.config",
        "cygnus.api.governance_router",
        "cygnus.api.app",
        "cygnus.api",
        "app",
    }

    scan_roots = [Path("cygnus"), Path("tests")]

    for root in scan_roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue

            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        assert name not in forbidden_modules, f"{path} imports forbidden module `{name}`"
                        assert not name.startswith("app."), f"{path} reintroduced legacy app namespace `{name}`"

                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert module not in forbidden_modules, f"{path} imports forbidden module `{module}`"
                    assert module != "app" and not module.startswith("app."), (
                        f"{path} reintroduced legacy app namespace `{module}`"
                    )
                    if module == "cygnus":
                        for alias in node.names:
                            assert alias.name != "api", f"{path} reintroduced removed `cygnus.api` package"
