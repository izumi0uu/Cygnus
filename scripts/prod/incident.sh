#!/usr/bin/env bash
# Fail-closed Production V1 incident command. Status is read-only; containment
# is delegated only to an approved protected-runner executable and is never
# guessed from a local Compose stack.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ACTION=${1:-}
shift || true
RELEASE=${CYGNUS_RELEASE:-}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --release) RELEASE=${2:?--release requires a version}; shift 2 ;;
    *) die "usage: scripts/prod/incident.sh <status|contain> --release <version>" ;;
  esac
done
case "$ACTION" in status|contain) ;; *) die "first argument must be status or contain" ;; esac
load_prod_env
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
case "$ACTION" in
  status)
    "${COMPOSE[@]}" ps
    verify_ingress "$CYGNUS_DOMAIN"
    log "production ingress and Compose service status are healthy"
    ;;
  contain)
    for variable in CYGNUS_INCIDENT_CONTAINMENT_RUNNER CYGNUS_INCIDENT_APPROVAL_REF; do
      [ -n "${!variable:-}" ] && ! is_placeholder "${!variable}" || die "$variable must be a non-placeholder external input"
    done
    [ -x "$CYGNUS_INCIDENT_CONTAINMENT_RUNNER" ] || die "CYGNUS_INCIDENT_CONTAINMENT_RUNNER must name an executable protected-runner command"
    exec "$CYGNUS_INCIDENT_CONTAINMENT_RUNNER" --release "$RELEASE" --approval-ref "$CYGNUS_INCIDENT_APPROVAL_REF" --environment-file "$DEPLOY_DIR/.env.prod"
    ;;
esac
