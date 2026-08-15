#!/usr/bin/env bash
# Shared fail-closed helpers for Cygnus Production V1 deploy operations.
# Sourced by scripts/prod/*.sh; not an executable entrypoint itself.
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cygnus-prod}"
COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --project-directory "$DEPLOY_DIR" -f "$COMPOSE_FILE")
PROXY_CIDR='172.30.0.0/24'
PLACEHOLDER_VALUES='change[_-]?me|replace[_-]?with|example\.com|<[^>]+>|cygnus-local-dev|todo|pending|unknown'

log() { printf '[cygnus-prod] %s\n' "$*"; }
die() { printf '[cygnus-prod] ERROR: %s\n' "$*" >&2; exit 1; }

# Parse only plain KEY=value dotenv records. Do NOT source an operator-managed
# env file: values are exported as data and never evaluated as shell code.
load_env_file() {
  local file="$1" line key value
  [ -f "$file" ] || die "required env file is missing: $file"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|'#'*) continue ;;
      [A-Za-z_][A-Za-z0-9_]*=*)
        key=${line%%=*}
        value=${line#*=}
        case "$value" in *$'\r'*|*$'\n'*) die "$file:$key has an invalid multiline value" ;; esac
        export "$key=$value"
        ;;
      *) die "$file contains invalid dotenv syntax; require plain KEY=value records" ;;
    esac
  done < "$file"
}

load_prod_env() { load_env_file "$DEPLOY_DIR/.env.prod"; }

validate_release_identifier() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' || die "release identifier must contain only letters, numbers, dot, underscore, or hyphen"
}

load_release() {
  local release="${1:-}"
  [ -n "$release" ] || die "no release specified; set CYGNUS_RELEASE or pass --release <version>"
  validate_release_identifier "$release"
  local release_file="$DEPLOY_DIR/releases/$release.env"
  [ -f "$release_file" ] || die "release metadata missing: $release_file"
  load_env_file "$release_file"
  validate_digests "$release"
}

validate_digests() {
  local release="$1" var value
  for var in CYGNUS_API_IMAGE CYGNUS_FRONTEND_IMAGE; do
    value="${!var:-}"
    if ! printf '%s' "$value" | grep -Eq '^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$'; then
      die "release $release: $var must be an exact name@sha256:<64 hex> reference"
    fi
  done
}

validate_identity() {
  local release="$1"
  APP_RELEASE="${APP_RELEASE:-$release}"
  APP_DEPLOYMENT_ID="${APP_DEPLOYMENT_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
  export APP_RELEASE APP_DEPLOYMENT_ID
  for var in APP_COMMIT_SHA EXPECTED_ALEMBIC_HEAD; do
    [ -n "${!var:-}" ] || die "$var is required in deploy/releases/$release.env"
  done
  printf '%s' "$APP_COMMIT_SHA" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$' || die "APP_COMMIT_SHA must be a full 40- or 64-hex commit SHA"
  for var in APP_RELEASE APP_DEPLOYMENT_ID EXPECTED_ALEMBIC_HEAD; do
    printf '%s' "${!var}" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' || die "$var contains an unsafe release identifier"
  done
}

is_placeholder() { printf '%s' "$1" | grep -Eiq "$PLACEHOLDER_VALUES"; }

