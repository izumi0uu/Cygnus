# Cygnus Backup / Restore / Recovery Drill Runbook

**CYG-132 · Production V1 operator recovery.** This runbook documents the
exact, automatable commands for creating a coordinated application-level backup
package, verifying it, restoring it into a disposable target, and running a
measured recovery drill. Every command is **fail closed**: missing, corrupt, or
key-mismatched backup state blocks the operation with a machine-readable error.

Implementation: `cygnus/runtime/backup_restore.py` (CLI entry point
`python -m cygnus.runtime.backup_restore`).

Chinese counterpart: [备份 / 恢复 / 演练 Runbook](../zh/backup-restore-runbook.md). Both language tracks describe the same release-identity, encrypted backup, isolated restore, and measured drill contract.

---

## 1. Guarantees

- The backup package is **atomic**: it is assembled in a staging directory and
  renamed into place only after the manifest and completion marker are written.
  A failed backup leaves no package behind and runs the operator resume command.
- The backup is a **consistent application-level snapshot** taken under an
  operator **quiesce barrier**: the operator-supplied quiesce command stops
  write paths, then the tool takes the `pg_dump` snapshot, copies the MinIO
  object inventory, records encrypted-config key fingerprints, the release /
  Alembic head, and checksums — and only then runs the resume command.
- **Redis/ARQ payloads are excluded by design.** Redis is ephemeral transport;
  committed PostgreSQL outbox rows are the recovery source of truth. A restore
  flushes the isolated target Redis database and replays the recorded durable
  reconcilers (deterministic ARQ job IDs make replay idempotent).
- **No plaintext key material is ever archived.** Only SHA-256 fingerprints of
  `runtime.secret_key` and `runtime.mcp_token_pepper` are recorded; a restore
  refuses to proceed unless the supplied key material matches the fingerprints.
- **Destructive restore only accepts an explicit empty disposable target**
  (empty target database, empty target bucket, `target_id` distinct from the
  source identity, and an exact `--confirm-target`). Production restores
  additionally require `--allow-production-restore` and an encrypted, signed
  manifest.
- The **drill report is machine-readable** and carries **measured RPO/RTO
  fields only**. Unmeasured values are reported as `"measured": false` with
  `null` seconds — never invented, never defaulted to zero.

## 2. Package format (`cygnus-coordinated-backup/v1`)

```
<backup-dir>/
  COMPLETE                    # completion marker; pins manifest envelope sha256
  manifest.envelope.json      # names the manifest artifact + its sha256/bytes
  manifest.json               # (or manifest.json.enc for encrypted backups)
  manifest.sig                # (optional) signature over the manifest artifact
  database.dump               # (or .enc) pg_dump --format=custom
  objects/00000001.blob       # (or .enc) one file per MinIO object
```

The manifest records:

- `source` — environment + source identity.
- `consistency_boundary` — quiesce/dump timestamps and the
  **measured RPO upper bound** (`measured_rpo_upper_bound_seconds`).
- `database` — artifact checksums (`sha256`, `bytes`, plaintext
  `payload_sha256`/`payload_bytes`), `database_revisions`, `repository_heads`.
- `objects` — per-object `object_key`, content type, metadata, source ETag,
  and artifact checksums.
- `configuration_inventory` — runtime setting names and the sensitive
  `app_config` keys that were encrypted at rest.
- `key_material` — SHA-256 fingerprints of the key material required to decrypt
  persisted encrypted settings and validate MCP token hashes.
- `queue_reconciliation` — Redis policy and the recorded durable reconcilers.
- `verification` — table row-count baseline and FK constraint count sampled
  under the same quiesce, used by drills to prove restored counts match.

## 3. Prerequisites

- `psql`, `pg_dump`, `pg_restore` on `PATH` (PostgreSQL 15+).
- Runtime dependencies via `uv run` (or an activated project venv).
- MinIO credentials and bucket; Redis URL for the target.
- For production backups: encryption + signing command templates
  (see §4.2). The commands are executed as argv templates **without a shell**,
  so never rely on shell operators inside them.
- The source database must be at the checked-out Alembic head; backups refuse
  a database that is not (`database_not_at_repository_head`).

