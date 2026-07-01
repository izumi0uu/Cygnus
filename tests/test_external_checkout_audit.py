from __future__ import annotations

import importlib.util
import subprocess
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
    def _git_ok(self, cwd: Path, *args: str) -> None:
        subprocess.check_call(["git", "-C", str(cwd), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _git(self, cwd: Path, *args: str) -> str:
        return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()

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

    def test_audit_reports_preservation_need_for_ahead_and_dirty_external_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare = root / "origin.git"
            subprocess.check_call(["git", "init", "--bare", str(bare)], stdout=subprocess.DEVNULL)

            seed = root / "seed"
            self._git_ok(root, "clone", str(bare), str(seed))
            self._git_ok(seed, "config", "user.name", "Cygnus Test")
            self._git_ok(seed, "config", "user.email", "test@example.com")
            (seed / "README.md").write_text("base\n", encoding="utf-8")
            self._git_ok(seed, "add", "README.md")
            self._git_ok(seed, "commit", "-m", "base")
            self._git_ok(seed, "branch", "-M", "main")
            self._git_ok(seed, "push", "origin", "main")

            repo = root / "arkon"
            self._git_ok(root, "clone", str(bare), str(repo))
            self._git_ok(repo, "config", "user.name", "Cygnus Test")
            self._git_ok(repo, "config", "user.email", "test@example.com")
            self._git_ok(repo, "checkout", "main")
            (repo / "feature.txt").write_text("ahead\n", encoding="utf-8")
            self._git_ok(repo, "add", "feature.txt")
            self._git_ok(repo, "commit", "-m", "feat: local ahead")
            (repo / "feature.txt").write_text("ahead\ndirty\n", encoding="utf-8")
            (repo / "notes.txt").write_text("scratch\n", encoding="utf-8")

            payload = external_checkout_audit.audit_external_checkouts([root], max_depth=2, base_ref="origin/main")

            self.assertEqual(payload["checkout_count"], 1)
            self.assertEqual(payload["requires_preservation_count"], 1)
            item = payload["checkouts"][0]
            self.assertEqual(item["branch"], "main")
            self.assertEqual(item["ahead_commit_count"], 1)
            self.assertTrue(item["requires_preservation"])
            self.assertTrue(item["physical_delete_blocked"])
            self.assertIn("dirty tracked worktree changes", item["preservation_reasons"])
            self.assertIn("1 ahead commit(s)", item["preservation_reasons"])
            self.assertIn("1 untracked file(s)", item["preservation_reasons"])
            self.assertIn("notes.txt", item["untracked_files"])
            self.assertTrue(any(line.startswith(" M feature.txt") for line in item["status_lines"]))
            self.assertEqual(item["head_commit"], self._git(repo, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
