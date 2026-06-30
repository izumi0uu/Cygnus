from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "external_checkout_audit.py"
    spec = importlib.util.spec_from_file_location("external_checkout_audit", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


external_checkout_audit = _load_module()


class ExternalCheckoutAuditTests(unittest.TestCase):
    def test_audit_finds_upstream_arkon_repo_by_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "arkon"
            git_dir = repo / ".git"
            git_dir.mkdir(parents=True)
            (git_dir / "config").write_text(
                '[remote "origin"]\n\turl = https://github.com/nduckmink/arkon.git\n',
                encoding="utf-8",
            )

            payload = external_checkout_audit.audit_external_checkouts([root], max_depth=2)

            self.assertEqual(payload["checkout_count"], 1)
            self.assertTrue(payload["checkouts"][0]["is_upstream_origin"])
            self.assertTrue(payload["checkouts"][0]["contains_arkon_name"])

    def test_audit_ignores_unrelated_repo_without_name_or_origin_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "support-brain"
            git_dir = repo / ".git"
            git_dir.mkdir(parents=True)
            (git_dir / "config").write_text(
                '[remote "origin"]\n\turl = git@github.com:izumi0uu/Cygnus.git\n',
                encoding="utf-8",
            )

            payload = external_checkout_audit.audit_external_checkouts([root], max_depth=2)

            self.assertEqual(payload["checkout_count"], 0)


if __name__ == "__main__":
    unittest.main()