validate_secrets() {
  local v f val
  for v in CYGNUS_TLS_CERT_FILE CYGNUS_TLS_KEY_FILE; do
    f="${!v:-}"
    [ -n "$f" ] || die "$v is required in deploy/.env.prod"
    [ -f "$f" ] && [ -s "$f" ] && [ -r "$f" ] || die "$v must name a readable non-empty external TLS file"
  done
  for v in SECRET_KEY DEFAULT_ADMIN_PASSWORD MCP_TOKEN_PEPPER DELIVERY_HMAC_SECRET POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD MINIO_SECRET_KEY; do
    val="${!v:-}"
    [ -n "$val" ] || die "$v is required in deploy/.env.prod"
    is_placeholder "$val" && die "$v still holds a placeholder/default value"
  done
  [ -n "${CYGNUS_DOMAIN:-}" ] && ! is_placeholder "$CYGNUS_DOMAIN" || die "CYGNUS_DOMAIN must be a real public FQDN"
  [ "${MINIO_PUBLIC_ENDPOINT:-}" = "$CYGNUS_DOMAIN" ] || die "MINIO_PUBLIC_ENDPOINT must exactly equal CYGNUS_DOMAIN for same-origin URLs"
  [ "${PORTAL_BASE_URL:-}" = "https://$CYGNUS_DOMAIN" ] || die "PORTAL_BASE_URL must be https://CYGNUS_DOMAIN"
  [ "${CORS_ORIGINS:-}" = "https://$CYGNUS_DOMAIN" ] || die "CORS_ORIGINS must be exactly https://CYGNUS_DOMAIN"
  [ "${TRUSTED_PROXY_IPS:-}" = "$PROXY_CIDR" ] || die "TRUSTED_PROXY_IPS must be the deterministic narrow prodnet CIDR $PROXY_CIDR"
  [ -n "${CYGNUS_METRICS_ALLOWED_CIDR:-}" ] || die "CYGNUS_METRICS_ALLOWED_CIDR is required"
  is_placeholder "$CYGNUS_METRICS_ALLOWED_CIDR" && die "CYGNUS_METRICS_ALLOWED_CIDR is a placeholder"
  python3 "$REPO_ROOT/scripts/production_network_config_gate.py" --domain "$CYGNUS_DOMAIN" --metrics-cidr "$CYGNUS_METRICS_ALLOWED_CIDR" --expected-proxy-cidr "$PROXY_CIDR" --quiet || die "public domain or nginx network inputs are invalid"
  [ -n "${CYGNUS_DELIVERY_ALLOWED_HOSTS:-}" ] && ! is_placeholder "$CYGNUS_DELIVERY_ALLOWED_HOSTS" || die "CYGNUS_DELIVERY_ALLOWED_HOSTS must explicitly name internal delivery hosts"
  [ -n "${CYGNUS_DELIVERY_HMAC_SECRET_REF:-}" ] && ! is_placeholder "$CYGNUS_DELIVERY_HMAC_SECRET_REF" || die "CYGNUS_DELIVERY_HMAC_SECRET_REF must identify the externally injected HMAC secret"
  python3 "$REPO_ROOT/scripts/production_delivery_config_gate.py" --targets-json "${DELIVERY_TARGETS_JSON:-}" --allowed-hosts "$CYGNUS_DELIVERY_ALLOWED_HOSTS" --quiet || die "DELIVERY_TARGETS_JSON must configure approved internal HTTPS delivery endpoints"
}

validate_capacity_inputs() {
  local v actual_hash
  for v in CYGNUS_METRICS_ALLOWLIST_REF CYGNUS_CAPACITY_THRESHOLDS_FILE CYGNUS_CAPACITY_TARGETS_FILE CYGNUS_CAPACITY_APPROVAL_REF CYGNUS_CAPACITY_THRESHOLDS_REF CYGNUS_CAPACITY_TARGETS_REF CYGNUS_CAPACITY_THRESHOLDS_SHA256 CYGNUS_ALERT_THRESHOLDS_FILE CYGNUS_ALERT_APPROVAL_REF CYGNUS_ALERT_THRESHOLDS_REF CYGNUS_ALERT_THRESHOLDS_SHA256 CYGNUS_BACKUP_SOURCE_ID CYGNUS_RPO_OBJECTIVE_REF CYGNUS_RTO_OBJECTIVE_REF; do
    [ -n "${!v:-}" ] || die "$v is required in deploy/.env.prod"
    is_placeholder "${!v}" && die "$v is a placeholder"
  done
  [ -r "$CYGNUS_CAPACITY_THRESHOLDS_FILE" ] && [ -s "$CYGNUS_CAPACITY_THRESHOLDS_FILE" ] || die "CYGNUS_CAPACITY_THRESHOLDS_FILE must be a readable non-empty approved file"
  [ -r "$CYGNUS_CAPACITY_TARGETS_FILE" ] && [ -s "$CYGNUS_CAPACITY_TARGETS_FILE" ] || die "CYGNUS_CAPACITY_TARGETS_FILE must be a readable non-empty approved file"
  [ -r "$CYGNUS_ALERT_THRESHOLDS_FILE" ] && [ -s "$CYGNUS_ALERT_THRESHOLDS_FILE" ] || die "CYGNUS_ALERT_THRESHOLDS_FILE must be a readable non-empty approved file"
  printf '%s' "$CYGNUS_CAPACITY_THRESHOLDS_SHA256" | grep -Eq '^sha256:[0-9a-f]{64}$' || die "CYGNUS_CAPACITY_THRESHOLDS_SHA256 must be sha256:<64 hex>"
  printf '%s' "$CYGNUS_ALERT_THRESHOLDS_SHA256" | grep -Eq '^sha256:[0-9a-f]{64}$' || die "CYGNUS_ALERT_THRESHOLDS_SHA256 must be sha256:<64 hex>"
  actual_hash="sha256:$(python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$CYGNUS_CAPACITY_THRESHOLDS_FILE")"
  [ "$actual_hash" = "$CYGNUS_CAPACITY_THRESHOLDS_SHA256" ] || die "CYGNUS_CAPACITY_THRESHOLDS_FILE hash does not match CYGNUS_CAPACITY_THRESHOLDS_SHA256"
  actual_hash="sha256:$(python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$CYGNUS_ALERT_THRESHOLDS_FILE")"
  [ "$actual_hash" = "$CYGNUS_ALERT_THRESHOLDS_SHA256" ] || die "CYGNUS_ALERT_THRESHOLDS_FILE hash does not match CYGNUS_ALERT_THRESHOLDS_SHA256"
}

