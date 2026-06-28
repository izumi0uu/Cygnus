from __future__ import annotations

import importlib
import inspect
from pathlib import Path

MRP_BASELINE_FILES = [
    "cygnus/runtime/ai/mrp/__init__.py",
    "cygnus/runtime/ai/mrp/mapper.py",
    "cygnus/runtime/ai/mrp/merger.py",
    "cygnus/runtime/ai/mrp/pipeline.py",
    "cygnus/runtime/ai/mrp/reducer.py",
    "cygnus/runtime/ai/mrp/verifier.py",
    "cygnus/runtime/ai/mrp/writer.py",
]

MRP_BASELINE_MODULES = {
    "cygnus.runtime.ai.mrp.mapper": [
        "DocumentChunk",
        "build_chunks",
        "extract_chunk",
        "run_map_phase",
    ],
    "cygnus.runtime.ai.mrp.reducer": [
        "collect_raw_items",
        "reconcile_with_kb",
        "run_planning_call",
        "run_reduce_phase",
    ],
    "cygnus.runtime.ai.mrp.writer": [
        "PageWriteResult",
        "SectionRef",
        "WriterPassBatch",
        "assemble_evidence",
        "run_refine_phase",
    ],
    "cygnus.runtime.ai.mrp.verifier": [
        "check_coverage",
        "check_conflicts",
        "assess_page_status",
        "run_verify_phase",
    ],
    "cygnus.runtime.ai.mrp.merger": [
        "merge_page_content",
    ],
    "cygnus.runtime.ai.mrp.pipeline": [
        "run_mrp_pipeline",
        "run_refine_pipeline",
        "run_commit_phase",
    ],
}

MRP_PIPELINE_PHASE_MARKERS = [
    "map",
    "reduce",
    "plan_review",
    "refine",
    "verify",
    "commit",
]


def test_mrp_baseline_files_exist() -> None:
    for relative_path in MRP_BASELINE_FILES:
        assert Path(relative_path).is_file(), f"missing mirrored MRP file: {relative_path}"


def test_mrp_baseline_files_are_syntax_valid() -> None:
    for relative_path in MRP_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")


def test_mrp_baseline_topology_is_exactly_the_upstream_module_family() -> None:
    expected = {Path(path).name for path in MRP_BASELINE_FILES}
    actual = {path.name for path in Path("cygnus/runtime/ai/mrp").glob("*.py")}

    assert actual == expected


def test_mrp_baseline_modules_import_and_expose_upstream_entrypoints() -> None:
    for module_name, symbols in MRP_BASELINE_MODULES.items():
        module = importlib.import_module(module_name)

        for symbol in symbols:
            value = getattr(module, symbol, None)
            assert value is not None, f"{module_name} missing upstream MRP symbol: {symbol}"
            assert inspect.isclass(value) or callable(value), (
                f"{module_name}.{symbol} should remain an importable MRP entrypoint"
            )


def test_mrp_pipeline_preserves_map_reduce_review_refine_verify_commit_markers() -> None:
    pipeline_source = Path("cygnus/runtime/ai/mrp/pipeline.py").read_text(encoding="utf-8")

    for marker in MRP_PIPELINE_PHASE_MARKERS:
        assert marker in pipeline_source, f"MRP pipeline lost phase marker: {marker}"

    assert "run_map_phase" in pipeline_source
    assert "run_reduce_phase" in pipeline_source
    assert "run_refine_phase" in pipeline_source
    assert "run_verify_phase" in pipeline_source
    assert "run_commit_phase" in pipeline_source
    assert "pipeline_phase" in pipeline_source


def test_mrp_baseline_has_no_legacy_app_namespace_imports() -> None:
    for relative_path in MRP_BASELINE_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")

        assert "from app." not in source
        assert "import app." not in source
        assert " app." not in source


def test_mrp_writer_uses_mirrored_upstream_prompt_helper() -> None:
    writer_source = Path("cygnus/runtime/ai/mrp/writer.py").read_text(encoding="utf-8")
    prompt_helper = Path("cygnus/runtime/ai/prompt_library.py")

    assert prompt_helper.is_file(), "MRP writer's upstream prompt helper must be mirrored"
    assert "build_wiki_writer_system_prompt" in writer_source
    assert "cygnus.runtime.ai.prompt_library" in writer_source
