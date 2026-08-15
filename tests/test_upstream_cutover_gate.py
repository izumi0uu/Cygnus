from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "upstream_cutover_gate.py"
    )
    spec = importlib.util.spec_from_file_location("upstream_cutover_gate", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


upstream_cutover_gate = _load_module()


class UpstreamCutoverGateTests(unittest.TestCase):
    def test_gate_passes_against_current_repo(self) -> None:
        failures = upstream_cutover_gate.collect_failures(
            Path(__file__).resolve().parents[1]
        )
        self.assertEqual(failures, [])

    def test_gate_report_exposes_structured_suite_sections(self) -> None:
        report = upstream_cutover_gate.build_gate_report(
            Path(__file__).resolve().parents[1]
        )

        self.assertTrue(report["ok"])
        sections = {section["name"]: section for section in report["sections"]}
        self.assertEqual(
            set(sections),
            {
                "code_residue_gate",
                "compat_shrink_gate",
                "owner_truth_gate",
                "dependency_internalization_gate",
                "executable_path_gate",
                "external_checkout_gate",
                "docs_truth_gate",
            },
        )
        self.assertTrue(sections["owner_truth_gate"]["ok"])
        self.assertTrue(sections["dependency_internalization_gate"]["ok"])
        self.assertTrue(sections["executable_path_gate"]["ok"])
        self.assertTrue(sections["external_checkout_gate"]["ok"])

    def test_gate_detects_forbidden_code_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cygnus/api").mkdir(parents=True)
            (root / "cygnus/api/__init__.py").write_text("", encoding="utf-8")
            (root / "cygnus/api/app.py").write_text("", encoding="utf-8")
            (root / "cygnus/runtime.py").write_text("import arkon\n", encoding="utf-8")

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.REQUIRED_DOC_SNIPPETS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            failures = upstream_cutover_gate.scan_forbidden_code_residue(root)
            self.assertTrue(
                any("forbidden upstream residue" in item for item in failures)
            )

    def test_gate_detects_reintroduced_legacy_api_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cygnus/api").mkdir(parents=True)
            (root / "cygnus/api/app.py").write_text("", encoding="utf-8")

            failures = upstream_cutover_gate.check_removed_legacy_api_package(root)
            self.assertTrue(any("removed legacy package" in item for item in failures))

    def test_gate_detects_missing_owner_truth_and_executable_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.REQUIRED_DOC_SNIPPETS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            report = upstream_cutover_gate.build_gate_report(root)
            sections = {section["name"]: section for section in report["sections"]}

            self.assertFalse(report["ok"])
            self.assertFalse(sections["owner_truth_gate"]["ok"])
            self.assertFalse(sections["executable_path_gate"]["ok"])
            self.assertTrue(
                any(
                    "missing owner-truth file" in item
                    for item in sections["owner_truth_gate"]["failures"]
                )
            )
            self.assertTrue(
                any(
                    "missing executable-path artifact" in item
                    for item in sections["executable_path_gate"]["failures"]
                )
            )

    def test_gate_detects_external_checkout_dependency_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.REQUIRED_DOC_SNIPPETS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.OWNER_TRUTH_FILES.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            for relative_path in upstream_cutover_gate.EXECUTABLE_PATH_FILES:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# executable artifact\n", encoding="utf-8")

            (root / "pyproject.toml").write_text(
                'arkon = { git = "https://github.com/nduckmink/arkon" }\n',
                encoding="utf-8",
            )
            (root / ".gitmodules").write_text('[submodule "arkon"]\n', encoding="utf-8")

            report = upstream_cutover_gate.build_gate_report(root)
            sections = {section["name"]: section for section in report["sections"]}

            self.assertFalse(sections["external_checkout_gate"]["ok"])
            self.assertTrue(
                any(
                    "forbidden external checkout reference" in item
                    for item in sections["external_checkout_gate"]["failures"]
                )
            )
            self.assertTrue(
                any(
                    ".gitmodules" in item
                    for item in sections["external_checkout_gate"]["failures"]
                )
            )

    def test_gate_detects_direct_dependency_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.REQUIRED_DOC_SNIPPETS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.OWNER_TRUTH_FILES.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            for relative_path in upstream_cutover_gate.EXECUTABLE_PATH_FILES:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# executable artifact\n", encoding="utf-8")

            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["content-core>=1.14.1,<2"]\n',
                encoding="utf-8",
            )
            (root / "uv.lock").write_text('name = "content-core"\n', encoding="utf-8")

            report = upstream_cutover_gate.build_gate_report(root)
            sections = {section["name"]: section for section in report["sections"]}

            self.assertFalse(sections["dependency_internalization_gate"]["ok"])
            self.assertTrue(
                any(
                    "direct dependency `content-core`" in item
                    for item in sections["dependency_internalization_gate"]["failures"]
                )
            )
            self.assertTrue(
                any(
                    "forbidden lockfile residue" in item
                    for item in sections["dependency_internalization_gate"]["failures"]
                )
            )

    def test_gate_detects_runtime_protocol_owner_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.REQUIRED_DOC_SNIPPETS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            for (
                relative_path,
                snippets,
            ) in upstream_cutover_gate.OWNER_TRUTH_FILES.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            for relative_path in upstream_cutover_gate.EXECUTABLE_PATH_FILES:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# executable artifact\n", encoding="utf-8")

            shim_path = root / upstream_cutover_gate.PROTOCOL_OWNER_SHIM
            shim_path.parent.mkdir(parents=True, exist_ok=True)
            shim_path.write_text(
                "from cygnus.substrate.agent_protocol import (\n    AssistantTurn,\n)\n",
                encoding="utf-8",
            )

            residue = root / "cygnus/runtime/ai/providers/base.py"
            residue.parent.mkdir(parents=True, exist_ok=True)
            residue.write_text(
                "from cygnus.runtime.ai.agent_protocol import AssistantTurn\n",
                encoding="utf-8",
            )

            report = upstream_cutover_gate.build_gate_report(root)
            sections = {section["name"]: section for section in report["sections"]}

            self.assertFalse(sections["owner_truth_gate"]["ok"])
            self.assertTrue(
                any(
                    "runtime protocol owner residue" in item
                    for item in sections["owner_truth_gate"]["failures"]
                )
            )


if __name__ == "__main__":
    unittest.main()
