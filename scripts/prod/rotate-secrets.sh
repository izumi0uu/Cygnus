#!/usr/bin/env bash
# Rotate externally stored Production V1 secret material, then redeploy the
# same immutable release. Secret values never appear in arguments or this repo.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

RELEASE=${CYGNUS_RELEASE:-}
DRY_RUN=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --release) RELEASE=${2:?--release requires a version}; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) die "usage: scripts/prod/rotate-secrets.sh --release <version> [--dry-run]" ;;
  esac
done
load_prod_env
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
for variable in CYGNUS_SECRET_ROTATION_RUNNER CYGNUS_SECRET_ROTATION_APPROVAL_REF; do
  [ -n "${!variable:-}" ] && ! is_placeholder "${!variable}" || die "$variable must be a non-placeholder external input"
done
[ -x "$CYGNUS_SECRET_ROTATION_RUNNER" ] || die "CYGNUS_SECRET_ROTATION_RUNNER must name an executable protected-runner command"
if [ "$DRY_RUN" = 1 ]; then
  "$CYGNUS_SECRET_ROTATION_RUNNER" --release "$RELEASE" --environment-file "$PROD_ENV_FILE" --approval-ref "$CYGNUS_SECRET_ROTATION_APPROVAL_REF" --dry-run
  log "secret rotation dry run passed; no secret or container changed"
  exit 0
fi
"$CYGNUS_SECRET_ROTATION_RUNNER" --release "$RELEASE" --environment-file "$PROD_ENV_FILE" --approval-ref "$CYGNUS_SECRET_ROTATION_APPROVAL_REF"
exec "$SCRIPT_DIR/deploy.sh" --release "$RELEASE"