## 4. Backup

### 4.1 Development / staging (unencrypted package)

```bash
uv run python -m cygnus.runtime.backup_restore backup \
  --output-dir "/var/backups/cygnus/$(date -u +%Y%m%dT%H%M%SZ)" \
  --environment staging \
  --source-id "staging-01" \
  --quiesce-command "docker compose stop api worker worker-skills" \
  --resume-command  "docker compose start api worker worker-skills" \
  --retention-label daily \
  --report-file /var/backups/cygnus/backup-report.json
```

- Database URL: `--database-url` or `CYGNUS_BACKUP_DATABASE_URL`; defaults to
  runtime settings.
- MinIO: `--minio-{endpoint,access-key,secret-key,bucket}` or
  `CYGNUS_BACKUP_MINIO_*`; defaults to runtime settings.
- The quiesce command must stop every write path (API, workers, scheduled
  crons). The tool runs it, snapshots, and runs the resume command in a
  `finally` block even on failure.
- `--quiesce-command "true"` / `--resume-command "true"` are valid for a
  development stack where no barrier is needed, but are **not** acceptable for
  production.
- Exit code `0` with `"status": "completed"`; any failure produces a
  machine-readable report with `"status": "failed"` and a non-zero exit.

### 4.2 Production (encrypted + signed, required)

Production backups **refuse to run without** artifact encryption, manifest
encryption, manifest signing, and complete immutable release identity.

```bash
export CYGNUS_REPO=/srv/cygnus
export CYGNUS_RELEASE=2026.08.15.1  # must name deploy/releases/<version>.env
export CYGNUS_RELEASE_GIT_COMMIT="$(git rev-parse HEAD)" # full commit only
export CYGNUS_RELEASE_BACKEND_IMAGE_REF="registry.example/cygnus-api@sha256:REPLACE_WITH_DEPLOYED_DIGEST"
export CYGNUS_RELEASE_FRONTEND_IMAGE_REF="registry.example/cygnus-web@sha256:REPLACE_WITH_DEPLOYED_DIGEST"
export CYGNUS_RELEASE_ALEMBIC_HEAD="REPLACE_WITH_DEPLOYED_ALEMBIC_HEAD"
cd "$CYGNUS_REPO"

uv run python -m cygnus.runtime.backup_restore backup \
  --output-dir "/var/backups/cygnus/$(date -u +%Y%m%dT%H%M%SZ)" \
  --environment production \
  --source-id "prod-01" \
  --git-commit "$CYGNUS_RELEASE_GIT_COMMIT" \
  --backend-image-ref "$CYGNUS_RELEASE_BACKEND_IMAGE_REF" \
  --frontend-image-ref "$CYGNUS_RELEASE_FRONTEND_IMAGE_REF" \
  --alembic-head "$CYGNUS_RELEASE_ALEMBIC_HEAD" \
  --quiesce-command "docker compose --project-directory ${CYGNUS_REPO} --project-name cygnus-prod -f ${CYGNUS_REPO}/deploy/docker-compose.prod.yml --env-file ${CYGNUS_REPO}/deploy/.env.prod --env-file ${CYGNUS_REPO}/deploy/releases/${CYGNUS_RELEASE}.env stop api worker worker-skills" \
  --resume-command  "docker compose --project-directory ${CYGNUS_REPO} --project-name cygnus-prod -f ${CYGNUS_REPO}/deploy/docker-compose.prod.yml --env-file ${CYGNUS_REPO}/deploy/.env.prod --env-file ${CYGNUS_REPO}/deploy/releases/${CYGNUS_RELEASE}.env start api worker worker-skills" \
  --retention-label daily \
  --artifact-encrypt-command  "age --encrypt -r age1xxxxxxxx -o {output} {input}" \
  --artifact-decrypt-command  "age --decrypt -i /run/secrets/cygnus-backup-age.txt -o {output} {input}" \
  --manifest-encrypt-command  "age --encrypt -r age1xxxxxxxx -o {output} {input}" \
  --manifest-decrypt-command  "age --decrypt -i /run/secrets/cygnus-backup-age.txt -o {output} {input}" \
  --manifest-sign-command     "openssl dgst -sha256 -sign /run/secrets/cygnus-backup-sign.key -out {signature} {input}" \
  --manifest-verify-command   "openssl dgst -sha256 -verify /run/secrets/cygnus-backup-sign.pub -signature {signature} {input}" \
  --report-file /var/backups/cygnus/backup-report.json
```

