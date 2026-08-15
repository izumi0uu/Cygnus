#!/usr/bin/env bash
# Run the exact production images in an isolated, disposable certification stack.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export COMPOSE_PROJECT_NAME="${CYGNUS_CERTIFICATION_COMPOSE_PROJECT:-cygnus-certification}"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

ACTION="${1:-}"
shift || true
RELEASE="${CYGNUS_RELEASE:-}"
FAULT_TARGET=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --release) RELEASE="${2:?--release requires a version}"; shift 2 ;;
    --target) FAULT_TARGET="${2:?--target requires a dependency}"; shift 2 ;;
    *) die "usage: scripts/prod/certification-stack.sh <action> --release <version> [--target <db|queue|tool|provider>]" ;;
  esac
done
case "$ACTION" in
  up|redeploy|restart|recover|quiesce|resume|smoke-exercise|smoke-verify|domain-prepare|domain-verify|oauth-provision|rollback-drill|diagnostics|down|origin|fault-on|fault-off) ;;
  *) die "unsupported certification stack action: $ACTION" ;;
esac
case "$FAULT_TARGET" in ''|db|queue|tool|provider) ;; *) die "unsupported certification fault target: $FAULT_TARGET" ;; esac

load_prod_env
if [ -z "${CYGNUS_RELEASE_INPUTS_FILE:-}" ] && [ -n "${CYGNUS_PRODUCTION_INPUTS_FILE:-}" ]; then
  export CYGNUS_RELEASE_INPUTS_FILE="$CYGNUS_PRODUCTION_INPUTS_FILE"
fi
load_release "$RELEASE"
validate_identity "$RELEASE"

CERTIFICATION_COMPOSE_FILE="$DEPLOY_DIR/docker-compose.certification.yml"
[ -r "$CERTIFICATION_COMPOSE_FILE" ] || die "certification Compose overlay is missing"
[ "$COMPOSE_PROJECT_NAME" != "cygnus-prod" ] || die "certification project must not use the production Compose identity"
export CYGNUS_HTTP_BIND_PORT="${CYGNUS_CERTIFICATION_HTTP_PORT:-18080}"
export CYGNUS_HTTPS_BIND_PORT="${CYGNUS_CERTIFICATION_HTTPS_PORT:-18443}"
export CYGNUS_POSTGRES_VOLUME_NAME="${COMPOSE_PROJECT_NAME}-postgres"
export CYGNUS_REDIS_VOLUME_NAME="${COMPOSE_PROJECT_NAME}-redis"
export CYGNUS_MINIO_VOLUME_NAME="${COMPOSE_PROJECT_NAME}-minio"
export CYGNUS_NETWORK_NAME="${COMPOSE_PROJECT_NAME}-net"
export CYGNUS_NETWORK_SUBNET="${CYGNUS_CERTIFICATION_NETWORK_SUBNET:-172.31.0.0/24}"
export TRUSTED_PROXY_IPS="$CYGNUS_NETWORK_SUBNET"
PROXY_CIDR="$CYGNUS_NETWORK_SUBNET"
export CYGNUS_METRICS_ALLOWED_CIDR="${CYGNUS_CERTIFICATION_METRICS_ALLOWED_CIDR:-172.31.0.1/32}"
CERTIFICATION_ORIGIN="https://127.0.0.1:$CYGNUS_HTTPS_BIND_PORT"
PKI_DIR="${CYGNUS_CERTIFICATION_PKI_DIR:-${RUNNER_TEMP:-/tmp}/cygnus-certification-pki}"
mkdir -p "$PKI_DIR"
chmod 700 "$PKI_DIR"
if [ ! -s "$PKI_DIR/server.crt" ] || [ ! -s "$PKI_DIR/server.key" ] || ! openssl x509 -in "$PKI_DIR/server.crt" -noout -ext subjectAltName 2>/dev/null | grep -q 'IP Address:127.0.0.1'; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -subj "/CN=$CYGNUS_DOMAIN" \
    -addext "subjectAltName=DNS:$CYGNUS_DOMAIN,IP:127.0.0.1" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -keyout "$PKI_DIR/server.key" -out "$PKI_DIR/server.crt" >/dev/null 2>&1
