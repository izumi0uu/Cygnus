#!/usr/bin/env bash
# Create a real encrypted/signed production backup, restore it once into a
# disposable Docker-isolated target, and emit the only drill report accepted by
# the release gate. It intentionally has no local/default credentials or fake
# RPO/RTO values: missing protected-runner inputs abort before backup/restore.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ARTIFACT_DIR=${CYGNUS_CERTIFICATION_ARTIFACT_DIR:-"$REPO_ROOT/production/evidence"}

require() {
  local variable=$1
  [ -n "${!variable:-}" ] || { printf '[backup-drill] ERROR: %s is required\n' "$variable" >&2; exit 1; }
}
require_file() {
  require "$1"
  [ -r "${!1}" ] || { printf '[backup-drill] ERROR: %s must name a readable external file\n' "$1" >&2; exit 1; }
}
sha256_file() { python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"; }
boolean_option() {
  case "$2" in
    true) printf '%s' "$1" ;;
    false) printf '%s' "--no-${1#--}" ;;
    *) printf '[backup-drill] ERROR: expected boolean true/false, got %s\n' "$2" >&2; exit 1 ;;
  esac
}

for variable in CYGNUS_RELEASE CYGNUS_PRODUCTION_ENV_FILE CYGNUS_RELEASE_METADATA_FILE CYGNUS_EXPECTED_GIT_SHA CYGNUS_EXPECTED_BACKEND_IMAGE CYGNUS_EXPECTED_FRONTEND_IMAGE CYGNUS_EXPECTED_ALEMBIC_HEAD; do
  require "$variable"
done

# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
[ -r "$CYGNUS_PRODUCTION_ENV_FILE" ] || die "CYGNUS_PRODUCTION_ENV_FILE must be a readable protected-runner file"
[ -r "$CYGNUS_RELEASE_METADATA_FILE" ] || die "CYGNUS_RELEASE_METADATA_FILE must be a readable protected-runner file"
validate_release_identifier "$CYGNUS_RELEASE"
load_env_file "$CYGNUS_PRODUCTION_ENV_FILE"
load_env_file "$CYGNUS_RELEASE_METADATA_FILE"
validate_digests "$CYGNUS_RELEASE"
validate_identity "$CYGNUS_RELEASE"
[ "$APP_COMMIT_SHA" = "$CYGNUS_EXPECTED_GIT_SHA" ] || die "backup release commit does not match the CI candidate"
[ "$CYGNUS_API_IMAGE" = "$CYGNUS_EXPECTED_BACKEND_IMAGE" ] || die "backup backend image does not match the CI candidate"
[ "$CYGNUS_FRONTEND_IMAGE" = "$CYGNUS_EXPECTED_FRONTEND_IMAGE" ] || die "backup frontend image does not match the CI candidate"
[ "$EXPECTED_ALEMBIC_HEAD" = "$CYGNUS_EXPECTED_ALEMBIC_HEAD" ] || die "backup Alembic head does not match the CI candidate"
validate_secrets
validate_resources
validate_production_inputs "$CYGNUS_RELEASE"
for variable in CYGNUS_BACKUP_OUTPUT_BASE CYGNUS_BACKUP_SOURCE_ID CYGNUS_RPO_OBJECTIVE_REF CYGNUS_RTO_OBJECTIVE_REF CYGNUS_BACKUP_AGE_RECIPIENT CYGNUS_BACKUP_DATABASE_URL CYGNUS_BACKUP_MINIO_ENDPOINT CYGNUS_BACKUP_MINIO_ACCESS_KEY CYGNUS_BACKUP_MINIO_SECRET_KEY CYGNUS_BACKUP_MINIO_BUCKET CYGNUS_BACKUP_MINIO_SECURE CYGNUS_DRILL_COMPOSE_FILE CYGNUS_DRILL_COMPOSE_ENV_FILE CYGNUS_DRILL_COMPOSE_PROJECT_DIRECTORY CYGNUS_DRILL_POSTGRES_USER CYGNUS_DRILL_POSTGRES_DB CYGNUS_DRILL_DATABASE_URL CYGNUS_DRILL_REDIS_URL CYGNUS_DRILL_MINIO_ENDPOINT CYGNUS_DRILL_MINIO_ACCESS_KEY CYGNUS_DRILL_MINIO_SECRET_KEY CYGNUS_DRILL_MINIO_BUCKET CYGNUS_DRILL_MINIO_SECURE CYGNUS_DRILL_ID CYGNUS_APPROVED_RPO_SECONDS CYGNUS_APPROVED_RTO_SECONDS; do
  require "$variable"
done
for variable in CYGNUS_BACKUP_AGE_IDENTITY_FILE CYGNUS_BACKUP_SIGNING_KEY_FILE CYGNUS_BACKUP_SIGNING_PUBLIC_KEY_FILE CYGNUS_BACKUP_KEY_MATERIAL_FILE; do
  require_file "$variable"
done

