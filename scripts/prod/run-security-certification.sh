#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$REPO_ROOT"
client_id=$(scripts/prod/certification-stack.sh oauth-provision --release "${CYGNUS_RELEASE:?CYGNUS_RELEASE is required}")
[ -n "$client_id" ] || { echo '[security-certification] OAuth provisioning returned no client id' >&2; exit 1; }
export CYGNUS_SECURITY_OAUTH_CLIENT_ID="$client_id"
exec uv run python scripts/prod/security-certification.py "$@"
