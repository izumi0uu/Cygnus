#!/usr/bin/env bash
# Shared fail-closed helpers for Cygnus Production V1 deploy operations.
# Sourced by scripts/prod/*.sh; not an executable entrypoint itself.
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
PROD_ENV_FILE="${CYGNUS_PRODUCTION_ENV_FILE:-$DEPLOY_DIR/.env.prod}"
RELEASES_DIR="$DEPLOY_DIR/releases"
STATE_FILE="$DEPLOY_DIR/.state"
CHECKOUTS_DIR=""
ACTIVE_CHECKOUT_LINK=""
OPERATOR_WORK_DIR="$DEPLOY_DIR"
export CYGNUS_PRODUCTION_ENV_FILE="$PROD_ENV_FILE"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cygnus-prod}"
COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --project-directory "$DEPLOY_DIR" -f "$COMPOSE_FILE" --env-file "$PROD_ENV_FILE")
PRODUCTION_BACKEND_SERVICES=(api worker worker-skills)
QUIESCED_BACKEND_SERVICES=()
BACKEND_RECOVERY_TRAP_ARMED=0
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

load_prod_env() {
  local releases_override="${CYGNUS_RELEASES_DIR:-}"
  local state_override="${CYGNUS_DEPLOY_STATE_FILE:-}"
  local checkouts_override="${CYGNUS_CHECKOUTS_DIR:-}"
  local active_link_override="${CYGNUS_ACTIVE_CHECKOUT_LINK:-}"
  local operator_work_override="${CYGNUS_OPERATOR_WORK_DIR:-}"
  load_env_file "$PROD_ENV_FILE"
  RELEASES_DIR="${releases_override:-${CYGNUS_RELEASES_DIR:-$DEPLOY_DIR/releases}}"
  STATE_FILE="${state_override:-${CYGNUS_DEPLOY_STATE_FILE:-$DEPLOY_DIR/.state}}"
  CHECKOUTS_DIR="${checkouts_override:-${CYGNUS_CHECKOUTS_DIR:-}}"
  ACTIVE_CHECKOUT_LINK="${active_link_override:-${CYGNUS_ACTIVE_CHECKOUT_LINK:-}}"
  OPERATOR_WORK_DIR="${operator_work_override:-${CYGNUS_OPERATOR_WORK_DIR:-$DEPLOY_DIR}}"
  export CYGNUS_RELEASES_DIR="$RELEASES_DIR"
  export CYGNUS_DEPLOY_STATE_FILE="$STATE_FILE"
  export CYGNUS_CHECKOUTS_DIR="$CHECKOUTS_DIR"
  export CYGNUS_ACTIVE_CHECKOUT_LINK="$ACTIVE_CHECKOUT_LINK"
  export CYGNUS_OPERATOR_WORK_DIR="$OPERATOR_WORK_DIR"
}

validate_release_identifier() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' || die "release identifier must contain only letters, numbers, dot, underscore, or hyphen"
}

load_release() {
  local release="${1:-}" release_file release_inputs fallback_file fallback_inputs
  [ -n "$release" ] || die "no release specified; set CYGNUS_RELEASE or pass --release <version>"
  validate_release_identifier "$release"
  fallback_file="$DEPLOY_DIR/releases/$release.env"
  fallback_inputs="$DEPLOY_DIR/releases/$release.production-inputs.json"
  if [ -n "${CYGNUS_RELEASE_METADATA_FILE:-}" ]; then
    release_file="$CYGNUS_RELEASE_METADATA_FILE"
  else
    release_file="$RELEASES_DIR/$release.env"
    if [ ! -f "$release_file" ] && [ "$release_file" != "$fallback_file" ]; then
      release_file="$fallback_file"
    fi
  fi
  if [ -n "${CYGNUS_RELEASE_INPUTS_FILE:-}" ]; then
    release_inputs="$CYGNUS_RELEASE_INPUTS_FILE"
  else
    release_inputs="$RELEASES_DIR/$release.production-inputs.json"
    if [ ! -f "$release_inputs" ] && [ "$release_inputs" != "$fallback_inputs" ]; then
      release_inputs="$fallback_inputs"
    fi
  fi
  [ -f "$release_file" ] || die "release metadata missing: $release_file"
  [ -f "$release_inputs" ] || die "release-bound production inputs missing: $release_inputs"
  LOADED_RELEASE_FILE="$release_file"
  LOADED_RELEASE_INPUTS_FILE="$release_inputs"
  export CYGNUS_PRODUCTION_INPUTS_FILE="$release_inputs"
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
  [ "$APP_RELEASE" = "$release" ] || die "release metadata APP_RELEASE does not match requested release $release"
  for var in APP_COMMIT_SHA EXPECTED_ALEMBIC_HEAD; do
    [ -n "${!var:-}" ] || die "$var is required in the release metadata file"
  done
  printf '%s' "$APP_COMMIT_SHA" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$' || die "APP_COMMIT_SHA must be a full 40- or 64-hex commit SHA"
  for var in APP_RELEASE APP_DEPLOYMENT_ID EXPECTED_ALEMBIC_HEAD; do
    printf '%s' "${!var}" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' || die "$var contains an unsafe release identifier"
  done
}

