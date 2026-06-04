#!/usr/bin/env sh
set -eu

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi

echo "[repo-check] Python syntax"
"$PYTHON_BIN" -m py_compile scripts/repo_guard.py scripts/diff_coverage_gate.py

echo "[repo-check] Unit tests"
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py' -v

echo "[repo-check] Shell syntax"
sh -n scripts/install_git_hooks.sh
sh -n scripts/repo_check.sh
sh -n .githooks/commit-msg
sh -n .githooks/pre-push
