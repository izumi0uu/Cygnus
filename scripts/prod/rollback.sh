#!/usr/bin/env bash
# Cygnus production rollback. Application image rollback is explicit; schema
# rollback is never implicit and must use the source image that owns the current
# Alembic head. The normal readiness gate rejects an incompatible schema.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"
FAILED_RELEASE="${CYGNUS_FAILED_RELEASE:-}"
SOURCE_METADATA_FILE="${CYGNUS_ROLLBACK_SOURCE_METADATA_FILE:-}"
SOURCE_INPUTS_FILE="${CYGNUS_ROLLBACK_SOURCE_INPUTS_FILE:-}"

RELEASE="${CYGNUS_RELEASE:-}"
DOWNGRADE_REV=""
YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE="${2:?--release requires a version}"; shift 2 ;;
    --downgrade) DOWNGRADE_REV="${2:?--downgrade requires an Alembic revision or target}"; shift 2 ;;
    --yes) YES=1; shift ;;
    *) die "unknown argument: $1 (usage: scripts/prod/rollback.sh [--release <version>] [--downgrade <revision|target>] [--yes])" ;;
  esac
done

clear_release_context() {
  unset CYGNUS_RELEASE_METADATA_FILE CYGNUS_RELEASE_INPUTS_FILE CYGNUS_PRODUCTION_INPUTS_FILE
  unset APP_RELEASE APP_COMMIT_SHA APP_DEPLOYMENT_ID EXPECTED_ALEMBIC_HEAD
  unset CYGNUS_API_IMAGE CYGNUS_FRONTEND_IMAGE LOADED_RELEASE_FILE LOADED_RELEASE_INPUTS_FILE
}

preflight_target_checkout() (
  exec 3>&1
  exec 1>&2
  local target_has_consumer=0
  clear_release_context
  # shellcheck disable=SC1090
  . "$TARGET_CHECKOUT/scripts/prod/lib.sh"
  load_prod_env
  load_release "$RELEASE"
  validate_identity "$RELEASE"
  validate_secrets
  validate_resources
  validate_production_inputs "$RELEASE"
  if declare -F validate_operator_state_paths >/dev/null; then
    validate_operator_state_paths "$RELEASE"
  fi
  validate_compose
  if "${COMPOSE[@]}" config --services | grep -Fxq delivery-consumer; then
    target_has_consumer=1
  fi
  printf '%s|%s' "$EXPECTED_ALEMBIC_HEAD" "$target_has_consumer" >&3
)

load_prod_env
load_state
[ -n "$RELEASE" ] || RELEASE="${CYGNUS_PREVIOUS_RELEASE:-}"
[ -n "$RELEASE" ] || die "no previous release is recorded; pass --release <approved-version>"
validate_release_identifier "$RELEASE"
if [ "$RELEASE" = "${CYGNUS_ACTIVE_RELEASE:-}" ] && [ -z "$FAILED_RELEASE" ]; then
  die "release $RELEASE is already active"
fi
if [ -n "$FAILED_RELEASE" ]; then
  validate_release_identifier "$FAILED_RELEASE"
fi
SOURCE_RELEASE="${FAILED_RELEASE:-${CYGNUS_ACTIVE_RELEASE:-}}"
[ -n "$SOURCE_RELEASE" ] || die "no active source release is recorded for rollback"
validate_release_identifier "$SOURCE_RELEASE"
[ "$SOURCE_RELEASE" != "$RELEASE" ] || die "rollback source and target releases are identical: $RELEASE"

TARGET_CHECKOUT=""
TARGET_ROOT=""
CURRENT_ROOT=$(CDPATH= cd -- "$REPO_ROOT" && pwd -P)
if [ -n "$CHECKOUTS_DIR" ]; then
  TARGET_CHECKOUT="$CHECKOUTS_DIR/$RELEASE"
  [ -x "$TARGET_CHECKOUT/scripts/prod/rollback.sh" ] || die "rollback checkout is missing or not executable: $TARGET_CHECKOUT"
  TARGET_ROOT=$(CDPATH= cd -- "$TARGET_CHECKOUT" && pwd -P)
fi

