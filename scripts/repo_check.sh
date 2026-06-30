#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/.venv-runability/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv-runability/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi

echo "[repo-check] Python syntax"
"$PYTHON_BIN" -m py_compile scripts/repo_guard.py scripts/diff_coverage_gate.py scripts/upstream_cutover_gate.py scripts/arkon_replacement_inventory.py scripts/governance_golden_path_gate.py

echo "[repo-check] Upstream cutover gate"
"$PYTHON_BIN" scripts/upstream_cutover_gate.py --quiet

echo "[repo-check] Governance golden path gate"
"$PYTHON_BIN" scripts/governance_golden_path_gate.py --quiet

echo "[repo-check] Unit tests"
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py' -v

echo "[repo-check] Shell syntax"
sh -n scripts/install_git_hooks.sh
sh -n scripts/repo_check.sh
sh -n .githooks/commit-msg
sh -n .githooks/pre-push
