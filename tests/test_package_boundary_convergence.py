from __future__ import annotations

import ast
from pathlib import Path


def test_internalization_docs_freeze_package_roles() -> None:
    checks = {
        "docs/zh/arkon-internalization-plan.md": [
            "Package boundary freeze",
            "`cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**",
            "`cygnus/substrate/*` = **Cygnus-owned substrate contracts**",
            "`cygnus/api/*` = **removed legacy package**",
        ],
        "docs/en/arkon-internalization-plan.md": [
            "Package boundary freeze",
            "`cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**",
            "`cygnus/substrate/*` = **Cygnus-owned substrate contracts**",
            "`cygnus/api/*` = **removed legacy package**",
        ],
        "docs/agent/zh/execution-context.md": [
            "Package owner contract",
            "`cygnus/runtime/*` = imported runtime/app shell/reference topology",
            "`cygnus/substrate/*` = Cygnus-owned substrate contracts",
            "`cygnus/api/*` = 已移除的 legacy package",
            "`cygnus.runtime.main` 是 canonical app owner",
        ],
        "docs/agent/en/execution-context.md": [
            "Package owner contract",
            "`cygnus/runtime/*` = imported runtime/app shell/reference topology",
            "`cygnus/substrate/*` = Cygnus-owned substrate contracts",
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
    runtime_text = Path("cygnus/runtime/__init__.py").read_text(encoding="utf-8")
    substrate_text = Path("cygnus/substrate/__init__.py").read_text(encoding="utf-8")

    assert api_modules == []

    assert "runtime shell preserving imported Arkon topology" in runtime_text
    assert "not the whole Cygnus product boundary" in runtime_text

    assert "Cygnus-owned substrate contracts" in substrate_text
    assert "not a second app shell or API entry layer" in substrate_text


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