The outer shell expands `CYGNUS_REPO` and `CYGNUS_RELEASE` before the CLI receives
the argv template. `backup_restore` deliberately does **not** invoke a shell for
the template, so retain the absolute compose file, project directory, production
project name, and both environment files; a bare `docker compose` would target
the caller's local compose stack instead of production.

Placeholders: `{input}`/`{output}` for encryption/decryption,
`{input}`/`{signature}` for signing/verification. Each command runs without a
shell; `openssl dgst` and `age` are used because they need no redirection.

## 5. Inventory / verification

Validates envelope + completion markers, artifact checksums, plaintext payload
checksums, and (with `--key-material-file`) key fingerprints — **before** any
destructive step:

```bash
uv run python -m cygnus.runtime.backup_restore inventory \
  --backup-dir /var/backups/cygnus/20260812T000000Z \
  --key-material-file /run/secrets/cygnus-key-material.json \
  --report-file /var/backups/cygnus/inventory-report.json
```

`/run/secrets/cygnus-key-material.json`:

```json
{
  "runtime.secret_key": "<same secret the source runtime used>",
  "runtime.mcp_token_pepper": "<same pepper the source runtime used>"
}
```

A tampered artifact that even re-signs the manifest fails at the plaintext
checksum layer (`artifact_plaintext_checksum_mismatch`); a wrong secret fails
with `key_material_precondition_failed`.

## 6. Restore (destructive)

> Restore is destructive and **only** accepts an empty disposable target:
> zero tables in the target database, zero objects in the target bucket,
> `--target-id` distinct from the backup's source identity, and
> `--confirm-target` matching `--target-id` exactly. Violations abort before
> anything is written. Use `--dry-run` first — it performs all read-only
> preflight checks (package validation, key fingerprints, revision
> compatibility, empty-target checks) and reports the plan.

```bash
uv run python -m cygnus.runtime.backup_restore restore \
  --backup-dir /var/backups/cygnus/20260812T000000Z \
  --target-database-url "postgresql+asyncpg://cygnus:CHANGE_ME@restore-host:5432/cygnus_restore" \
  --target-redis-url "redis://:CHANGE_ME@restore-host:6379/14" \
  --target-minio-endpoint "restore-minio:9000" \
  --target-minio-access-key "CHANGE_ME" \
  --target-minio-secret-key "CHANGE_ME" \
  --target-minio-bucket "cygnus-restore" \
  --target-environment isolated \
  --target-id "restore-20260812" \
  --confirm-target "restore-20260812" \
  --key-material-file /run/secrets/cygnus-key-material.json \
  --report-file /var/backups/cygnus/restore-report.json
```

For an encrypted backup add the matching `--artifact-decrypt-command`,
`--manifest-decrypt-command`, and `--manifest-verify-command`. Production
restores additionally require `--allow-production-restore` **and** an
encrypted, signed manifest; treat that path as a last resort.

What a restore does, in order:

1. Preflight: envelope/checksum validation, key fingerprint match, Alembic
   revision compatibility, plaintext checksum validation, `pg_restore --list`.
2. Empty-target guard (database + bucket) — read-only, also enforced in
   `--dry-run`.
3. `pg_restore` with `--exit-on-error`; verify restored Alembic revisions.
4. Restore every MinIO object; **read each object back and hash it** against
   the manifest.
5. Apply forward Alembic migrations.
6. Reconcile object references (sources/source_images/skills/skill_versions/
   skill_contributions → bucket keys).
7. Flush the target Redis database and replay the recorded durable outbox
   reconcilers **in a fresh interpreter pointed at the target**, so a restore
   can never sweep the source runtime's queues.

## 7. Recovery drill (measured PASS/FAIL)