if [ -n "$TARGET_ROOT" ] && [ "$CURRENT_ROOT" != "$TARGET_ROOT" ]; then
  target_contract=$(preflight_target_checkout)
  TARGET_EXPECTED_ALEMBIC_HEAD=${target_contract%%|*}
  TARGET_HAS_DELIVERY_CONSUMER=${target_contract##*|}
else
  clear_release_context
  load_release "$RELEASE"
  validate_identity "$RELEASE"
  validate_secrets
  validate_resources
  validate_production_inputs "$RELEASE"
  validate_operator_state_paths "$RELEASE"
  validate_compose
  TARGET_EXPECTED_ALEMBIC_HEAD=$EXPECTED_ALEMBIC_HEAD
  TARGET_HAS_DELIVERY_CONSUMER=0
  if "${COMPOSE[@]}" config --services | grep -Fxq delivery-consumer; then
    TARGET_HAS_DELIVERY_CONSUMER=1
  fi
fi

clear_release_context
if [ -n "$SOURCE_METADATA_FILE" ]; then
  export CYGNUS_RELEASE_METADATA_FILE="$SOURCE_METADATA_FILE"
fi
if [ -n "$SOURCE_INPUTS_FILE" ]; then
  export CYGNUS_RELEASE_INPUTS_FILE="$SOURCE_INPUTS_FILE"
fi
load_release "$SOURCE_RELEASE"
validate_identity "$SOURCE_RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$SOURCE_RELEASE"
validate_operator_state_paths "$SOURCE_RELEASE"
validate_compose
SOURCE_EXPECTED_ALEMBIC_HEAD=$EXPECTED_ALEMBIC_HEAD

if [ "$DOWNGRADE_REV" = target ]; then
  DOWNGRADE_REV=$TARGET_EXPECTED_ALEMBIC_HEAD
fi
if [ "$SOURCE_EXPECTED_ALEMBIC_HEAD" != "$TARGET_EXPECTED_ALEMBIC_HEAD" ] && [ -z "$DOWNGRADE_REV" ]; then
  die "rollback crosses schema heads ($SOURCE_EXPECTED_ALEMBIC_HEAD -> $TARGET_EXPECTED_ALEMBIC_HEAD); pass --downgrade $TARGET_EXPECTED_ALEMBIC_HEAD"
fi
if [ -n "$DOWNGRADE_REV" ] && [ "$DOWNGRADE_REV" != "$TARGET_EXPECTED_ALEMBIC_HEAD" ]; then
  die "--downgrade must equal the target release Alembic head: $TARGET_EXPECTED_ALEMBIC_HEAD"
fi

log "rollback source: $SOURCE_RELEASE (schema $SOURCE_EXPECTED_ALEMBIC_HEAD)"
log "rollback target: $RELEASE (schema $TARGET_EXPECTED_ALEMBIC_HEAD)"
if [ "$YES" != 1 ]; then
  printf '[cygnus-prod] continue with rollback from %s to %s? [y/N] ' "$SOURCE_RELEASE" "$RELEASE"
  read -r answer
  case "$answer" in y|Y) ;; *) die "aborted" ;; esac
fi

log "gracefully quiescing the source API, workers, and delivery consumer..."
arm_backend_recovery_trap
compose_quiesce_backend

if [ -n "$DOWNGRADE_REV" ]; then
  log "running source-image Alembic downgrade to $DOWNGRADE_REV..."
  "${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"
fi

# Source containers are no longer a valid recovery target after a downgrade.
# The target rollback owns recovery from this point onward.
clear_backend_recovery_trap
if [ "$TARGET_HAS_DELIVERY_CONSUMER" != 1 ]; then
  log "removing candidate-only delivery-consumer before target checkout handoff..."
  "${COMPOSE[@]}" rm --stop --force delivery-consumer
fi

if [ -n "$TARGET_ROOT" ] && [ "$CURRENT_ROOT" != "$TARGET_ROOT" ]; then
  clear_release_context
  log "handing rollback to target checkout: $TARGET_CHECKOUT"
  CYGNUS_FAILED_RELEASE="$FAILED_RELEASE" \
    "$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes
  exit 0
fi

clear_release_context
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
validate_operator_state_paths "$RELEASE"
validate_compose
arm_backend_recovery_trap
log "recreating ingress backend from target digests..."
compose_up_ingress_backend
log "recreating TLS reverse proxy from the target digest..."
compose_up_frontend
verify_delivery_ingress "$CYGNUS_DOMAIN"
log "recreating workers after the target delivery route is active..."
compose_up_workers
verify_ingress "$CYGNUS_DOMAIN"
clear_backend_recovery_trap
activate_release_checkout "$RELEASE"
if [ -z "$FAILED_RELEASE" ]; then
  save_state "${CYGNUS_ACTIVE_RELEASE:-}" "$RELEASE"
else
  log "failed release $FAILED_RELEASE was removed from service; deployment state remains on $RELEASE"
fi
log "rollback complete: $RELEASE is ready"
