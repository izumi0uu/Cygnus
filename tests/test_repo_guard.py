from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "repo_guard.py"
    spec = importlib.util.spec_from_file_location("repo_guard", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repo_guard = _load_module()


class RepoGuardTests(unittest.TestCase):
    def test_accepts_valid_conventional_commit_with_lore_trailers(self) -> None:
        text = (
            "feat(repo-guard): enforce conventional subject shapes\n\n"
            "Confidence: high\n"
            "Scope-risk: narrow\n"
            "Tested: python -m unittest discover -s tests -p 'test_*.py' -v\n"
        )
        self.assertEqual(repo_guard.validate_commit_text(text, "sample"), [])

    def test_rejects_non_conventional_commit_subject(self) -> None:
        text = (
            "Protect review quality before repo code starts scaling\n\n"
            "Confidence: high\n"
            "Scope-risk: narrow\n"
            "Tested: manual\n"
        )
        errors = repo_guard.validate_commit_text(text, "sample")
        self.assertTrue(any("type(scope): summary" in error for error in errors))

    def test_accepts_valid_pr_shape(self) -> None:
        body = """## Summary
- Adds a repo-native validation system.

## Problem
- The repository needs consistent review structure.

## Solution
- Add PR, commit, and repo-quality checks.

## Validation
- [x] Relevant local checks ran
- [x] New or changed behavior was tested
- [x] Risk / rollback impact was reviewed
- [x] Follow-up work is documented, or N/A with reason

## Risks
- N/A: repo-only validation change.

## Related
- N/A: no tracker yet.
"""
        with patch.dict(
            os.environ,
            {
                "PR_TITLE": "fix(repo-guard): enforce conventional PR titles",
                "PR_BODY": body,
                "PR_BRANCH": "fix/repo-guard",
            },
            clear=False,
        ):
            self.assertEqual(repo_guard.validate_pr(), 0)

    def test_rejects_empty_required_pr_sections(self) -> None:
        body = """## Summary

## Problem

"""
        with patch.dict(
            os.environ,
            {
                "PR_TITLE": "fix(repo-guard): enforce conventional PR titles",
                "PR_BODY": body,
                "PR_BRANCH": "fix/repo-guard",
            },
            clear=False,
        ):
            self.assertEqual(repo_guard.validate_pr(), 1)


if __name__ == "__main__":
    unittest.main()
