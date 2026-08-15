from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "dependency_gate.py"
    spec = importlib.util.spec_from_file_location("dependency_gate", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["dependency_gate"] = module
    spec.loader.exec_module(module)
    return module


dependency_gate = _load_module()


class DependencyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_offline_checks_pass_for_locked_graph(self) -> None:
        self._write(
            "pyproject.toml",
            '[project]\nname = "demo"\ndependencies = ["fastapi>=0.100"]\n'
            '[project.optional-dependencies]\ndev = ["pytest>=8"]\n',
        )
        self._write(
            "uv.lock",
            "version = 1\n"
            '[[package]]\nname = "demo"\nversion = "0.1.0"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            'wheels = [{ url = "https://example.invalid/demo.whl", hash = "sha256:'
            + "a"
            * 64
            + '", size = 1 }]\n'
            '[[package]]\nname = "fastapi"\nversion = "0.115.0"\n'
            'wheels = [{ url = "https://example.invalid/f.whl", hash = "sha256:'
            + "b"
            * 64
            + '", size = 1 }]\n'
            '[[package]]\nname = "pytest"\nversion = "8.3.0"\n'
            'wheels = [{ url = "https://example.invalid/p.whl", hash = "sha256:'
            + "c" * 64
            + '", size = 1 }]\n',
        )
        result = dependency_gate.offline_checks(self.root)
        self.assertTrue(result["ok"], result["failures"])

    def test_offline_checks_fail_when_dependency_missing_from_lock(self) -> None:
        self._write(
            "pyproject.toml",
            '[project]\nname = "demo"\ndependencies = ["missing-pkg>=1"]\n',
        )
        self._write(
            "uv.lock",
            "version = 1\n"
            '[[package]]\nname = "demo"\nversion = "0.1.0"\n'
            'wheels = [{ url = "https://example.invalid/d.whl", hash = "sha256:'
            + "d" * 64
            + '", size = 1 }]\n',
        )
        result = dependency_gate.offline_checks(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("missing-pkg" in failure for failure in result["failures"]))

    def test_offline_checks_fail_on_unhashed_package(self) -> None:
        self._write(
            "pyproject.toml",
            '[project]\nname = "demo"\ndependencies = ["unpinned"]\n',
        )
        self._write(
            "uv.lock",
            "version = 1\n"
            '[[package]]\nname = "demo"\nversion = "0.1.0"\n'
            'wheels = [{ url = "https://example.invalid/d.whl", hash = "sha256:'
            + "d"
            * 64
            + '", size = 1 }]\n'
            '[[package]]\nname = "unpinned"\nversion = "0.0.1"\n'
            'wheels = [{ url = "https://example.invalid/u.whl" }]\n',
        )
        result = dependency_gate.offline_checks(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("no sha256 hash" in failure for failure in result["failures"])
        )

    def test_offline_checks_fail_when_lock_missing(self) -> None:
        self._write("pyproject.toml", '[project]\nname = "demo"\n')
        result = dependency_gate.offline_checks(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("uv.lock is missing" in failure for failure in result["failures"])
        )

    def test_risk_acceptances_load(self) -> None:
        path = self._write(
            "acceptances.json",
            json.dumps(
                {
                    "acceptances": [
                        {"package": "Demo", "version": "1.0", "advisory": "GHSA-123"}
                    ]
                }
            ),
        )
        accepted = dependency_gate._load_risk_acceptances(path)
        self.assertEqual(accepted, {"demo@1.0:GHSA-123"})

    def test_filter_unaccepted_respects_pip_audit_schema(self) -> None:
        dependencies = [
            {
                "name": "demo",
                "version": "1.0",
                "vulns": [
                    {"id": "GHSA-123", "description": "accepted"},
                    {"id": "GHSA-999", "description": "unaccepted"},
                ],
            }
        ]
        accepted = {"demo@1.0:GHSA-123"}
        unaccepted = dependency_gate.filter_unaccepted(dependencies, accepted)
        self.assertEqual([item["advisory"] for item in unaccepted], ["GHSA-999"])

    def test_filter_unaccepted_accepts_everything_when_covered(self) -> None:
        dependencies = [
            {
                "name": "demo",
                "version": "1.0",
                "vulns": [{"id": "GHSA-123"}],
            }
        ]
        accepted = {"demo@1.0:GHSA-123"}
        self.assertEqual(dependency_gate.filter_unaccepted(dependencies, accepted), [])


if __name__ == "__main__":
    unittest.main()