A drill runs the full destructive restore into a disposable isolated target and
then measures recovery evidence. It is the acceptance proof for CYG-132.

For release evidence, the backup manifest and drill report must bind the exact
source environment/id, full Git commit, immutable backend/frontend `@sha256`
image references, and Alembic head. Set the following values from the approved
release record; the placeholders below are intentionally not usable values:

```bash
export CYGNUS_APPROVED_RPO_OBJECTIVE_REF="<approved-RPO-objective-reference>"
export CYGNUS_APPROVED_RTO_OBJECTIVE_REF="<approved-RTO-objective-reference>"
```

```bash
uv run python -m cygnus.runtime.backup_restore drill \
  --backup-dir /var/backups/cygnus/20260812T000000Z \
  --target-database-url "postgresql+asyncpg://cygnus:CHANGE_ME@drill-host:5432/cygnus_drill" \
  --target-redis-url "redis://:CHANGE_ME@drill-host:6379/14" \
  --target-minio-endpoint "drill-minio:9000" \
  --target-minio-access-key "CHANGE_ME" \
  --target-minio-secret-key "CHANGE_ME" \
  --target-minio-bucket "cygnus-drill" \
  --target-environment isolated \
  --target-id "drill-20260812" \
  --confirm-target "drill-20260812" \
  --key-material-file /run/secrets/cygnus-key-material.json \
  --require-recovery-objectives \
  --rpo-max-seconds 60 \
  --rto-max-seconds 1800 \
  --rpo-objective-ref "$CYGNUS_APPROVED_RPO_OBJECTIVE_REF" \
  --rto-objective-ref "$CYGNUS_APPROVED_RTO_OBJECTIVE_REF" \
  --expected-git-commit "$CYGNUS_RELEASE_GIT_COMMIT" \
  --expected-backend-image-ref "$CYGNUS_RELEASE_BACKEND_IMAGE_REF" \
  --expected-frontend-image-ref "$CYGNUS_RELEASE_FRONTEND_IMAGE_REF" \
  --expected-alembic-head "$CYGNUS_RELEASE_ALEMBIC_HEAD" \
  --report-file /var/backups/cygnus/drill-report.json
```

- Exit code `0` = `"status": "passed"`, `1` = `"status": "failed"` — safe to
  wire into CI/alerting.
- A production-source backup automatically requires numeric objectives **and**
  non-empty `--rpo-objective-ref` / `--rto-objective-ref` before any restore
  write. A release gate must also pass `--require-recovery-objectives` and all
  four `--expected-*` identity fields. Missing values, a missing manifest
  identity, or an identity mismatch fails before restore and is never release
  evidence. The tool only binds the operator-supplied objective references; it
  cannot fabricate or independently approve those external records.
- Without that flag, a non-production integrity drill may omit objectives, but
  its passing status is not production/release certification.
- When objectives are supplied, a measured value above either objective (or an
  RPO that cannot be measured) fails closed.
- A drill only runs against `--target-environment isolated`; production
  targets are refused (`drill_target_must_be_isolated`).

### Drill report schema (`cygnus-drill-report/v1`)

