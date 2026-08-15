#!/usr/bin/env bash
# Cygnus production rollback. Application image rollback is explicit; schema
# rollback is never implicit and must use the target image plus an explicit
# Alembic revision. The normal readiness gate rejects an incompatible schema.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

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
[ "$RELEASE" != "${CYGNUS_ACTIVE_RELEASE:-}" ] || die "release $RELEASE is already active"
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
validate_compose

log "rollback target: $RELEASE"
log "api:       $CYGNUS_API_IMAGE"
log "frontend:  $CYGNUS_FRONTEND_IMAGE"
if [ "$YES" != 1 ]; then
  printf '[cygnus-prod] continue with rollback to %s? [y/N] ' "$RELEASE"
  read -r answer
  case "$answer" in y|Y) ;; *) die "aborted" ;; esac
fi

if [ -n "$DOWNGRADE_REV" ]; then
  log "running explicit target-image Alembic downgrade to $DOWNGRADE_REV..."
  "${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"
fi

log "recreating backend and proxy from target digests..."
compose_up_backend
compose_up_frontend
verify_ingress "$CYGNUS_DOMAIN"
save_state "${CYGNUS_ACTIVE_RELEASE:-}" "$RELEASE"
log "rollback complete: $RELEASE is ready"