validate_resources() {
  local v val
  for v in CYGNUS_APP_CPU_LIMIT CYGNUS_APP_MEMORY_LIMIT CYGNUS_POSTGRES_CPU_LIMIT CYGNUS_POSTGRES_MEMORY_LIMIT CYGNUS_REDIS_CPU_LIMIT CYGNUS_REDIS_MEMORY_LIMIT CYGNUS_MINIO_CPU_LIMIT CYGNUS_MINIO_MEMORY_LIMIT CYGNUS_FRONTEND_CPU_LIMIT CYGNUS_FRONTEND_MEMORY_LIMIT; do
    val="${!v:-}"
    [ -n "$val" ] || die "$v is required in deploy/.env.prod"
    is_placeholder "$val" && die "$v is a placeholder"
  done
  for v in CYGNUS_APP_CPU_LIMIT CYGNUS_POSTGRES_CPU_LIMIT CYGNUS_REDIS_CPU_LIMIT CYGNUS_MINIO_CPU_LIMIT CYGNUS_FRONTEND_CPU_LIMIT; do
    printf '%s' "${!v}" | grep -Eq '^[0-9]+([.][0-9]+)?$' || die "$v must be a positive Compose CPU limit"
    if printf '%s' "${!v}" | grep -Eq '^0([.]0+)?$'; then
      die "$v must be greater than zero"
    fi
  done
  for v in CYGNUS_APP_MEMORY_LIMIT CYGNUS_POSTGRES_MEMORY_LIMIT CYGNUS_REDIS_MEMORY_LIMIT CYGNUS_MINIO_MEMORY_LIMIT CYGNUS_FRONTEND_MEMORY_LIMIT; do
    printf '%s' "${!v}" | grep -Eiq '^[1-9][0-9]*([kmgt]i?b?|b)?$' || die "$v must be a positive Compose memory limit (for example 512M)"
  done
}

