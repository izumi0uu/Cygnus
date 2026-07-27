#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-cygnus-smoke}
export COMPOSE_PROJECT_NAME

CYGNUS_DOCKER_POSTGRES_HOST_PORT=${CYGNUS_DOCKER_POSTGRES_HOST_PORT:-15432}
CYGNUS_DOCKER_REDIS_HOST_PORT=${CYGNUS_DOCKER_REDIS_HOST_PORT:-16379}
CYGNUS_DOCKER_MINIO_API_HOST_PORT=${CYGNUS_DOCKER_MINIO_API_HOST_PORT:-19000}
CYGNUS_DOCKER_MINIO_CONSOLE_HOST_PORT=${CYGNUS_DOCKER_MINIO_CONSOLE_HOST_PORT:-19001}
CYGNUS_DOCKER_API_HOST_PORT=${CYGNUS_DOCKER_API_HOST_PORT:-18077}
CYGNUS_DOCKER_FRONTEND_HOST_PORT=${CYGNUS_DOCKER_FRONTEND_HOST_PORT:-15173}
export CYGNUS_DOCKER_POSTGRES_HOST_PORT
export CYGNUS_DOCKER_REDIS_HOST_PORT
export CYGNUS_DOCKER_MINIO_API_HOST_PORT
export CYGNUS_DOCKER_MINIO_CONSOLE_HOST_PORT
export CYGNUS_DOCKER_API_HOST_PORT
export CYGNUS_DOCKER_FRONTEND_HOST_PORT

# The smoke stack is published on loopback. CI and developer environments may
# set a global proxy that cannot route those host ports, so explicitly preserve
# direct localhost access for every curl probe below.
NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,$NO_PROXY}"
no_proxy="$NO_PROXY"
export NO_PROXY no_proxy

BASE_URL=${CYGNUS_SMOKE_BASE_URL:-http://127.0.0.1:${CYGNUS_DOCKER_API_HOST_PORT}}
FRONTEND_URL=${CYGNUS_SMOKE_FRONTEND_URL:-http://127.0.0.1:${CYGNUS_DOCKER_FRONTEND_HOST_PORT}}
ADMIN_EMAIL=${CYGNUS_SMOKE_ADMIN_EMAIL:-admin@cygnus.local}
ADMIN_PASSWORD=${CYGNUS_SMOKE_ADMIN_PASSWORD:-admin123}
BUILD_FLAG=${CYGNUS_SMOKE_BUILD_FLAG-__CYGNUS_DEFAULT_BUILD__}
if [ "$BUILD_FLAG" = "__CYGNUS_DEFAULT_BUILD__" ]; then
  BUILD_FLAG="--build"
fi
KEEP_UP=${CYGNUS_SMOKE_KEEP_UP:-0}
START_TIMEOUT_SECONDS=${CYGNUS_SMOKE_START_TIMEOUT_SECONDS:-240}
SLEEP_SECONDS=${CYGNUS_SMOKE_POLL_INTERVAL_SECONDS:-3}

cleanup() {
  if [ "$KEEP_UP" = "1" ]; then
    echo "[docker-smoke] keeping compose stack up (COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME)"
    return
  fi

  echo "[docker-smoke] tearing down compose stack..."
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

docker compose down -v --remove-orphans >/dev/null 2>&1 || true

wait_for_url() {
  name=$1
  url=$2
  deadline=$(( $(date +%s) + START_TIMEOUT_SECONDS ))

  while :; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[docker-smoke] $name is reachable: $url"
      return 0
    fi

    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "[docker-smoke] timeout waiting for $name: $url" >&2
      docker compose ps >&2 || true
      docker compose logs --tail=200 >&2 || true
      return 1
    fi

    sleep "$SLEEP_SECONDS"
  done
}

echo "[docker-smoke] starting compose stack..."
if [ -n "${BUILD_FLAG:-}" ]; then
  docker compose up -d "$BUILD_FLAG"
else
  docker compose up -d
fi

wait_for_url "api health" "$BASE_URL/health"
wait_for_url "api detailed health" "$BASE_URL/api/health"
wait_for_url "frontend" "$FRONTEND_URL"

echo "[docker-smoke] checking service health payloads..."
health_json=$(curl -fsS "$BASE_URL/health")
api_health_json=$(curl -fsS "$BASE_URL/api/health")
frontend_html=$(curl -fsS "$FRONTEND_URL")

printf '%s' "$health_json" | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["status"]=="healthy", data; assert data["services"]["database"]=="healthy", data; assert data["services"]["redis"]=="healthy", data; assert data["services"]["minio"]=="healthy", data'
printf '%s' "$api_health_json" | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["api"]=="healthy", data; assert data["database"]=="healthy", data; assert data["worker"]=="healthy", data'
printf '%s' "$frontend_html" | grep -qi "<!doctype html"

echo "[docker-smoke] logging in with seeded admin..."
login_json=$(curl -fsS -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}")

token=$(printf '%s' "$login_json" | python3 -c 'import json,sys; data=json.load(sys.stdin); token=data.get("access_token"); assert token, data; print(token)')

me_json=$(curl -fsS "$BASE_URL/api/auth/me" \
  -H "Authorization: Bearer $token")

printf '%s' "$me_json" | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["email"], data; assert data["role"] in {"admin","employee"}, data'

echo "[docker-smoke] smoke gate passed"
