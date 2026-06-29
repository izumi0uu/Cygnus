from __future__ import annotations

from pathlib import Path


def test_governance_router_surface_adapters_exist() -> None:
    expected = [
        "cygnus/runtime/routers/governance/__init__.py",
        "cygnus/runtime/routers/governance/command_center.py",
        "cygnus/runtime/routers/governance/review.py",
        "cygnus/runtime/routers/governance/publish.py",
        "cygnus/runtime/routers/governance/recovery.py",
        "cygnus/runtime/routers/governance/knowledge_graph.py",
    ]

    for relative_path in expected:
        assert Path(relative_path).is_file(), f"missing governance adapter file: {relative_path}"


def test_governance_router_is_thin_assembly() -> None:
    text = Path("cygnus/runtime/governance_router.py").read_text(encoding="utf-8")

    assert "router = APIRouter(tags=[\"governance\"])" in text
    assert "from cygnus.runtime.routers.governance.command_center import router as command_center_router" in text
    assert "from cygnus.runtime.routers.governance.knowledge_graph import router as knowledge_graph_router" in text
    assert "router.include_router(command_center_router, tags=[\"governance\"])" in text
    assert "router.include_router(knowledge_graph_router, tags=[\"governance\"])" in text