fi
chmod 600 "$PKI_DIR/server.key" "$PKI_DIR/server.crt"
export CYGNUS_TLS_CERT_FILE="$PKI_DIR/server.crt"
export CYGNUS_TLS_KEY_FILE="$PKI_DIR/server.key"
COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --project-directory "$DEPLOY_DIR" -f "$COMPOSE_FILE" -f "$CERTIFICATION_COMPOSE_FILE" --env-file "$PROD_ENV_FILE")
SMOKE_RECEIPT="${CYGNUS_CERTIFICATION_SMOKE_RECEIPT:-$OPERATOR_WORK_DIR/$RELEASE/certification/governance-smoke.json}"
DOMAIN_STATE="${CYGNUS_CERTIFICATION_DOMAIN_STATE:-$OPERATOR_WORK_DIR/$RELEASE/certification/persisted-domain-state.json}"
DOMAIN_RESULT="${CYGNUS_CERTIFICATION_DOMAIN_RESULT:-$OPERATOR_WORK_DIR/$RELEASE/certification/persisted-domain-result.json}"

verify_certification_ingress() {
  local deadline body
  deadline=$(( $(date +%s) + 300 ))
  while :; do
    if body=$(curl -fsS --cacert "$CYGNUS_TLS_CERT_FILE" --max-time 10 "$CERTIFICATION_ORIGIN/readyz" 2>/dev/null) && printf '%s' "$body" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ready"'; then
      log "certification ingress ready: $CERTIFICATION_ORIGIN/readyz"
      return 0
    fi
    [ "$(date +%s)" -lt "$deadline" ] || die "certification ingress did not become ready: $CERTIFICATION_ORIGIN"
    sleep 5
  done
}

