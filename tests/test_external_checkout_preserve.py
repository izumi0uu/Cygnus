from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "external_checkout_preserve.py"
    spec = importlib.util.spec_from_file_location("external_checkout_preserve", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


external_checkout_preserve = _load_module()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def _git_ok(cwd: Path, *args: str) -> None:
    subprocess.check_call(["git", "-C", str(cwd), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ExternalCheckoutPreserveTests(unittest.TestCase):
    def _make_repo_with_ahead_history(self, root: Path) -> tuple[Path, str, str]:
        bare = root / "origin.git"
        subprocess.check_call(["git", "init", "--bare", str(bare)], stdout=subprocess.DEVNULL)

        seed = root / "seed"
        _git_ok(root, "clone", str(bare), str(seed))
        _git_ok(seed, "config", "user.name", "Cygnus Test")
        _git_ok(seed, "config", "user.email", "test@example.com")
        (seed / "README.md").write_text("base\n", encoding="utf-8")
        _git_ok(seed, "add", "README.md")
        _git_ok(seed, "commit", "-m", "base")
        _git_ok(seed, "branch", "-M", "main")
        _git_ok(seed, "push", "origin", "main")
        base = _git(seed, "rev-parse", "HEAD")

        repo = root / "arkon"
        _git_ok(root, "clone", str(bare), str(repo))
        _git_ok(repo, "config", "user.name", "Cygnus Test")
        _git_ok(repo, "config", "user.email", "test@example.com")
        _git_ok(repo, "checkout", "main")
        (repo / "feature.txt").write_text("one\n", encoding="utf-8")
        _git_ok(repo, "add", "feature.txt")
        _git_ok(repo, "commit", "-m", "feat: local ahead")
        head = _git(repo, "rev-parse", "HEAD")
        return repo, base, head

    def test_create_preservation_artifacts_writes_manifest_bundle_and_patches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base, head = self._make_repo_with_ahead_history(root)
            out = root / "artifacts"

            artifact = external_checkout_preserve.create_preservation_artifacts(repo, out)

            self.assertEqual(artifact.base_commit, base)
            self.assertEqual(artifact.head_commit, head)
            self.assertEqual(len(artifact.ahead_commits), 1)
            self.assertTrue(Path(artifact.manifest_path).is_file())
            self.assertTrue(Path(artifact.delta_bundle_path).is_file())
            self.assertTrue(Path(artifact.full_bundle_path).is_file())
            self.assertEqual(len(list(Path(artifact.patches_dir).glob("*.patch"))), 1)

    def test_verify_delta_bundle_restores_original_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _base, head = self._make_repo_with_ahead_history(root)
            out = root / "artifacts"
            artifact = external_checkout_preserve.create_preservation_artifacts(repo, out)

            verification = external_checkout_preserve.verify_delta_bundle(repo, artifact, cleanup=False)
            assert verification is not None
            self.assertEqual(verification.original_head, head)
            self.assertEqual(verification.restored_head, head)
            self.assertEqual(verification.restored_subjects, ["feat: local ahead"])
            self.assertEqual(verification.expected_subjects, ["feat: local ahead"])
            self.assertTrue(verification.head_matches_original)
            self.assertTrue(verification.subjects_match_expected)
            self.assertTrue(Path(verification.restore_dir).exists())

    def test_verify_patch_series_replays_subjects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _base, head = self._make_repo_with_ahead_history(root)
            out = root / "artifacts"
            artifact = external_checkout_preserve.create_preservation_artifacts(repo, out)

            verification = external_checkout_preserve.verify_patch_series(repo, artifact, cleanup=False)
            assert verification is not None
            self.assertEqual(verification.original_head, head)
            self.assertEqual(verification.restored_subjects, ["feat: local ahead"])
            self.assertEqual(verification.expected_subjects, ["feat: local ahead"])
            self.assertFalse(verification.head_matches_original)
            self.assertTrue(verification.subjects_match_expected)
            self.assertTrue(Path(verification.restore_dir).exists())


if __name__ == "__main__":
    unittest.main()
