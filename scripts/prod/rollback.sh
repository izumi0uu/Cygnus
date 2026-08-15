#!/usr/bin/env bash
# Cygnus production rollback. Application image rollback is explicit; schema
# rollback is never implicit and must use the target image plus an explicit
# Alembic revision. The normal readiness gate rejects an incompatible schema.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"
ORIGINAL_ARGS=("$@")
FAILED_RELEASE="${CYGNUS_FAILED_RELEASE:-}"

RELEASE="${CYGNUS_RELEASE:-}"
DOWNGRADE_REV=""
YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE="${2:?--release requires a version}"; shift 2 ;;
    --downgrade) DOWNGRADE_REV="${2:?--downgrade requires an Alembic revision}"; shift 2 ;;
    --yes) YES=1; shift ;;
    *) die "unknown argument: $1 (usage: scripts/prod/rollback.sh [--release <version>] [--downgrade <revision>] [--yes])" ;;
  esac
done

load_prod_env
load_state
[ -n "$RELEASE" ] || RELEASE="${CYGNUS_PREVIOUS_RELEASE:-}"
[ -n "$RELEASE" ] || die "no previous release is recorded; pass --release <approved-version>"
if [ -n "$CHECKOUTS_DIR" ]; then
  TARGET_CHECKOUT="$CHECKOUTS_DIR/$RELEASE"
  [ -x "$TARGET_CHECKOUT/scripts/prod/rollback.sh" ] || die "rollback checkout is missing or not executable: $TARGET_CHECKOUT"
  CURRENT_ROOT=$(CDPATH= cd -- "$REPO_ROOT" && pwd -P)
  TARGET_ROOT=$(CDPATH= cd -- "$TARGET_CHECKOUT" && pwd -P)
  if [ "$CURRENT_ROOT" != "$TARGET_ROOT" ]; then
    exec "$TARGET_CHECKOUT/scripts/prod/rollback.sh" "${ORIGINAL_ARGS[@]}"
  fi
fi
unset CYGNUS_RELEASE_METADATA_FILE CYGNUS_RELEASE_INPUTS_FILE CYGNUS_PRODUCTION_INPUTS_FILE APP_RELEASE APP_COMMIT_SHA APP_DEPLOYMENT_ID EXPECTED_ALEMBIC_HEAD CYGNUS_API_IMAGE CYGNUS_FRONTEND_IMAGE
if [ "$RELEASE" = "${CYGNUS_ACTIVE_RELEASE:-}" ] && [ -z "$FAILED_RELEASE" ]; then
  die "release $RELEASE is already active"
fi
if [ -n "$FAILED_RELEASE" ]; then
  validate_release_identifier "$FAILED_RELEASE"
fi
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
validate_operator_state_paths "$RELEASE"
validate_compose

log "rollback target: $RELEASE"
log "api:       $CYGNUS_API_IMAGE"
log "frontend:  $CYGNUS_FRONTEND_IMAGE"
if [ "$YES" != 1 ]; then
  printf '[cygnus-prod] continue with rollback to %s? [y/N] ' "$RELEASE"
  read -r answer
  case "$answer" in y|Y) ;; *) die "aborted" ;; esac
fi
log "gracefully quiescing current API and workers before rollback mutation..."
arm_backend_recovery_trap
compose_quiesce_backend

if [ -n "$DOWNGRADE_REV" ]; then
  log "running explicit target-image Alembic downgrade to $DOWNGRADE_REV..."
  "${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"
fi

log "recreating backend from target digests..."
compose_up_backend
clear_backend_recovery_trap
log "recreating TLS reverse proxy from the target digest..."
compose_up_frontend
verify_ingress "$CYGNUS_DOMAIN"
activate_release_checkout "$RELEASE"
if [ -z "$FAILED_RELEASE" ]; then
  save_state "${CYGNUS_ACTIVE_RELEASE:-}" "$RELEASE"
else
  log "failed release $FAILED_RELEASE was removed from service; deployment state remains on $RELEASE"
fi
log "rollback complete: $RELEASE is ready"
