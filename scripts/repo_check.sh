#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

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
"$PYTHON_BIN" -m py_compile cygnus/observability/alert_rules.py scripts/repo_guard.py scripts/diff_coverage_gate.py scripts/upstream_cutover_gate.py scripts/arkon_replacement_inventory.py scripts/governance_golden_path_gate.py scripts/domain_eval_gate.py scripts/external_checkout_audit.py scripts/external_checkout_preserve.py scripts/secrets_scan.py scripts/dependency_gate.py scripts/migration_gate.py scripts/image_gate.py scripts/image_reference_gate.py scripts/release_contract_gate.py scripts/release_gate.py scripts/write_evidence.py scripts/write_image_manifest.py scripts/production_inputs_gate.py scripts/render_alert_rules.py scripts/production_delivery_config_gate.py scripts/production_network_config_gate.py scripts/live_certification_report_gate.py scripts/create_isolated_minio_bucket.py

echo "[repo-check] Upstream cutover gate"
"$PYTHON_BIN" scripts/upstream_cutover_gate.py --quiet

echo "[repo-check] Governance golden path gate"
"$PYTHON_BIN" scripts/governance_golden_path_gate.py --quiet
echo "[repo-check] Production domain evaluation gate"
"$PYTHON_BIN" scripts/domain_eval_gate.py --quiet

echo "[repo-check] Secrets scan (release gate, offline)"
"$PYTHON_BIN" scripts/secrets_scan.py --quiet

echo "[repo-check] Dependency gate (offline lock integrity)"
"$PYTHON_BIN" scripts/dependency_gate.py --quiet

echo "[repo-check] Migration gate (static reversibility)"
"$PYTHON_BIN" scripts/migration_gate.py --quiet

echo "[repo-check] Static release contract gate"
"$PYTHON_BIN" scripts/release_contract_gate.py --quiet

echo "[repo-check] Unit tests"
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py' -v

echo "[repo-check] Shell syntax"
sh -n scripts/install_git_hooks.sh
sh -n scripts/docker_smoke.sh
sh -n scripts/repo_check.sh
sh -n .githooks/commit-msg
bash -n scripts/prod/lib.sh
bash -n scripts/prod/deploy.sh
bash -n scripts/prod/rollback.sh
bash -n scripts/prod/backup_restore_drill.sh
bash -n scripts/run_live_production_certification.sh
bash -n scripts/prod/rotate-secrets.sh
bash -n scripts/prod/incident.sh
sh -n .githooks/pre-push