validate_production_inputs() {
  local release="$1" inputs="${CYGNUS_PRODUCTION_INPUTS_FILE:-$DEPLOY_DIR/production-inputs.json}"
  [ -f "$inputs" ] || die "production input manifest is required: $inputs (copy deploy/production-inputs.example.json and obtain approvals)"
  command -v python3 >/dev/null || die "python3 is required to validate production inputs"
  validate_capacity_inputs
  python3 "$REPO_ROOT/scripts/production_inputs_gate.py" \
    --inputs "$inputs" \
    --git-sha "$APP_COMMIT_SHA" \
    --backend-image "$CYGNUS_API_IMAGE" \
    --frontend-image "$CYGNUS_FRONTEND_IMAGE" \
    --alembic-head "$EXPECTED_ALEMBIC_HEAD" \
    --domain "$CYGNUS_DOMAIN" \
    --delivery-targets-json "$DELIVERY_TARGETS_JSON" \
    --delivery-allowed-hosts "$CYGNUS_DELIVERY_ALLOWED_HOSTS" \
    --delivery-hmac-secret-ref "$CYGNUS_DELIVERY_HMAC_SECRET_REF" \
    --metrics-allowed-cidr "$CYGNUS_METRICS_ALLOWED_CIDR" \
    --metrics-allowlist-ref "$CYGNUS_METRICS_ALLOWLIST_REF" \
    --capacity-approval-ref "$CYGNUS_CAPACITY_APPROVAL_REF" \
    --capacity-thresholds-ref "$CYGNUS_CAPACITY_THRESHOLDS_REF" \
    --capacity-targets-ref "$CYGNUS_CAPACITY_TARGETS_REF" \
    --alert-approval-ref "$CYGNUS_ALERT_APPROVAL_REF" \
    --alert-thresholds-ref "$CYGNUS_ALERT_THRESHOLDS_REF" \
    --alert-thresholds-sha256 "$CYGNUS_ALERT_THRESHOLDS_SHA256" \
    --backup-source-identity "$CYGNUS_BACKUP_SOURCE_ID" \
    --rpo-objective-ref "$CYGNUS_RPO_OBJECTIVE_REF" \
    --rto-objective-ref "$CYGNUS_RTO_OBJECTIVE_REF" \
    --capacity-thresholds-sha256 "$CYGNUS_CAPACITY_THRESHOLDS_SHA256" \
    --expected-proxy-cidr "$PROXY_CIDR" \
    --report "$DEPLOY_DIR/evidence/production-inputs-$release.json"
  python3 "$REPO_ROOT/scripts/render_alert_rules.py" \
    --thresholds "$CYGNUS_ALERT_THRESHOLDS_FILE" \
    --approval-ref "$CYGNUS_ALERT_APPROVAL_REF" \
    --thresholds-ref "$CYGNUS_ALERT_THRESHOLDS_REF" \
    --thresholds-sha256 "$CYGNUS_ALERT_THRESHOLDS_SHA256" \
    --output "$DEPLOY_DIR/rendered/alert_rules.yml" \
    --quiet || die "approved alert rule rendering failed"
  [ -s "$DEPLOY_DIR/rendered/alert_rules.yml" ] || die "rendered alert rule file is empty"
}

compose_up_stateful() { "${COMPOSE[@]}" up -d --wait postgres redis minio; }
run_migrations() { "${COMPOSE[@]}" run --rm --no-deps migrator; }
compose_up_backend() { "${COMPOSE[@]}" up -d --no-deps --force-recreate api worker worker-skills; }
compose_up_frontend() { "${COMPOSE[@]}" up -d --no-deps --force-recreate frontend; }

# Verify TLS termination plus API JSON semantics. No -k: a production deploy
# must present a certificate valid for CYGNUS_DOMAIN even when we pin traffic to
# local ingress with --resolve.
verify_ingress() {
  local domain="$1" timeout_seconds="${2:-300}" interval="${3:-5}" deadline body
  [ -n "$domain" ] || die "verify_ingress: no domain"
  deadline=$(( $(date +%s) + timeout_seconds ))
  [ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/livez || true)" = "301" ] || die "HTTP ingress must redirect /livez to HTTPS"
  while :; do
    if body=$(curl -fsS --resolve "$domain:443:127.0.0.1" --max-time 10 "https://$domain/livez" 2>/dev/null) && printf '%s' "$body" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "alive"'; then
      break
    fi
    [ "$(date +%s)" -lt "$deadline" ] || die "TLS/API livez did not become healthy at https://$domain/livez"
    sleep "$interval"
  done
  while :; do
    if body=$(curl -fsS --resolve "$domain:443:127.0.0.1" --max-time 10 "https://$domain/readyz" 2>/dev/null) && printf '%s' "$body" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ready"'; then
      log "ingress ready: https://$domain/readyz"
      return 0
    fi
    [ "$(date +%s)" -lt "$deadline" ] || die "TLS/API readyz did not become ready at https://$domain/readyz"
    sleep "$interval"
  done
}

save_state() {
  local previous="$1" active="$2"
  umask 077
  printf 'CYGNUS_PREVIOUS_RELEASE=%s\nCYGNUS_ACTIVE_RELEASE=%s\n' "$previous" "$active" > "$DEPLOY_DIR/.state"
  log "state: previous=$previous active=$active"
}

load_state() { load_env_file "$DEPLOY_DIR/.state"; }
