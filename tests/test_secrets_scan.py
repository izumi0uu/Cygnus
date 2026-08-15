from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "secrets_scan.py"
    spec = importlib.util.spec_from_file_location("secrets_scan", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["secrets_scan"] = module
    spec.loader.exec_module(module)
    return module


secrets_scan = _load_module()


class SecretsScanTests(unittest.TestCase):
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

    def test_flags_aws_access_key(self) -> None:
        self._write("config.py", "key = 'AKIA' + 'IOSFODNN7EXAMPLE'\n")
        findings = secrets_scan.scan_paths(list(self.root.rglob("*")), root=self.root)
        self.assertTrue(any(f.pattern == "aws_access_key_id" for f in findings))

    def test_flags_private_key_block(self) -> None:
        self._write(
            "certs/legacy.pem",
            "-----BEGIN "
            + "PRIVATE KEY-----\nMIIBVAIBADANBgkqhkiG9w0BAQEFAASC\n-----END "
            + "PRIVATE KEY-----\n",
        )
        findings = secrets_scan.scan_paths(list(self.root.rglob("*")), root=self.root)
        self.assertTrue(any(f.pattern == "private_key" for f in findings))

    def test_ignores_explicit_ignore_path(self) -> None:
        self._write(
            "fixtures/aws.env", "AWS_ACCESS_KEY=" + "AKIA" + "IOSFODNN7EXAMPLE\n"
        )
        findings = secrets_scan.scan_paths(
            list(self.root.rglob("*")), root=self.root, ignored=frozenset({"fixtures"})
        )
        self.assertEqual(findings, [])

    def test_skips_binary_files(self) -> None:
        path = self._write("blob.bin", "AKIA" + "IOSFODNN7EXAMPLE")
        path.write_bytes(b"\x00\x01\x02" + b"AKIA" + b"IOSFODNN7EXAMPLE" + b"\x00")
        findings = secrets_scan.scan_paths(list(self.root.rglob("*")), root=self.root)
        self.assertEqual(findings, [])

    def test_clean_directory_passes(self) -> None:
        self._write("main.py", "print('no secrets here')\n")
        self._write("README.txt", "documentation only\n")
        findings = secrets_scan.scan_paths(list(self.root.rglob("*")), root=self.root)
        self.assertEqual(findings, [])

    def test_redaction_hides_match_body(self) -> None:
        self._write("x.txt", "AKIA" + "IOSFODNN7EXAMPLE\n")
        findings = secrets_scan.scan_paths(list(self.root.rglob("*")), root=self.root)
        self.assertEqual(len(findings), 1)
        self.assertNotIn("IOSFODNN7", findings[0].snippet)


if __name__ == "__main__":
    unittest.main()