printf '%s' "$CYGNUS_BACKUP_AGE_RECIPIENT" | grep -Eq '^age1[0-9a-z]+$' || die "CYGNUS_BACKUP_AGE_RECIPIENT must be an age recipient"
for value in CYGNUS_BACKUP_MINIO_SECURE CYGNUS_DRILL_MINIO_SECURE; do
  case "${!value}" in true|false) ;; *) die "$value must be literal true or false" ;; esac
done
printf '%s' "$CYGNUS_APPROVED_RPO_SECONDS" | grep -Eq '^[0-9]+([.][0-9]+)?$' || die "CYGNUS_APPROVED_RPO_SECONDS must be positive numeric"
printf '%s' "$CYGNUS_APPROVED_RTO_SECONDS" | grep -Eq '^[0-9]+([.][0-9]+)?$' || die "CYGNUS_APPROVED_RTO_SECONDS must be positive numeric"
case "$CYGNUS_APPROVED_RPO_SECONDS" in 0|0.0|0.00|0.000) die "CYGNUS_APPROVED_RPO_SECONDS must be greater than zero" ;; esac
case "$CYGNUS_APPROVED_RTO_SECONDS" in 0|0.0|0.00|0.000) die "CYGNUS_APPROVED_RTO_SECONDS must be greater than zero" ;; esac

mkdir -p "$ARTIFACT_DIR" "$CYGNUS_BACKUP_OUTPUT_BASE"
backup_dir="$CYGNUS_BACKUP_OUTPUT_BASE/$(date -u +%Y%m%dT%H%M%SZ)-${APP_COMMIT_SHA:0:12}"
quiesce="docker compose --project-directory ${REPO_ROOT} --project-name cygnus-prod -f ${REPO_ROOT}/deploy/docker-compose.prod.yml --env-file ${CYGNUS_PRODUCTION_ENV_FILE} --env-file ${CYGNUS_RELEASE_METADATA_FILE} stop api worker worker-skills"
resume="docker compose --project-directory ${REPO_ROOT} --project-name cygnus-prod -f ${REPO_ROOT}/deploy/docker-compose.prod.yml --env-file ${CYGNUS_PRODUCTION_ENV_FILE} --env-file ${CYGNUS_RELEASE_METADATA_FILE} start api worker worker-skills"

source_minio_secure=$(boolean_option --minio-secure "$CYGNUS_BACKUP_MINIO_SECURE")
uv run python -m cygnus.runtime.backup_restore backup \
  --output-dir "$backup_dir" \
  --database-url "$CYGNUS_BACKUP_DATABASE_URL" \
  --minio-endpoint "$CYGNUS_BACKUP_MINIO_ENDPOINT" \
  --minio-access-key "$CYGNUS_BACKUP_MINIO_ACCESS_KEY" \
  --minio-secret-key "$CYGNUS_BACKUP_MINIO_SECRET_KEY" \
  --minio-bucket "$CYGNUS_BACKUP_MINIO_BUCKET" \
  "$source_minio_secure" \
  --environment production --source-id "$CYGNUS_BACKUP_SOURCE_ID" \
  --git-commit "$APP_COMMIT_SHA" --backend-image-ref "$CYGNUS_API_IMAGE" --frontend-image-ref "$CYGNUS_FRONTEND_IMAGE" --alembic-head "$EXPECTED_ALEMBIC_HEAD" \
  --quiesce-command "$quiesce" --resume-command "$resume" --retention-label release-certification \
  --artifact-encrypt-command "age --encrypt -r ${CYGNUS_BACKUP_AGE_RECIPIENT} -o {output} {input}" \
  --artifact-decrypt-command "age --decrypt -i ${CYGNUS_BACKUP_AGE_IDENTITY_FILE} -o {output} {input}" \
  --manifest-encrypt-command "age --encrypt -r ${CYGNUS_BACKUP_AGE_RECIPIENT} -o {output} {input}" \
  --manifest-decrypt-command "age --decrypt -i ${CYGNUS_BACKUP_AGE_IDENTITY_FILE} -o {output} {input}" \
  --manifest-sign-command "openssl dgst -sha256 -sign ${CYGNUS_BACKUP_SIGNING_KEY_FILE} -out {signature} {input}" \
  --manifest-verify-command "openssl dgst -sha256 -verify ${CYGNUS_BACKUP_SIGNING_PUBLIC_KEY_FILE} -signature {signature} {input}" \
  --report-file "$ARTIFACT_DIR/cygnus.backup.report.json"