case "$ACTION" in
  origin)
    printf '%s\n' "$CERTIFICATION_ORIGIN"
    ;;
  down)
    "${COMPOSE[@]}" down -v --remove-orphans
    ;;
  quiesce)
    "${COMPOSE[@]}" stop api worker worker-skills
    ;;
  resume)
    "${COMPOSE[@]}" start api worker worker-skills
    verify_certification_ingress
    ;;
  restart)
    "${COMPOSE[@]}" restart api worker worker-skills frontend
    verify_certification_ingress
    ;;
  recover)
    compose_up_backend
    compose_up_frontend
    verify_certification_ingress
    ;;
  smoke-exercise)
    mkdir -p "$(dirname "$SMOKE_RECEIPT")"
    rm -f "$SMOKE_RECEIPT"
    "${COMPOSE[@]}" exec -T api python -m cygnus.runtime.bootstrap.governance_smoke exercise --receipt-path /tmp/cygnus-governance-live.json
    "${COMPOSE[@]}" cp api:/tmp/cygnus-governance-live.json "$SMOKE_RECEIPT"
    ;;
  smoke-verify)
    [ -s "$SMOKE_RECEIPT" ] || die "governance smoke receipt is missing: $SMOKE_RECEIPT"
    "${COMPOSE[@]}" cp "$SMOKE_RECEIPT" api:/tmp/cygnus-governance-live.json
    "${COMPOSE[@]}" exec -T api python -m cygnus.runtime.bootstrap.governance_smoke verify --receipt-path /tmp/cygnus-governance-live.json
    ;;
  domain-prepare)
    [ -s "$SMOKE_RECEIPT" ] || die "governance smoke receipt is missing: $SMOKE_RECEIPT"
    mkdir -p "$(dirname "$DOMAIN_STATE")"
    "${COMPOSE[@]}" cp "$SMOKE_RECEIPT" api:/tmp/cygnus-governance-live.json
    "${COMPOSE[@]}" exec -T api python -m cygnus.runtime.bootstrap.persisted_domain_certification prepare --receipt-path /tmp/cygnus-governance-live.json --state-path /tmp/cygnus-persisted-domain-state.json
    "${COMPOSE[@]}" cp api:/tmp/cygnus-persisted-domain-state.json "$DOMAIN_STATE"
    ;;
  domain-verify)
    [ -s "$DOMAIN_STATE" ] || die "persisted domain state is missing: $DOMAIN_STATE"
    "${COMPOSE[@]}" cp "$DOMAIN_STATE" api:/tmp/cygnus-persisted-domain-state.json
    "${COMPOSE[@]}" exec -T api python -m cygnus.runtime.bootstrap.persisted_domain_certification verify --receipt-path /tmp/cygnus-governance-live.json --state-path /tmp/cygnus-persisted-domain-state.json --result-path /tmp/cygnus-persisted-domain-result.json
    "${COMPOSE[@]}" cp api:/tmp/cygnus-persisted-domain-result.json "$DOMAIN_RESULT"
    ;;
  oauth-provision)
    "${COMPOSE[@]}" exec -T api python -m cygnus.runtime.bootstrap.oauth_client_provision \
      --redirect-uri "$CERTIFICATION_ORIGIN/oauth/callback"
    ;;
  diagnostics)
    "${COMPOSE[@]}" ps --format json
    ;;
  fault-on|fault-off)
    [ -n "$FAULT_TARGET" ] || die "$ACTION requires --target"
    case "$FAULT_TARGET" in
      db) service=postgres ;;
      queue) service=redis ;;
      tool) service=worker-skills ;;
      provider) service=minio ;;
    esac
    if [ "$ACTION" = fault-on ]; then
      "${COMPOSE[@]}" stop -t 5 "$service"
    else
      "${COMPOSE[@]}" start "$service"
    fi
    ;;
  rollback-drill)
    bad_overlay=$(mktemp "${TMPDIR:-/tmp}/cygnus-bad-candidate.XXXXXX.yml")
    printf 'services:\n  frontend:\n    image: %s\n' "$CYGNUS_API_IMAGE" > "$bad_overlay"
    restore_frontend() {
      "${COMPOSE[@]}" up -d --no-deps --force-recreate --wait frontend >/dev/null
      rm -f "$bad_overlay"
    }
    trap restore_frontend EXIT
    "${COMPOSE[@]}" -f "$bad_overlay" up -d --no-deps --force-recreate frontend >/dev/null
    sleep 3
    origin="$CERTIFICATION_ORIGIN"
    failed_status=$(curl -k -sS --max-time 10 -o /dev/null -w '%{http_code}' "$origin/" || true)
    [ "$failed_status" != 200 ] || die "invalid frontend candidate unexpectedly served successfully"
    restore_frontend
    trap - EXIT
    verify_certification_ingress
    frontend_container=$("${COMPOSE[@]}" ps -q frontend)
    restored_image=$(docker inspect --format '{{.Config.Image}}' "$frontend_container")
    [ "$restored_image" = "$CYGNUS_FRONTEND_IMAGE" ] || die "rollback did not restore the exact approved frontend image"
    printf '{"failed_candidate_http_status":"%s","restored":true,"restored_frontend_image":"%s"}\n' "$failed_status" "$restored_image"
    ;;
  up|redeploy)
    validate_secrets
    validate_resources
    validate_production_inputs "$RELEASE"
    certification_url="$CERTIFICATION_ORIGIN"
    export PORTAL_BASE_URL="$certification_url"
    export CORS_ORIGINS="$certification_url"
    export MINIO_PUBLIC_ENDPOINT="$CYGNUS_DOMAIN:$CYGNUS_HTTPS_BIND_PORT"
    validate_compose
    if [ "$ACTION" = up ]; then
      "${COMPOSE[@]}" down -v --remove-orphans
    fi
    compose_pull
    compose_up_stateful
    run_migrations
    compose_up_backend
    compose_up_frontend
    verify_certification_ingress
    ;;
esac