is_placeholder() { printf '%s' "$1" | grep -Eiq "$PLACEHOLDER_VALUES"; }

validate_secrets() {
  local v f val expected_origin expected_authority
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
  [ -n "${CYGNUS_PUBLIC_ORIGIN:-}" ] || die "CYGNUS_PUBLIC_ORIGIN is required in deploy/.env.prod"
  expected_origin="$CYGNUS_PUBLIC_ORIGIN"
  expected_authority="${expected_origin#https://}"
  [ "${MINIO_PUBLIC_ENDPOINT:-}" = "$expected_authority" ] || die "MINIO_PUBLIC_ENDPOINT must exactly equal the CYGNUS_PUBLIC_ORIGIN authority for same-origin URLs"
  [ "${PORTAL_BASE_URL:-}" = "$expected_origin" ] || die "PORTAL_BASE_URL must exactly equal CYGNUS_PUBLIC_ORIGIN"
  [ "${CORS_ORIGINS:-}" = "$expected_origin" ] || die "CORS_ORIGINS must exactly equal CYGNUS_PUBLIC_ORIGIN"
  [ "${TRUSTED_PROXY_IPS:-}" = "$PROXY_CIDR" ] || die "TRUSTED_PROXY_IPS must be the deterministic narrow prodnet CIDR $PROXY_CIDR"
  [ -n "${CYGNUS_METRICS_ALLOWED_CIDR:-}" ] || die "CYGNUS_METRICS_ALLOWED_CIDR is required"
  is_placeholder "$CYGNUS_METRICS_ALLOWED_CIDR" && die "CYGNUS_METRICS_ALLOWED_CIDR is a placeholder"
  python3 "$REPO_ROOT/scripts/production_network_config_gate.py" --domain "$CYGNUS_DOMAIN" --public-origin "$expected_origin" --metrics-cidr "$CYGNUS_METRICS_ALLOWED_CIDR" --expected-proxy-cidr "$PROXY_CIDR" --quiet || die "public domain, origin, or nginx network inputs are invalid"
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
  local release_work_dir="$OPERATOR_WORK_DIR/$release" public_origin
  public_origin="$CYGNUS_PUBLIC_ORIGIN"
  [ -f "$inputs" ] || die "production input manifest is required: $inputs (copy deploy/production-inputs.example.json and obtain approvals)"
  command -v python3 >/dev/null || die "python3 is required to validate production inputs"
  [ -d "$OPERATOR_WORK_DIR" ] && [ -w "$OPERATOR_WORK_DIR" ] || die "CYGNUS_OPERATOR_WORK_DIR must be an existing writable protected directory"
  mkdir -p "$release_work_dir/evidence" "$release_work_dir/rendered"
  PRODUCTION_INPUTS_REPORT_FILE="$release_work_dir/evidence/production-inputs-$release.json"
  RENDERED_ALERT_RULES_FILE="$release_work_dir/rendered/alert_rules.yml"
  export PRODUCTION_INPUTS_REPORT_FILE RENDERED_ALERT_RULES_FILE
  validate_capacity_inputs
  python3 "$REPO_ROOT/scripts/production_inputs_gate.py" \
    --inputs "$inputs" \
    --git-sha "$APP_COMMIT_SHA" \
    --backend-image "$CYGNUS_API_IMAGE" \
    --frontend-image "$CYGNUS_FRONTEND_IMAGE" \
    --alembic-head "$EXPECTED_ALEMBIC_HEAD" \
    --domain "$CYGNUS_DOMAIN" \
    --public-origin "$public_origin" \
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
    --report "$PRODUCTION_INPUTS_REPORT_FILE"
  python3 "$REPO_ROOT/scripts/render_alert_rules.py" \
    --thresholds "$CYGNUS_ALERT_THRESHOLDS_FILE" \
    --approval-ref "$CYGNUS_ALERT_APPROVAL_REF" \
    --thresholds-ref "$CYGNUS_ALERT_THRESHOLDS_REF" \
    --thresholds-sha256 "$CYGNUS_ALERT_THRESHOLDS_SHA256" \
    --output "$RENDERED_ALERT_RULES_FILE" \
    --quiet || die "approved alert rule rendering failed"
  [ -s "$RENDERED_ALERT_RULES_FILE" ] || die "rendered alert rule file is empty"
}