[ -r "$CYGNUS_DRILL_COMPOSE_FILE" ] || die "CYGNUS_DRILL_COMPOSE_FILE must be a readable isolated-target Compose file"
[ -r "$CYGNUS_DRILL_COMPOSE_ENV_FILE" ] || die "CYGNUS_DRILL_COMPOSE_ENV_FILE must be a readable isolated-target env file"
[ -d "$CYGNUS_DRILL_COMPOSE_PROJECT_DIRECTORY" ] || die "CYGNUS_DRILL_COMPOSE_PROJECT_DIRECTORY must be an existing directory"
[ "$(realpath "$CYGNUS_DRILL_COMPOSE_FILE")" != "$(realpath "$COMPOSE_FILE")" ] || die "drill Compose file must never be the production manifest"
DRILL_COMPOSE=(docker compose --project-directory "$CYGNUS_DRILL_COMPOSE_PROJECT_DIRECTORY" --project-name cygnus-drill -f "$CYGNUS_DRILL_COMPOSE_FILE" --env-file "$CYGNUS_DRILL_COMPOSE_ENV_FILE")
cleanup_drill() { "${DRILL_COMPOSE[@]}" down -v || true; }
trap cleanup_drill EXIT
"${DRILL_COMPOSE[@]}" up -d --wait postgres redis minio
"${DRILL_COMPOSE[@]}" exec -T postgres createdb -U "$CYGNUS_DRILL_POSTGRES_USER" "$CYGNUS_DRILL_POSTGRES_DB"
uv run python "$REPO_ROOT/scripts/create_isolated_minio_bucket.py" --endpoint "$CYGNUS_DRILL_MINIO_ENDPOINT" --access-key "$CYGNUS_DRILL_MINIO_ACCESS_KEY" --secret-key "$CYGNUS_DRILL_MINIO_SECRET_KEY" --bucket "$CYGNUS_DRILL_MINIO_BUCKET" --secure "$CYGNUS_DRILL_MINIO_SECURE"
case "$CYGNUS_DRILL_REDIS_URL" in */0|*/0\?*) die "CYGNUS_DRILL_REDIS_URL must select a dedicated nonzero Redis database" ;; esac

target_minio_secure=$(boolean_option --target-minio-secure "$CYGNUS_DRILL_MINIO_SECURE")
uv run python -m cygnus.runtime.backup_restore drill \
  --backup-dir "$backup_dir" \
  --target-database-url "$CYGNUS_DRILL_DATABASE_URL" \
  --target-redis-url "$CYGNUS_DRILL_REDIS_URL" \
  --target-minio-endpoint "$CYGNUS_DRILL_MINIO_ENDPOINT" \
  --target-minio-access-key "$CYGNUS_DRILL_MINIO_ACCESS_KEY" \
  --target-minio-secret-key "$CYGNUS_DRILL_MINIO_SECRET_KEY" \
  --target-minio-bucket "$CYGNUS_DRILL_MINIO_BUCKET" \
  "$target_minio_secure" \
  --target-environment isolated --target-id "$CYGNUS_DRILL_ID" --confirm-target "$CYGNUS_DRILL_ID" \
  --key-material-file "$CYGNUS_BACKUP_KEY_MATERIAL_FILE" \
  --artifact-decrypt-command "age --decrypt -i ${CYGNUS_BACKUP_AGE_IDENTITY_FILE} -o {output} {input}" \
  --manifest-decrypt-command "age --decrypt -i ${CYGNUS_BACKUP_AGE_IDENTITY_FILE} -o {output} {input}" \
  --manifest-verify-command "openssl dgst -sha256 -verify ${CYGNUS_BACKUP_SIGNING_PUBLIC_KEY_FILE} -signature {signature} {input}" \
  --require-recovery-objectives --rpo-max-seconds "$CYGNUS_APPROVED_RPO_SECONDS" --rto-max-seconds "$CYGNUS_APPROVED_RTO_SECONDS" \
  --rpo-objective-ref "$CYGNUS_RPO_OBJECTIVE_REF" --rto-objective-ref "$CYGNUS_RTO_OBJECTIVE_REF" \
  --expected-git-commit "$APP_COMMIT_SHA" --expected-backend-image-ref "$CYGNUS_API_IMAGE" --expected-frontend-image-ref "$CYGNUS_FRONTEND_IMAGE" --expected-alembic-head "$EXPECTED_ALEMBIC_HEAD" \
  --report-file "$ARTIFACT_DIR/cygnus.drill.report.json"

python3 "$REPO_ROOT/scripts/write_evidence.py" backup-restore-drill --passed --git-sha "$APP_COMMIT_SHA" --tool "backup_restore drill" \
  --check "report_sha256=$(sha256_file "$ARTIFACT_DIR/cygnus.drill.report.json")" \
  --check "source_identity=$CYGNUS_BACKUP_SOURCE_ID" \
  --check "rpo_objective_ref=$CYGNUS_RPO_OBJECTIVE_REF" \
  --check "rto_objective_ref=$CYGNUS_RTO_OBJECTIVE_REF" \
  --check "rpo_max_seconds=$CYGNUS_APPROVED_RPO_SECONDS" \
  --check "rto_max_seconds=$CYGNUS_APPROVED_RTO_SECONDS" \
  --out "$ARTIFACT_DIR/backup-restore-drill.json"
printf '[backup-drill] encrypted backup and isolated drill evidence written to %s\n' "$ARTIFACT_DIR"
