from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "upstream_cutover_gate.py"
    spec = importlib.util.spec_from_file_location("upstream_cutover_gate", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


upstream_cutover_gate = _load_module()


class UpstreamCutoverGateTests(unittest.TestCase):
    def test_gate_passes_against_current_repo(self) -> None:
        failures = upstream_cutover_gate.collect_failures(Path(__file__).resolve().parents[1])
        self.assertEqual(failures, [])

    def test_gate_detects_forbidden_code_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cygnus/api").mkdir(parents=True)
            (root / "cygnus/api/__init__.py").write_text("", encoding="utf-8")
            (root / "cygnus/api/app.py").write_text("", encoding="utf-8")
            (root / "cygnus/runtime.py").write_text("import arkon\n", encoding="utf-8")

            for relative_path, snippets in upstream_cutover_gate.REQUIRED_DOC_SNIPPETS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(snippets), encoding="utf-8")

            failures = upstream_cutover_gate.scan_forbidden_code_residue(root)
            self.assertTrue(any("forbidden upstream residue" in item for item in failures))

    def test_gate_detects_reintroduced_legacy_api_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cygnus/api").mkdir(parents=True)
            (root / "cygnus/api/app.py").write_text("", encoding="utf-8")

            failures = upstream_cutover_gate.check_removed_legacy_api_package(root)
            self.assertTrue(any("removed legacy package" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