validate_compose() {
  command -v docker >/dev/null 2>&1 || die "docker is required for production operations"
  "${COMPOSE[@]}" version >/dev/null 2>&1 || die "Docker Compose v2 is required for production operations"
  "${COMPOSE[@]}" config --quiet || die "production Compose manifest failed to resolve: $COMPOSE_FILE"
}

compose_pull() {
  "${COMPOSE[@]}" pull
}

compose_quiesce_backend() {
  local running service
  QUIESCED_BACKEND_SERVICES=()
  if ! running=$("${COMPOSE[@]}" ps --services --filter status=running "${PRODUCTION_BACKEND_SERVICES[@]}"); then
    die "could not determine the running backend container set"
  fi
  for service in "${PRODUCTION_BACKEND_SERVICES[@]}"; do
    if printf '%s\n' "$running" | grep -Fxq "$service"; then
      QUIESCED_BACKEND_SERVICES+=("$service")
    fi
  done
  if [ "${#QUIESCED_BACKEND_SERVICES[@]}" -eq 0 ]; then
    log "no running backend services require quiescence"
    return 0
  fi
  log "quiescing backend services: ${QUIESCED_BACKEND_SERVICES[*]}"
  "${COMPOSE[@]}" stop "${QUIESCED_BACKEND_SERVICES[@]}"
}

compose_resume_quiesced_backend() {
  [ "${#QUIESCED_BACKEND_SERVICES[@]}" -gt 0 ] || return 0
  log "resuming previously running backend services: ${QUIESCED_BACKEND_SERVICES[*]}"
  "${COMPOSE[@]}" start "${QUIESCED_BACKEND_SERVICES[@]}"
}

resume_backend_on_failure() {
  local status="${1:-1}"
  trap - EXIT
  if [ "$status" -ne 0 ] && [ "$BACKEND_RECOVERY_TRAP_ARMED" = 1 ]; then
    log "backend mutation failed; attempting to resume the previous container set..."
    if ! compose_resume_quiesced_backend; then
      printf '[cygnus-prod] ERROR: automatic backend resume failed; manual intervention is required\n' >&2
    fi
  fi
  exit "$status"
}

arm_backend_recovery_trap() {
  BACKEND_RECOVERY_TRAP_ARMED=1
  trap 'resume_backend_on_failure "$?"' EXIT
}

