#!/usr/bin/env bash
# Execute one exact production Compose operation after loading the approved
# release/environment. Use this as the backup_restore quiesce/resume command;
# it cannot accidentally target the repository's development compose file.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

RELEASE="${CYGNUS_RELEASE:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE="${2:?--release requires a version}"; shift 2 ;;
    --) shift; break ;;
    *) die "usage: scripts/prod/compose-control.sh --release <version> -- <docker-compose arguments>" ;;
  esac
done
[ "$#" -gt 0 ] || die "no docker compose arguments provided"

load_prod_env
load_release "$RELEASE"
validate_identity "$RELEASE"
validate_secrets
validate_resources
validate_production_inputs "$RELEASE"
validate_compose
case "$1" in
  quiesce-backend)
    [ "$#" -eq 1 ] || die "quiesce-backend accepts no additional arguments"
    compose_quiesce_backend
    exit 0
    ;;
  resume-backend)
    [ "$#" -eq 1 ] || die "resume-backend accepts no additional arguments"
    compose_resume_backend
    exit 0
    ;;
esac
exec "${COMPOSE[@]}" "$@"
