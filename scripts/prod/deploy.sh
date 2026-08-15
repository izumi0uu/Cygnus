#!/usr/bin/env bash
# Cygnus production deploy/upgrade. This is the only supported mutation path.
# It refuses unpinned images, unapproved production inputs, stale/missing TLS,
# missing resource budgets, and any attempt to skip the current-image migration.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

RELEASE="${CYGNUS_RELEASE:-}"
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE="${2:?--release requires a version}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) die "unknown argument: $1 (usage: scripts/prod/deploy.sh --release <version> [--dry-run])" ;;
  esac
done

load_prod_env
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
validate_operator_state_paths "$RELEASE"
validate_compose

PREVIOUS=""
if [ -f "$STATE_FILE" ]; then
  load_state
  PREVIOUS="${CYGNUS_ACTIVE_RELEASE:-}"
fi
if [ -n "$PREVIOUS" ]; then
  validate_release_identifier "$PREVIOUS"
  [ -f "$RELEASES_DIR/$PREVIOUS.env" ] || die "previous release metadata is missing: $RELEASES_DIR/$PREVIOUS.env"
  [ -x "$CHECKOUTS_DIR/$PREVIOUS/scripts/prod/rollback.sh" ] || die "previous release checkout cannot perform recovery: $CHECKOUTS_DIR/$PREVIOUS"
fi

recover_failed_rollout() {
  local status="${1:-1}"
  trap - EXIT
  if [ "$status" -ne 0 ] && [ -n "$PREVIOUS" ]; then
    log "candidate rollout failed; restoring active release $PREVIOUS with its exact schema head..."
    if ! CYGNUS_FAILED_RELEASE="$RELEASE" CYGNUS_ROLLBACK_SOURCE_METADATA_FILE="$LOADED_RELEASE_FILE" CYGNUS_ROLLBACK_SOURCE_INPUTS_FILE="$LOADED_RELEASE_INPUTS_FILE" "$SCRIPT_DIR/rollback.sh" --release "$PREVIOUS" --downgrade target --yes; then
      printf '[cygnus-prod] ERROR: automatic application/schema rollback failed; manual intervention is required\n' >&2
    fi
  fi
  exit "$status"
}

log "release:   $RELEASE"
log "api:       $CYGNUS_API_IMAGE"
log "frontend:  $CYGNUS_FRONTEND_IMAGE"
log "ingress:   $CYGNUS_PUBLIC_ORIGIN"
log "identity:  release=$APP_RELEASE commit=$APP_COMMIT_SHA deployment=$APP_DEPLOYMENT_ID head=$EXPECTED_ALEMBIC_HEAD"

if [ "$DRY_RUN" = 1 ]; then
  log "dry run validated required external inputs and would execute:"
  log "  docker compose pull"
  log "  docker compose up -d --wait postgres redis minio"
  log "  docker compose stop <currently running api/worker/worker-skills/delivery-consumer>"
  log "  docker compose run --rm --no-deps migrator  # current digest: Alembic head + storage"
  log "  docker compose up -d --no-deps --force-recreate api delivery-consumer"
  log "  docker compose up -d --no-deps --wait delivery-consumer"
  log "  docker compose up -d --no-deps --force-recreate frontend"
  log "  TLS livez plus exact signed-delivery route gate"
  log "  docker compose up -d --no-deps --force-recreate --wait worker worker-skills"
  log "  aggregate API + worker + delivery-consumer readiness gate"
  log "  migration failure resumes the previously running backend containers"
  log "  rollout/ingress failure recreates the previous immutable application release"
  log "  persist immutable release metadata, active checkout, and active/previous state externally"
  exit 0
fi

log "pulling reviewed digest-pinned images..."
compose_pull
log "starting private stateful services..."
compose_up_stateful
log "gracefully quiescing current API and workers before schema mutation..."
arm_backend_recovery_trap
compose_quiesce_backend
log "running mandatory current-image Alembic/storage migration gate..."
run_migrations
clear_backend_recovery_trap
if [ -n "$PREVIOUS" ]; then
  trap 'recover_failed_rollout "$?"' EXIT
fi
log "starting ingress backend from the migrated release..."
compose_up_ingress_backend
log "starting TLS reverse proxy..."
compose_up_frontend
verify_delivery_ingress "$CYGNUS_DOMAIN"
log "starting workers after the signed-delivery route is active..."
compose_up_workers
verify_ingress "$CYGNUS_DOMAIN"
persist_release_metadata "$RELEASE"
activate_release_checkout "$RELEASE"
save_state "$PREVIOUS" "$RELEASE"
trap - EXIT

log "deploy complete: $RELEASE is ready at $CYGNUS_PUBLIC_ORIGIN"
if [ -n "$PREVIOUS" ]; then
  log "rollback target: scripts/prod/rollback.sh --release $PREVIOUS"
fi