clear_backend_recovery_trap() {
  BACKEND_RECOVERY_TRAP_ARMED=0
  trap - EXIT
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
  local http_port="${CYGNUS_HTTP_BIND_PORT:-80}" https_port="${CYGNUS_HTTPS_BIND_PORT:-443}" ingress_origin
  [ -n "$domain" ] || die "verify_ingress: no domain"
  ingress_origin="https://$domain"
  [ "$https_port" = 443 ] || ingress_origin="$ingress_origin:$https_port"
  deadline=$(( $(date +%s) + timeout_seconds ))
  [ "$(curl -sS -o /dev/null -w '%{http_code}' --resolve "$domain:$http_port:127.0.0.1" --max-time 5 "http://$domain:$http_port/livez" || true)" = "301" ] || die "HTTP ingress must redirect /livez to HTTPS"
  while :; do
    if body=$(curl -fsS --resolve "$domain:$https_port:127.0.0.1" --max-time 10 "$ingress_origin/livez" 2>/dev/null) && printf '%s' "$body" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "alive"'; then
      break
    fi
    [ "$(date +%s)" -lt "$deadline" ] || die "TLS/API livez did not become healthy at $ingress_origin/livez"
    sleep "$interval"
  done
  while :; do
    if body=$(curl -fsS --resolve "$domain:$https_port:127.0.0.1" --max-time 10 "$ingress_origin/readyz" 2>/dev/null) && printf '%s' "$body" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ready"'; then
      log "ingress ready: $ingress_origin/readyz"
      return 0
    fi
    [ "$(date +%s)" -lt "$deadline" ] || die "TLS/API readyz did not become ready at $ingress_origin/readyz"
    sleep "$interval"
  done
}

validate_operator_state_paths() {
  local release="$1" state_parent link_parent expected_root current_root target inputs_target
  [ -d "$RELEASES_DIR" ] && [ -w "$RELEASES_DIR" ] || die "CYGNUS_RELEASES_DIR must be an existing writable protected directory: $RELEASES_DIR"
  state_parent=$(dirname "$STATE_FILE")
  [ -d "$state_parent" ] && [ -w "$state_parent" ] || die "CYGNUS_DEPLOY_STATE_FILE parent must be an existing writable protected directory"
  [ -n "$CHECKOUTS_DIR" ] && [ -d "$CHECKOUTS_DIR" ] || die "CYGNUS_CHECKOUTS_DIR must be an existing protected directory"
  [ -n "$ACTIVE_CHECKOUT_LINK" ] || die "CYGNUS_ACTIVE_CHECKOUT_LINK is required"
  link_parent=$(dirname "$ACTIVE_CHECKOUT_LINK")
  [ -d "$link_parent" ] && [ -w "$link_parent" ] || die "CYGNUS_ACTIVE_CHECKOUT_LINK parent must be an existing writable protected directory"
  if [ -e "$ACTIVE_CHECKOUT_LINK" ] && [ ! -L "$ACTIVE_CHECKOUT_LINK" ]; then
    die "CYGNUS_ACTIVE_CHECKOUT_LINK must be absent or a symbolic link"
  fi
  target="$RELEASES_DIR/$release.env"
  inputs_target="$RELEASES_DIR/$release.production-inputs.json"
  if [ -f "$target" ] && ! cmp -s "$LOADED_RELEASE_FILE" "$target"; then
    die "immutable release metadata conflict: $target"
  fi
  if [ -f "$inputs_target" ] && ! cmp -s "$LOADED_RELEASE_INPUTS_FILE" "$inputs_target"; then
    die "immutable release production-input conflict: $inputs_target"
  fi
  [ -d "$CHECKOUTS_DIR/$release" ] || die "release checkout is missing: $CHECKOUTS_DIR/$release"
  expected_root=$(CDPATH= cd -- "$CHECKOUTS_DIR/$release" && pwd -P)
  current_root=$(CDPATH= cd -- "$REPO_ROOT" && pwd -P)
  [ "$current_root" = "$expected_root" ] || die "release operations must run from $CHECKOUTS_DIR/$release"
}

activate_release_checkout() {
  local release="$1" target temporary
  target=$(CDPATH= cd -- "$CHECKOUTS_DIR/$release" && pwd -P)
  temporary="${ACTIVE_CHECKOUT_LINK}.tmp.$$"
  rm -f "$temporary"
  ln -s "$target" "$temporary"
  python3 -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' "$temporary" "$ACTIVE_CHECKOUT_LINK"
  log "active checkout: $ACTIVE_CHECKOUT_LINK -> $target"
}

persist_immutable_file() {
  local source="$1" target="$2" temporary
  if [ -f "$target" ]; then
    cmp -s "$source" "$target" || die "immutable release contract conflict: $target"
    return 0
  fi
  umask 027
  temporary=$(mktemp "$RELEASES_DIR/.$(basename "$target").XXXXXX")
  if ! cat "$source" > "$temporary"; then
    rm -f "$temporary"
    die "could not stage immutable release contract: $target"
  fi
  chmod 0640 "$temporary"
  mv "$temporary" "$target"
}

persist_release_metadata() {
  local release="$1"
  [ -n "${LOADED_RELEASE_FILE:-}" ] || die "no loaded release metadata is available to persist"
  [ -n "${LOADED_RELEASE_INPUTS_FILE:-}" ] || die "no release-bound production inputs are available to persist"
  [ -d "$RELEASES_DIR" ] && [ -w "$RELEASES_DIR" ] || die "CYGNUS_RELEASES_DIR must be an existing writable protected directory: $RELEASES_DIR"
  persist_immutable_file "$LOADED_RELEASE_FILE" "$RELEASES_DIR/$release.env"
  persist_immutable_file "$LOADED_RELEASE_INPUTS_FILE" "$RELEASES_DIR/$release.production-inputs.json"
}

save_state() {
  local previous="$1" active="$2" temporary
  [ -d "$(dirname "$STATE_FILE")" ] && [ -w "$(dirname "$STATE_FILE")" ] || die "CYGNUS_DEPLOY_STATE_FILE parent must be an existing writable protected directory"
  umask 077
  temporary="${STATE_FILE}.tmp.$$"
  printf 'CYGNUS_PREVIOUS_RELEASE=%s\nCYGNUS_ACTIVE_RELEASE=%s\n' "$previous" "$active" > "$temporary"
  mv "$temporary" "$STATE_FILE"
  log "state: previous=$previous active=$active"
}

load_state() { load_env_file "$STATE_FILE"; }