```jsonc
{
  "report_format": "cygnus-drill-report/v1",
  "operation": "drill",
  "status": "passed",                      // or "failed"
  "backup_dir": "/var/backups/cygnus/20260812T000000Z",
  "backup_created_at": "2026-08-12T00:00:00+00:00",
  "source": {"environment": "production", "identity": "prod-01"},
  "release_identity": {
    "git_commit": "<full-40-or-64-character-commit>",
    "backend_image_ref": "<backend>@sha256:<64-hex-digest>",
    "frontend_image_ref": "<frontend>@sha256:<64-hex-digest>",
    "alembic_head": "<exact-backed-up-head>"
  },
  "release_identity_requirement": {
    "manifest_required": true,
    "expected_match_required": true,
    "expected_match_verified": true
  },
  "target": {"environment": "isolated", "identity": "drill-20260812"},
  "rpo": {
    "measured": true,                      // false + null seconds = never claimed
    "seconds": 0.45,
    "basis": "quiesce_completed_to_dump_started",
    "measured_at": "backup"
  },
  "rto": {
    "measured": true,
    "seconds": 42.7,
    "basis": "restore_start_to_verification_complete",
    "measured_at": "drill"
  },
  "objectives": {"rpo_max_seconds": 60, "rto_max_seconds": 1800},
  "objective_refs": {
    "rpo_objective_ref": "<approved-RPO-objective-reference>",
    "rto_objective_ref": "<approved-RTO-objective-reference>"
  },
  "objective_requirement": {
    "required": true,
    "source": "explicit_release_mode",
    "both_declared": true
  },
  "verification": {
    "table_row_counts": {"baseline_tables": 23, "checked": 23, "matched": 23, "mismatches": []},
    "object_hashes":    {"checked": 12, "matched": 12, "mismatches": []},
    "foreign_keys":     {"constraints_checked": 31, "orphan_rows": 0, "orphans": []},
    "idempotency_receipts": {
      "ledger_event_duplicate_idempotency_keys": [],
      "ledger_event_count": {"expected": 5, "actual": 5, "matched": true, "measured": true},
      "outbox_job_id_duplicates": [],
      "outbox_row_count": {"expected": 2, "actual": 2, "matched": true, "measured": true}
    },
    "pending_jobs": {"nonterminal_outbox_rows_after_replay": 0, "checked_statuses": ["pending", "dispatching"]},
    "redis": {"dbsize": 3, "arq_key_count": 2, "expected_arq_job_ids": 1, "enqueued_outbox_without_arq_job": []},
    "encrypted_config": {"checked": true, "sensitive_keys_checked": 2, "decrypt_ok": 2, "decrypt_failures": []}
  },
  "restore": {"completed_stages": ["database_restored", "objects_restored", "forward_migrations_applied", "object_references_reconciled", "durable_outboxes_replayed"], "object_count": 12},
  "checks": [
    {"name": "table_row_counts", "passed": true, "detail": "23/23 tables matched"},
    {"name": "object_hashes", "passed": true, "detail": "12/12 objects matched"},
    {"name": "foreign_key_integrity", "passed": true, "detail": "31 constraints checked, 0 orphan rows"},
    {"name": "idempotency_receipts", "passed": true, "detail": "0 duplicate ledger idempotency keys, 0 duplicate outbox job ids, ledger rows matched, outbox rows matched"},
    {"name": "pending_jobs_replayed", "passed": true, "detail": "0 non-terminal outbox rows remain after replay"},
    {"name": "redis_replay", "passed": true, "detail": "dbsize=3, arq keys=2, expected=1, missing=[]"},
    {"name": "encrypted_config_continuity", "passed": true, "detail": "2/2 sensitive values decrypt"},
    {"name": "rpo_objective", "passed": true, "detail": "measured rpo 0.45s (max 60s)"},
    {"name": "rto_objective", "passed": true, "detail": "measured rto 42.7s (max 1800s)"}
  ],
  "generated_at": "2026-08-12T01:00:00+00:00"
}
```

### What each check proves

- `table_row_counts` — every public table's restored row count matches the
  count baseline sampled into the manifest under quiesce.
- `object_hashes` — every object re-read from the target bucket hashes to the
  manifest plaintext checksum.
- `foreign_key_integrity` — a generic MATCH SIMPLE orphan scan per validated FK
  constraint in `public` reports zero orphaned rows.
- `idempotency_receipts` — `governance_ledger_events.idempotency_key` and
  `wiki_draft_ai_pre_review_dispatches.job_id` have zero duplicates and the row
  counts match the backup — replay produced no duplicated side effects.
- `pending_jobs_replayed` — no outbox rows remain `pending`/`dispatching` after
  the durable reconcilers ran.
- `redis_replay` — the target Redis database was flushed and every
  `enqueued` outbox row has a matching `arq:job:<id>` key.
- `encrypted_config_continuity` — the supplied `runtime.secret_key` decrypts
  every restored sensitive `app_config` value (the same key whose fingerprint
  was recorded in the backup).

### RPO / RTO semantics (measured, never invented)

