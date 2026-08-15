#!/usr/bin/env bash
# Run Production V1 live certification on a deliberately labelled self-hosted
# runner. Targets, credentials, release identity, and non-browser probes remain
# operator-supplied; the browser probe has a locked repository-owned default.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ARTIFACT_DIR=${CYGNUS_CERTIFICATION_ARTIFACT_DIR:-"$REPO_ROOT/production/evidence"}
CYGNUS_BROWSER_E2E_RUNNER=${CYGNUS_BROWSER_E2E_RUNNER:-"$REPO_ROOT/frontend/scripts/run-browser-certification.mjs"}
export CYGNUS_BROWSER_E2E_RUNNER

require() {
  local name=$1
  [ -n "${!name:-}" ] || { printf '[live-certification] ERROR: %s is required\n' "$name" >&2; exit 1; }
}
sha256_file() { python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"; }
record() {
  local name=$1 report=$2
  python3 "$REPO_ROOT/scripts/write_evidence.py" "$name" --passed \
    --git-sha "$APP_COMMIT_SHA" --tool "self-hosted-production-certification" \
    --check "report_sha256=$(sha256_file "$report")" --out "$ARTIFACT_DIR/$name.json"
}
run_external() {
  local name=$1 executable=$2 report=$3
  [ -x "$executable" ] || { printf '[live-certification] ERROR: %s runner is not executable: %s\n' "$name" "$executable" >&2; exit 1; }
  "$executable" --report "$report" --git-sha "$APP_COMMIT_SHA" \
    --backend-image "$CYGNUS_API_IMAGE" --frontend-image "$CYGNUS_FRONTEND_IMAGE" \
    --alembic-head "$EXPECTED_ALEMBIC_HEAD"
  python3 "$REPO_ROOT/scripts/live_certification_report_gate.py" --name "$name" \
    --report "$report" --git-sha "$APP_COMMIT_SHA" \
    --backend-image "$CYGNUS_API_IMAGE" --frontend-image "$CYGNUS_FRONTEND_IMAGE" \
    --alembic-head "$EXPECTED_ALEMBIC_HEAD" --out "$ARTIFACT_DIR/$name.json"
}

for variable in CYGNUS_RELEASE CYGNUS_PRODUCTION_ENV_FILE CYGNUS_RELEASE_METADATA_FILE CYGNUS_EXPECTED_GIT_SHA CYGNUS_EXPECTED_BACKEND_IMAGE CYGNUS_EXPECTED_FRONTEND_IMAGE CYGNUS_EXPECTED_ALEMBIC_HEAD CYGNUS_PRODUCTION_E2E_RUNNER CYGNUS_BROWSER_E2E_RUNNER CYGNUS_SECURITY_FAILURE_INJECTION_RUNNER CYGNUS_PERSISTED_DOMAIN_EVAL_RUNNER; do
  require "$variable"
done
mkdir -p "$ARTIFACT_DIR"

# Loading is data-only; lib.sh rejects template/default secrets, malformed
# nginx inputs, unapproved capacity identities, and release/image mismatches.
# shellcheck source=prod/lib.sh
source "$REPO_ROOT/scripts/prod/lib.sh"
[ -r "$CYGNUS_PRODUCTION_ENV_FILE" ] || die "CYGNUS_PRODUCTION_ENV_FILE must be an external readable dotenv file"
[ -r "$CYGNUS_RELEASE_METADATA_FILE" ] || die "CYGNUS_RELEASE_METADATA_FILE must be an external readable release metadata file"
validate_release_identifier "$CYGNUS_RELEASE"
load_prod_env
load_env_file "$CYGNUS_RELEASE_METADATA_FILE"
validate_digests "$CYGNUS_RELEASE"
validate_identity "$CYGNUS_RELEASE"
[ "$APP_COMMIT_SHA" = "$CYGNUS_EXPECTED_GIT_SHA" ] || die "release metadata APP_COMMIT_SHA does not match the CI candidate"
[ "$CYGNUS_API_IMAGE" = "$CYGNUS_EXPECTED_BACKEND_IMAGE" ] || die "release metadata backend digest does not match the CI candidate"
[ "$CYGNUS_FRONTEND_IMAGE" = "$CYGNUS_EXPECTED_FRONTEND_IMAGE" ] || die "release metadata frontend digest does not match the CI candidate"
[ "$EXPECTED_ALEMBIC_HEAD" = "$CYGNUS_EXPECTED_ALEMBIC_HEAD" ] || die "release metadata Alembic head does not match the CI candidate"
validate_secrets
validate_resources
validate_production_inputs "$CYGNUS_RELEASE"
inputs_report="$PRODUCTION_INPUTS_REPORT_FILE"
[ -s "$inputs_report" ] || die "production input gate did not write a report"
cp "$inputs_report" "$ARTIFACT_DIR/cygnus.production-inputs.json"
record production-inputs "$ARTIFACT_DIR/cygnus.production-inputs.json"
cp "$CYGNUS_PRODUCTION_INPUTS_FILE" "$ARTIFACT_DIR/cygnus.production-inputs.bound.json"
if [ -n "${CYGNUS_CERTIFICATION_TARGET_ORIGIN:-}" ]; then
  python3 - "$CYGNUS_CERTIFICATION_TARGET_ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
if url.scheme != "https" or not url.netloc or url.path not in ("", "/") or url.query or url.fragment:
    raise SystemExit("CYGNUS_CERTIFICATION_TARGET_ORIGIN must be an HTTPS origin")
PY
  export ENVIRONMENT=staging
  export CYGNUS_BROWSER_BASE_URL="$CYGNUS_CERTIFICATION_TARGET_ORIGIN"
  export PORTAL_BASE_URL="$CYGNUS_CERTIFICATION_TARGET_ORIGIN"
  export CORS_ORIGINS="$CYGNUS_CERTIFICATION_TARGET_ORIGIN"
fi
# Seed and verify the durable candidate lifecycle before route-specific load.
# The capacity adapter reads this persisted receipt; it never invents fixtures.
run_external production-e2e "$CYGNUS_PRODUCTION_E2E_RUNNER" "$ARTIFACT_DIR/cygnus.production-e2e.json"

# A native staging load report is required; the gate refuses missing thresholds,
# targets, runtime identity, or fault injection and exits nonzero on every
# non-PASS result. The report binds the exact backend manifest digest.
export CYGNUS_CAPACITY_GATE_INJECTION=1
export APP_IMAGE_REF="$CYGNUS_API_IMAGE"
export GIT_SHA="$APP_COMMIT_SHA"
uv run python "$REPO_ROOT/scripts/load_gate.py" \
  --thresholds "$CYGNUS_CAPACITY_THRESHOLDS_FILE" \
  --targets "$CYGNUS_CAPACITY_TARGETS_FILE" \
  --commit-sha "$APP_COMMIT_SHA" \
  --image-tag "$CYGNUS_API_IMAGE" \
  --alembic-revision "$EXPECTED_ALEMBIC_HEAD" \
  --capacity-approval-ref "$CYGNUS_CAPACITY_APPROVAL_REF" \
  --capacity-thresholds-ref "$CYGNUS_CAPACITY_THRESHOLDS_REF" \
  --capacity-targets-ref "$CYGNUS_CAPACITY_TARGETS_REF" \
  --environment staging --require-runtime-identity \
  --report-out "$ARTIFACT_DIR/cygnus.capacity.report.json" \
  --samples-out "$ARTIFACT_DIR/cygnus.capacity.samples.json"
[ -s "$ARTIFACT_DIR/cygnus.capacity.report.json" ] || die "capacity gate did not write its native report"
[ -s "$ARTIFACT_DIR/cygnus.capacity.samples.json" ] || die "capacity gate did not write recorded samples"
python3 "$REPO_ROOT/scripts/write_evidence.py" capacity-gate --passed \
  --git-sha "$APP_COMMIT_SHA" --tool "scripts/load_gate.py" \
  --check "report_sha256=$(sha256_file "$ARTIFACT_DIR/cygnus.capacity.report.json")" \
  --check "samples_sha256=$(sha256_file "$ARTIFACT_DIR/cygnus.capacity.samples.json")" \
  --out "$ARTIFACT_DIR/capacity-gate.json"

# Every probe exercises the real target and emits the native report contract.
# The browser probe defaults to the locked repository runner above; operators
# may supply a separately approved executable. Missing probes never degrade to
# unit tests or synthetic success records.
run_external browser-e2e "$CYGNUS_BROWSER_E2E_RUNNER" "$ARTIFACT_DIR/cygnus.browser-e2e.json"
run_external security-failure-injection "$CYGNUS_SECURITY_FAILURE_INJECTION_RUNNER" "$ARTIFACT_DIR/cygnus.security-failure-injection.json"
run_external persisted-domain-eval "$CYGNUS_PERSISTED_DOMAIN_EVAL_RUNNER" "$ARTIFACT_DIR/cygnus.persisted-domain-eval.json"

printf '[live-certification] native production evidence written to %s\n' "$ARTIFACT_DIR"