- **RPO** is measured at **backup time** as
  `dump_started_at − quiesce_completed_at`: the operator-quiesce window that
  precedes the `pg_dump` snapshot, i.e. the upper bound on data age in the
  backup. It is stored in the manifest
  (`consistency_boundary.measured_rpo_upper_bound_seconds`) and reported by the
  drill with `"basis": "quiesce_completed_to_dump_started"`.
- **RTO** is measured at **drill time** as wall-clock time from restore start
  through verification completion (`restore_start_to_verification_complete`).
- When a value cannot be measured (old package without boundary timestamps,
  no secret supplied, no baseline), the field is reported as
  `"measured": false` with `"seconds": null` and a `reason`. It is **never**
  replaced with a default or estimate. With an objective set, an unmeasurable
  value fails the drill.

## 8. Key continuity

`runtime.secret_key` encrypts sensitive `app_config` values (Fernet) and signs
JWTs; `runtime.mcp_token_pepper` hashes MCP bearer tokens at rest. Both must be
stable across the source and the restore target:

- Backup records only SHA-256 fingerprints.
- Restore/drill/inventory-with-key-file require the actual values; a missing,
  wrong, or partially supplied key set aborts with
  `key_material_precondition_failed` (details list per-key reasons:
  `missing`, `fingerprint_mismatch`).
- Rotating `secret_key` after a backup invalidates that backup's encrypted
  config continuity; rotate keys first, then take a new backup.

## 9. Fail-closed error codes

| Code | Meaning / operator action |
| --- | --- |
| `required_backup_file_missing` / `backup_json_invalid` | Package structure corrupt; do not restore. |
| `completion_marker_checksum_mismatch` / `manifest_checksum_mismatch` | Package tampered or truncated; do not restore. |
| `backup_artifact_validation_failed` / `artifact_plaintext_checksum_mismatch` | Artifact missing/corrupt (even if re-signed); do not restore. |
| `key_material_precondition_failed` | Supplied keys do not match the backup fingerprint; supply the source keys. |
| `database_not_at_repository_head` / `backup_revision_unknown` | Backup refuses a DB off-head, or the package revision is absent from this checkout; run migrations/checkout matching version. |
| `release_identity_required` / `release_identity_mismatch` / `release_alembic_head_mismatch` / `release_git_commit_mismatch` | Production/release evidence is missing or mismatches deployed Git, image, or Alembic identity; correct the release record, then rerun backup or drill. |
| `drill_recovery_objectives_required` | Drill lacks numeric RPO/RTO, objective references, or release-required inputs; supply them before any restore write. |
| `restore_target_confirmation_mismatch` / `restore_target_matches_source` | Target identity not confirmed or equals the source; fix `--target-id`/`--confirm-target`. |
| `restore_target_database_not_empty` / `restore_target_bucket_not_empty` | Destructive restore guard; provision an empty disposable target. |
| `production_restore_guard_required` / `production_manifest_protection_required` | Production path requires the explicit flag and an encrypted signed manifest. |
| `drill_target_must_be_isolated` | Drills only run into disposable isolated targets. |
| `restore_target_storage_missing` / `restore_target_configuration_missing` | Target MinIO/DB/Redis not supplied; restore requires explicit target config. |
| `queue_reconciler_unavailable` | A recorded durable reconciler cannot be loaded in this runtime; use `--queue-reconciler` override or fix packaging. |
| `restore_execution_failed` | Restore aborted mid-way; **discard the target** (details carry `target_requires_discard: true` and `completed_stages`). |
| `external_command_failed` / `required_tool_missing` | A quiesce/resume/crypto/psql command failed; inspect `details.returncode`, the source was left resumed (backup) or the target must be discarded (restore). |

## 10. Local drill stack (disposable)

For a routine drill, stand up a throwaway stack and restore into it:

```bash
docker compose -p cygnus-drill up -d postgres redis minio
# source backup already exists; then run the §7 drill command against
# the drill containers (host ports 5432/6379/9000 with a dedicated DB,
# Redis db 14, and a dedicated empty bucket).
docker compose -p cygnus-drill down -v   # discard everything
```

The drill's empty-target guards make it safe to reuse the same containers: a
non-empty target database or bucket aborts the drill before any write.
