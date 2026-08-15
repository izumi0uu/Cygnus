"""Coordinated Cygnus backup, restore, and durable queue reconciliation.

This module owns the on-disk ``cygnus-coordinated-backup/v1`` package format.
It deliberately excludes Redis/ARQ payloads: Redis is ephemeral transport, while
committed database outboxes are the recovery source of truth. A restore flushes
the isolated target Redis database and invokes the recorded durable reconcilers.

The module never archives plaintext runtime keys. It records only SHA-256
fingerprints of the key material required to decrypt persisted encrypted settings
and validate MCP token hashes.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from typing import Iterator, Mapping, NotRequired, Protocol, Sequence, TypedDict
from urllib.parse import urlsplit, urlunsplit
import uuid

from alembic.config import Config
from alembic.script import ScriptDirectory
from minio import Minio
import redis.asyncio as redis


BACKUP_FORMAT = "cygnus-coordinated-backup/v1"
MANIFEST_ENVELOPE_FILE = "manifest.envelope.json"
COMPLETE_FILE = "COMPLETE"
DEFAULT_RETENTION_LABEL = "manual"
DEFAULT_QUEUE_RECONCILERS = (
    "cygnus.review.pre_review.dispatch:sweep_ai_pre_review_dispatches",
    "cygnus.runtime.source_dispatch:sweep_source_dispatches",
    "cygnus.runtime.source_deletion:sweep_source_deletions",
)
KEY_MATERIAL_FIELDS = {
    "runtime.secret_key": "secret_key",
    "runtime.mcp_token_pepper": "mcp_token_pepper",
}
DRILL_REPORT_FORMAT = "cygnus-drill-report/v1"
# RPO is measured at backup time as the operator-quiesce window that precedes
# the pg_dump snapshot; RTO is measured during a drill from restore start to
# completion of the verification stage. Values are never invented: when a
# measurement basis is absent the report carries measured=false and null seconds.
DRILL_RPO_BASIS = "quiesce_completed_to_dump_started"
DRILL_RTO_BASIS = "restore_start_to_verification_complete"
OUTBOX_TABLE = "wiki_draft_ai_pre_review_dispatches"
SOURCE_DISPATCH_OUTBOX_TABLE = "source_dispatch_executions"
OUTBOX_JOB_ID_COLUMN = "job_id"
LEDGER_TABLE = "governance_ledger_events"
LEDGER_IDEMPOTENCY_COLUMN = "idempotency_key"
# Non-terminal outbox statuses that must be drained by the restore reconcilers.
OUTBOX_NONTERMINAL_STATUSES = ("pending", "dispatching")
SOURCE_DISPATCH_NONTERMINAL_STATUSES = ("pending", "dispatching")
_CONFIG_INVENTORY_FIELDS = (
    "database_url",
    "secret_key",
    "mcp_token_pepper",
    "minio_endpoint",
    "minio_bucket",
    "minio_access_key",
    "minio_secret_key",
    "redis_host",
    "redis_port",
    "redis_password",
    "redis_db",
)
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:=/-]{0,127}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:=/-]{0,127}$")
_FULL_GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_IMMUTABLE_IMAGE_REF_PATTERN = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReleaseIdentity:
    """Immutable deployed release coordinates bound to a backup package.

    The values are deliberately explicit rather than inferred from mutable tags
    or the local checkout. Production backups validate the commit against the
    checkout and the Alembic revision against the backed-up database.
    """

    git_commit: str
    backend_image_ref: str
    frontend_image_ref: str
    alembic_head: str

    def to_dict(self) -> dict[str, str]:
        return {
            "git_commit": self.git_commit,
            "backend_image_ref": self.backend_image_ref,
            "frontend_image_ref": self.frontend_image_ref,
            "alembic_head": self.alembic_head,
        }


@dataclass(frozen=True)
class RecoveryObjectiveRefs:
    """Operator-approved objective identities attached to a measured drill."""

    rpo_objective_ref: str | None = None
    rto_objective_ref: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "rpo_objective_ref": self.rpo_objective_ref,
            "rto_objective_ref": self.rto_objective_ref,
        }


# --- Drill verification evidence shapes (drill report records) ---
class TableRowCounts(TypedDict):
    baseline_tables: int
    checked: int
    matched: int
    mismatches: list[dict[str, object]]
    measured: bool


class ObjectHashVerification(TypedDict):
    checked: int
    matched: int
    mismatches: list[dict[str, object]]


class ForeignKeyOrphan(TypedDict):
    constraint_name: str
    orphan_rows: int


class ForeignKeyVerification(TypedDict):
    constraints_checked: int
    orphan_rows: int
    orphans: list[ForeignKeyOrphan]


class CountComparison(TypedDict):
    expected: int | None
    actual: int
    matched: bool | None
    measured: bool


class IdempotencyReceipts(TypedDict):
    ledger_table: NotRequired[str]
    ledger_event_duplicate_idempotency_keys: list[list[str | int]]
    ledger_event_count: CountComparison
    outbox_table: NotRequired[str]
    outbox_job_id_duplicates: list[list[str | int]]
    outbox_row_count: CountComparison
    source_dispatch_table: NotRequired[str]
    source_dispatch_job_id_duplicates: NotRequired[list[list[str | int]]]
    source_dispatch_row_count: NotRequired[CountComparison]


class PendingJobsVerification(TypedDict):
    nonterminal_outbox_rows_after_replay: int
    checked_statuses: NotRequired[list[str]]
    source_dispatch_nonterminal_rows_after_replay: NotRequired[int]


class RedisEvidence(TypedDict):
    dbsize: int
    arq_key_count: int
    expected_arq_job_ids: int
    enqueued_outbox_without_arq_job: list[str]


class EncryptedConfigVerification(TypedDict):
    checked: bool
    sensitive_keys_checked: int
    decrypt_ok: int
    decrypt_failures: list[dict[str, str]]
    reason: NotRequired[str]


class VerificationEvidence(TypedDict):
    table_row_counts: TableRowCounts
    object_hashes: ObjectHashVerification
    foreign_keys: ForeignKeyVerification
    idempotency_receipts: IdempotencyReceipts
    pending_jobs: PendingJobsVerification
    redis: RedisEvidence
    encrypted_config: EncryptedConfigVerification


class RpoEvidence(TypedDict, total=False):
    measured: bool
    seconds: float | None
    basis: str
    measured_at: str
    reason: str


class _StreamableResponse(Protocol):
    """Readable/streamable object-store response used while sealing artifacts."""

    def stream(self, amt: int) -> Iterator[bytes]: ...

    def read(self, amt: int) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class BackupRestoreError(RuntimeError):
    """A failure that is safe to serialize into an operator report."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def as_report(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


@dataclass(frozen=True)
class ObjectStoreTarget:
    """Credentials and location for one S3-compatible MinIO bucket."""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool


@dataclass(frozen=True)
class TransformCommands:
    """External cryptographic hooks run without a shell.

    Each command is an argv template. The available placeholders are documented
    by the corresponding CLI option. Keeping this as an argv template avoids
    evaluating operator-supplied command text through a shell.
    """

    artifact_encrypt: str | None = None
    artifact_decrypt: str | None = None
    manifest_encrypt: str | None = None
    manifest_decrypt: str | None = None
    manifest_sign: str | None = None
    manifest_verify: str | None = None

    def validate_for_backup(self, *, environment: str) -> None:
        _require_pair(
            self.artifact_encrypt,
            self.artifact_decrypt,
            "artifact_encrypt_command",
            "artifact_decrypt_command",
        )
        _require_pair(
            self.manifest_encrypt,
            self.manifest_decrypt,
            "manifest_encrypt_command",
            "manifest_decrypt_command",
        )
        _require_pair(
            self.manifest_sign,
            self.manifest_verify,
            "manifest_sign_command",
            "manifest_verify_command",
        )
        if environment == "production":
            missing = [
                label
                for label, value in (
                    ("artifact encryption", self.artifact_encrypt),
                    ("manifest encryption", self.manifest_encrypt),
                    ("manifest signing", self.manifest_sign),
                )
                if not value
            ]
            if missing:
                raise BackupRestoreError(
                    "production_backup_protection_required",
                    "production backups require encrypted artifacts plus an encrypted, signed manifest",
                    details={"missing": missing},
                )


@dataclass(frozen=True)
class BackupRequest:
    output_dir: Path
    database_url: str
    object_store: ObjectStoreTarget
    environment: str
    source_id: str
    quiesce_command: str
    resume_command: str
    retention_labels: tuple[str, ...]
    transforms: TransformCommands
    queue_reconcilers: tuple[str, ...]
    dry_run: bool = False
    release_identity: ReleaseIdentity | None = None
    repo_root: Path | None = None
    key_material: Mapping[str, str] | None = None


@dataclass(frozen=True)
class RestoreRequest:
    backup_dir: Path
    target_database_url: str
    target_object_store: ObjectStoreTarget
    target_redis_url: str
    target_environment: str
    target_id: str
    confirm_target: str
    allow_production_restore: bool
    key_material: Mapping[str, str]
    transforms: TransformCommands
    queue_reconcilers: tuple[str, ...] | None = None
    dry_run: bool = False
    repo_root: Path | None = None


@dataclass(frozen=True)
class LoadedBackup:
    package_dir: Path
    envelope: dict[str, object]
    manifest: dict[str, object]


def _require_pair(
    left: str | None,
    right: str | None,
    left_name: str,
    right_name: str,
) -> None:
    if bool(left) != bool(right):
        raise BackupRestoreError(
            "incomplete_crypto_hook",
            f"{left_name} and {right_name} must be supplied together",
            details={"required_pair": [left_name, right_name]},
        )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root(repo_root: Path | None = None) -> Path:
    return (repo_root or Path(__file__).resolve().parents[2]).resolve()


def _normalize_database_url(database_url: str) -> str:
    """Make an SQLAlchemy async PostgreSQL URL usable by PostgreSQL CLIs."""

    parsed = urlsplit(database_url)
    scheme = parsed.scheme
    if scheme.startswith("postgresql+"):
        scheme = "postgresql"
    elif scheme.startswith("postgres+"):
        scheme = "postgres"
    return urlunsplit(
        (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_relative_path(value: str) -> Path:
    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise BackupRestoreError(
            "unsafe_archive_path",
            "backup manifest contains an unsafe artifact path",
            details={"path": value},
        )
    return candidate


def _archive_path(root: Path, relative: str) -> Path:
    path = root / _safe_relative_path(relative)
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise BackupRestoreError(
            "unsafe_archive_path",
            "backup artifact resolves outside its package directory",
            details={"path": relative},
        )
    return resolved_path


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupRestoreError(
            "required_backup_file_missing",
            f"required {label} is missing",
            details={"path": str(path)},
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupRestoreError(
            "backup_json_invalid",
            f"cannot read {label}",
            details={"path": str(path), "error_type": type(exc).__name__},
        ) from exc
    if not isinstance(loaded, dict):
        raise BackupRestoreError(
            "backup_json_invalid",
            f"{label} must be a JSON object",
            details={"path": str(path)},
        )
    return loaded


def _run_checked(
    argv: Sequence[str],
    *,
    label: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
        )
    except FileNotFoundError as exc:
        raise BackupRestoreError(
            "required_tool_missing",
            f"{label} could not start because its executable is unavailable",
            details={"tool": argv[0]},
        ) from exc
    if completed.returncode != 0:
        raise BackupRestoreError(
            "external_command_failed",
            f"{label} failed",
            details={"tool": argv[0], "returncode": completed.returncode},
        )
    return completed.stdout


def _run_template(
    template: str,
    *,
    label: str,
    required_placeholders: tuple[str, ...],
    values: Mapping[str, str],
) -> str:
    missing = [
        placeholder
        for placeholder in required_placeholders
        if f"{{{placeholder}}}" not in template
    ]
    if missing:
        raise BackupRestoreError(
            "crypto_hook_template_invalid",
            f"{label} is missing required placeholders",
            details={"missing_placeholders": missing},
        )
    try:
        argv = [part.format_map(values) for part in shlex.split(template)]
    except (KeyError, ValueError) as exc:
        raise BackupRestoreError(
            "crypto_hook_template_invalid",
            f"{label} contains an invalid placeholder",
            details={"error_type": type(exc).__name__},
        ) from exc
    if not argv:
        raise BackupRestoreError(
            "crypto_hook_template_invalid",
            f"{label} cannot be empty",
        )
    return _run_checked(argv, label=label)


def _repository_revisions(
    repo_root: Path | None = None,
) -> tuple[tuple[str, ...], ScriptDirectory]:
    root = _repo_root(repo_root)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = tuple(sorted(script.get_heads()))
    if not heads:
        raise BackupRestoreError(
            "repository_has_no_alembic_head",
            "the repository does not expose an Alembic head",
        )
    return heads, script


def _psql_rows(database_url: str, query: str) -> list[list[str]]:
    output = _run_checked(
        (
            "psql",
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--csv",
            "--dbname",
            _normalize_database_url(database_url),
            "--command",
            query,
        ),
        label="PostgreSQL metadata query",
    )
    return [row for row in csv.reader(io.StringIO(output)) if row]


def _database_revisions(database_url: str) -> tuple[str, ...]:
    rows = _psql_rows(
        database_url,
        "SELECT version_num FROM alembic_version ORDER BY version_num;",
    )
    revisions = tuple(row[0] for row in rows if row and row[0])
    if not revisions:
        raise BackupRestoreError(
            "database_unversioned",
            "database has no Alembic revision and cannot be backed up as a governed runtime",
        )
    return revisions


def _assert_database_is_at_repository_head(
    database_url: str,
    repository_heads: tuple[str, ...],
) -> tuple[str, ...]:
    revisions = _database_revisions(database_url)
    if set(revisions) != set(repository_heads):
        raise BackupRestoreError(
            "database_not_at_repository_head",
            "backup refuses a database that is not at the checked-out Alembic head",
            details={
                "database_revisions": list(revisions),
                "repository_heads": list(repository_heads),
            },
        )
    return revisions


def _sensitive_app_config_keys(database_url: str) -> tuple[str, ...]:
    rows = _psql_rows(database_url, "SELECT key FROM app_config ORDER BY key;")
    from cygnus.runtime.services.config_service import _is_sensitive

    return tuple(sorted(row[0] for row in rows if row and _is_sensitive(row[0])))


def _runtime_key_material() -> dict[str, str]:
    from cygnus.runtime.config import get_settings

    settings = get_settings()
    values = {
        key_id: str(getattr(settings, field_name))
        for key_id, field_name in KEY_MATERIAL_FIELDS.items()
    }
    empty = [key_id for key_id, value in values.items() if not value]
    if empty:
        raise BackupRestoreError(
            "required_key_material_missing",
            "runtime key material required for encrypted settings is absent",
            details={"missing_key_ids": empty},
        )
    return values


def _key_inventory(values: Mapping[str, str]) -> dict[str, object]:
    missing = [key_id for key_id in KEY_MATERIAL_FIELDS if not values.get(key_id)]
    if missing:
        raise BackupRestoreError(
            "required_key_material_missing",
            "backup requires key material fingerprints for encrypted runtime state",
            details={"missing_key_ids": missing},
        )
    return {
        key_id: {
            "algorithm": "sha256",
            "fingerprint": _fingerprint(values[key_id]),
            "required_for": (
                ["app_config_encryption", "jwt_validation"]
                if key_id == "runtime.secret_key"
                else ["mcp_token_validation"]
            ),
        }
        for key_id in sorted(KEY_MATERIAL_FIELDS)
    }


def _validate_labels(labels: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(labels or (DEFAULT_RETENTION_LABEL,)))
    invalid = [label for label in normalized if not _LABEL_PATTERN.fullmatch(label)]
    if invalid:
        raise BackupRestoreError(
            "retention_label_invalid",
            "retention labels must be short safe identifiers",
            details={"invalid_labels": invalid},
        )
    return normalized


def _validate_identifier(value: str, *, label: str) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise BackupRestoreError(
            "runtime_identity_invalid",
            f"{label} must be a short safe identifier",
            details={"label": label},
        )


def _validate_release_identity(
    identity: ReleaseIdentity | None,
    *,
    required: bool,
) -> ReleaseIdentity | None:
    if identity is None:
        if required:
            raise BackupRestoreError(
                "release_identity_required",
                "production/release evidence requires full Git, immutable image, and Alembic identity",
            )
        return None
    normalized = ReleaseIdentity(
        git_commit=identity.git_commit.strip().lower(),
        backend_image_ref=identity.backend_image_ref.strip(),
        frontend_image_ref=identity.frontend_image_ref.strip(),
        alembic_head=identity.alembic_head.strip(),
    )
    missing = [name for name, value in normalized.to_dict().items() if not value]
    if missing:
        raise BackupRestoreError(
            "release_identity_invalid",
            "release identity fields must be non-empty",
            details={"missing": missing},
        )
    if not _FULL_GIT_COMMIT_PATTERN.fullmatch(normalized.git_commit):
        raise BackupRestoreError(
            "release_git_commit_invalid",
            "release Git commit must be a full 40- or 64-character lowercase SHA",
        )
    invalid_images = [
        name
        for name, value in (
            ("backend_image_ref", normalized.backend_image_ref),
            ("frontend_image_ref", normalized.frontend_image_ref),
        )
        if not _IMMUTABLE_IMAGE_REF_PATTERN.fullmatch(value)
    ]
    if invalid_images:
        raise BackupRestoreError(
            "release_image_ref_invalid",
            "backend and frontend images must be immutable @sha256 digest references",
            details={"invalid": invalid_images},
        )
    _validate_identifier(normalized.alembic_head, label="alembic_head")
    return normalized


def _assert_release_identity_matches_snapshot(
    identity: ReleaseIdentity | None,
    *,
    repository_heads: tuple[str, ...],
    database_revisions: tuple[str, ...],
    repo_root: Path | None,
) -> ReleaseIdentity | None:
    normalized = _validate_release_identity(identity, required=False)
    if normalized is None:
        return None
    if len(repository_heads) != 1:
        raise BackupRestoreError(
            "release_alembic_head_ambiguous",
            "release evidence requires exactly one repository Alembic head",
            details={"repository_heads": list(repository_heads)},
        )
    head = repository_heads[0]
    if normalized.alembic_head != head or database_revisions != (head,):
        raise BackupRestoreError(
            "release_alembic_head_mismatch",
            "declared release Alembic head does not exactly match the backed-up database",
            details={
                "declared_alembic_head": normalized.alembic_head,
                "database_revisions": list(database_revisions),
                "repository_heads": list(repository_heads),
            },
        )
    checked_out_commit = (
        _run_checked(
            ("git", "rev-parse", "HEAD"),
            label="release Git commit verification",
            cwd=_repo_root(repo_root),
        )
        .strip()
        .lower()
    )
    if checked_out_commit != normalized.git_commit:
        raise BackupRestoreError(
            "release_git_commit_mismatch",
            "declared release Git commit does not match the checked-out backup code",
            details={
                "declared_git_commit": normalized.git_commit,
                "checked_out_git_commit": checked_out_commit,
            },
        )
    return normalized


def _release_identity_from_manifest(
    manifest: Mapping[str, object],
    *,
    required: bool,
) -> ReleaseIdentity | None:
    raw_identity = manifest.get("release_identity")
    if raw_identity is None:
        return _validate_release_identity(None, required=required)
    if not isinstance(raw_identity, Mapping):
        raise BackupRestoreError(
            "manifest_release_identity_invalid",
            "backup manifest release_identity must be an object",
        )
    values = {
        key: raw_identity.get(key)
        for key in (
            "git_commit",
            "backend_image_ref",
            "frontend_image_ref",
            "alembic_head",
        )
    }
    invalid = [key for key, value in values.items() if not isinstance(value, str)]
    if invalid:
        raise BackupRestoreError(
            "manifest_release_identity_invalid",
            "backup manifest release_identity has invalid fields",
            details={"invalid": invalid},
        )
    return _validate_release_identity(
        ReleaseIdentity(
            git_commit=str(values["git_commit"]),
            backend_image_ref=str(values["backend_image_ref"]),
            frontend_image_ref=str(values["frontend_image_ref"]),
            alembic_head=str(values["alembic_head"]),
        ),
        required=required,
    )


def _assert_release_identity_matches_expected(
    manifest: Mapping[str, object],
    *,
    expected: ReleaseIdentity | None,
    required: bool,
) -> ReleaseIdentity | None:
    recorded = _release_identity_from_manifest(manifest, required=required)
    expected = _validate_release_identity(expected, required=required)
    if recorded is None:
        return None
    if expected is None:
        return recorded
    mismatches = [
        key
        for key, value in recorded.to_dict().items()
        if value != expected.to_dict()[key]
    ]
    if mismatches:
        raise BackupRestoreError(
            "release_identity_mismatch",
            "backup package identity does not match the release being certified",
            details={"mismatches": mismatches},
        )
    return recorded


def _normalize_objective_refs(
    refs: RecoveryObjectiveRefs | None,
) -> RecoveryObjectiveRefs:
    refs = refs or RecoveryObjectiveRefs()
    normalized = RecoveryObjectiveRefs(
        rpo_objective_ref=(refs.rpo_objective_ref or "").strip() or None,
        rto_objective_ref=(refs.rto_objective_ref or "").strip() or None,
    )
    for label, value in normalized.to_dict().items():
        if value is not None:
            _validate_identifier(value, label=label)
    return normalized


def _release_identity_from_cli(
    args: argparse.Namespace,
    *,
    option_prefix: str,
    environment_prefix: str,
) -> ReleaseIdentity | None:
    fields = (
        "git_commit",
        "backend_image_ref",
        "frontend_image_ref",
        "alembic_head",
    )
    values = {
        field: getattr(args, f"{option_prefix}{field}", None)
        or os.environ.get(f"{environment_prefix}{field.upper()}")
        for field in fields
    }
    if not any(values.values()):
        return None
    missing = [field for field, value in values.items() if not value]
    if missing:
        raise BackupRestoreError(
            "release_identity_arguments_incomplete",
            "release identity arguments must be supplied as one complete set",
            details={"missing": missing},
        )
    return ReleaseIdentity(
        git_commit=str(values["git_commit"]),
        backend_image_ref=str(values["backend_image_ref"]),
        frontend_image_ref=str(values["frontend_image_ref"]),
        alembic_head=str(values["alembic_head"]),
    )


def _client_for(target: ObjectStoreTarget) -> Minio:
    return Minio(
        target.endpoint,
        access_key=target.access_key,
        secret_key=target.secret_key,
        secure=target.secure,
    )


def _extract_user_metadata(stat: object) -> dict[str, str]:
    raw = getattr(stat, "metadata", None) or {}
    metadata: dict[str, str] = {}
    for key, value in dict(raw).items():
        text_key = str(key)
        if text_key.lower().startswith("x-amz-meta-"):
            metadata[text_key] = str(value)
    return metadata


def _content_type(stat: object) -> str:
    value = getattr(stat, "content_type", None)
    if isinstance(value, str) and value:
        return value
    metadata = getattr(stat, "metadata", None) or {}
    for key, value in dict(metadata).items():
        if str(key).lower() == "content-type" and value:
            return str(value)
    return "application/octet-stream"


def _object_timestamp(stat: object) -> str | None:
    value = getattr(stat, "last_modified", None)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _seal_artifact(
    raw_path: Path,
    *,
    package_root: Path,
    final_relative_path: str,
    transforms: TransformCommands,
) -> dict[str, object]:
    payload_sha256, payload_bytes = _file_digest(raw_path)
    encrypted = bool(transforms.artifact_encrypt)
    stored_relative_path = (
        f"{final_relative_path}.enc" if encrypted else final_relative_path
    )
    stored_path = _archive_path(package_root, stored_relative_path)
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    if encrypted:
        assert transforms.artifact_encrypt is not None
        _run_template(
            transforms.artifact_encrypt,
            label="artifact encryption command",
            required_placeholders=("input", "output"),
            values={"input": str(raw_path), "output": str(stored_path)},
        )
        if not stored_path.is_file() or stored_path.stat().st_size == 0:
            raise BackupRestoreError(
                "artifact_encryption_output_missing",
                "artifact encryption command did not create a non-empty output",
                details={"artifact": final_relative_path},
            )
        raw_path.unlink()
    else:
        os.replace(raw_path, stored_path)
    stored_sha256, stored_bytes = _file_digest(stored_path)
    return {
        "path": stored_relative_path,
        "sha256": stored_sha256,
        "bytes": stored_bytes,
        "payload_sha256": payload_sha256,
        "payload_bytes": payload_bytes,
        "encrypted": encrypted,
    }


def _stream_response_to_file(response: _StreamableResponse, destination: Path) -> None:
    try:
        with destination.open("wb") as stream:
            if hasattr(response, "stream"):
                for chunk in response.stream(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
            else:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        release = getattr(response, "release_conn", None)
        if callable(release):
            release()


def _copy_object_to_package(
    client: Minio,
    *,
    bucket: str,
    object_key: str,
    index: int,
    package_root: Path,
    transforms: TransformCommands,
) -> dict[str, object]:
    stat = client.stat_object(bucket, object_key)
    raw_path = package_root / "objects" / f"{index:08d}.blob.raw"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    response = client.get_object(bucket, object_key)
    _stream_response_to_file(response, raw_path)
    artifact = _seal_artifact(
        raw_path,
        package_root=package_root,
        final_relative_path=f"objects/{index:08d}.blob",
        transforms=transforms,
    )
    return {
        "object_key": object_key,
        "artifact": artifact,
        "content_type": _content_type(stat),
        "metadata": _extract_user_metadata(stat),
        "source_etag": str(getattr(stat, "etag", "")) or None,
        "source_size": int(getattr(stat, "size", 0) or 0),
        "source_last_modified": _object_timestamp(stat),
    }


def _dump_database(
    database_url: str,
    destination: Path,
) -> None:
    _run_checked(
        (
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(destination),
            _normalize_database_url(database_url),
        ),
        label="PostgreSQL custom dump",
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise BackupRestoreError(
            "database_dump_missing",
            "pg_dump did not create a non-empty custom dump",
        )
    _run_checked(
        ("pg_restore", "--list", str(destination)),
        label="PostgreSQL custom dump validation",
    )


def _write_manifest(
    package_root: Path,
    manifest: dict[str, object],
    transforms: TransformCommands,
) -> None:
    raw_manifest = package_root / "manifest.json"
    _write_json_atomic(raw_manifest, manifest)
    manifest_path = raw_manifest
    encrypted = bool(transforms.manifest_encrypt)
    if encrypted:
        assert transforms.manifest_encrypt is not None
        manifest_path = package_root / "manifest.json.enc"
        _run_template(
            transforms.manifest_encrypt,
            label="manifest encryption command",
            required_placeholders=("input", "output"),
            values={"input": str(raw_manifest), "output": str(manifest_path)},
        )
        if not manifest_path.is_file() or manifest_path.stat().st_size == 0:
            raise BackupRestoreError(
                "manifest_encryption_output_missing",
                "manifest encryption command did not create a non-empty output",
            )
        raw_manifest.unlink()

    signature_name: str | None = None
    if transforms.manifest_sign:
        signature_path = package_root / "manifest.sig"
        _run_template(
            transforms.manifest_sign,
            label="manifest signing command",
            required_placeholders=("input", "signature"),
            values={"input": str(manifest_path), "signature": str(signature_path)},
        )
        if not signature_path.is_file() or signature_path.stat().st_size == 0:
            raise BackupRestoreError(
                "manifest_signature_missing",
                "manifest signing command did not create a non-empty signature",
            )
        signature_name = signature_path.name

    manifest_sha256, manifest_bytes = _file_digest(manifest_path)
    envelope = {
        "format_version": BACKUP_FORMAT,
        "manifest_artifact": manifest_path.name,
        "manifest_sha256": manifest_sha256,
        "manifest_bytes": manifest_bytes,
        "encrypted": encrypted,
        "signature_artifact": signature_name,
    }
    envelope_path = package_root / MANIFEST_ENVELOPE_FILE
    _write_json_atomic(envelope_path, envelope)
    envelope_sha256, _ = _file_digest(envelope_path)
    _write_json_atomic(
        package_root / COMPLETE_FILE,
        {
            "format_version": BACKUP_FORMAT,
            "manifest_envelope_sha256": envelope_sha256,
            "completed_at": _utcnow(),
        },
    )


def _queue_policy(reconcilers: tuple[str, ...]) -> dict[str, object]:
    return {
        "redis_persistence": "ephemeral",
        "restore_action": "flush_target_redis_db_then_replay_durable_outboxes",
        "durable_truth": "postgresql_outbox_rows",
        "reconcilers": list(reconcilers),
    }


def _backup_manifest(
    *,
    request: BackupRequest,
    database_artifact: dict[str, object],
    database_revisions: tuple[str, ...],
    repository_heads: tuple[str, ...],
    objects: list[dict[str, object]],
    encrypted_config_keys: tuple[str, ...],
    key_inventory: dict[str, object],
    consistency_boundary: dict[str, object],
    verification_baseline: dict[str, object],
) -> dict[str, object]:
    return {
        "format_version": BACKUP_FORMAT,
        "created_at": _utcnow(),
        "source": {
            "environment": request.environment,
            "identity": request.source_id,
        },
        "release_identity": (
            request.release_identity.to_dict()
            if request.release_identity is not None
            else None
        ),
        "consistency_boundary": consistency_boundary,
        "database": {
            "format": "postgres_custom",
            "artifact": database_artifact,
            "database_revisions": list(database_revisions),
            "repository_heads": list(repository_heads),
        },
        "objects": objects,
        "configuration_inventory": {
            "runtime_setting_names": list(_CONFIG_INVENTORY_FIELDS),
            "encrypted_app_config_keys": list(encrypted_config_keys),
            "plaintext_key_material_archived": False,
        },
        "key_material": key_inventory,
        "queue_reconciliation": _queue_policy(request.queue_reconcilers),
        "retention_labels": list(request.retention_labels),
        "artifact_encryption": {"enabled": bool(request.transforms.artifact_encrypt)},
        "verification": verification_baseline,
    }


def _report_backup_plan(
    request: BackupRequest, repository_heads: tuple[str, ...]
) -> dict[str, object]:
    return {
        "report_format": "cygnus-backup-report/v1",
        "operation": "backup",
        "status": "dry_run",
        "source": {"environment": request.environment, "identity": request.source_id},
        "release_identity": (
            request.release_identity.to_dict()
            if request.release_identity is not None
            else None
        ),
        "output_dir": str(request.output_dir),
        "database": {
            "format": "postgres_custom",
            "repository_heads": list(repository_heads),
        },
        "consistency_boundary": "operator_quiesce_commands",
        "retention_labels": list(request.retention_labels),
        "artifact_encryption": bool(request.transforms.artifact_encrypt),
        "manifest_encryption": bool(request.transforms.manifest_encrypt),
        "manifest_signature": bool(request.transforms.manifest_sign),
        "queue_reconcilers": list(request.queue_reconcilers),
        "generated_at": _utcnow(),
    }


def run_backup(request: BackupRequest) -> dict[str, object]:
    """Create an atomic coordinated backup package after an operator quiesce."""

    if request.environment not in {"development", "staging", "production"}:
        raise BackupRestoreError(
            "backup_environment_invalid",
            "backup environment must be development, staging, or production",
        )
    _validate_identifier(request.source_id, label="source_id")
    release_identity = _validate_release_identity(
        request.release_identity,
        required=request.environment == "production",
    )
    if release_identity != request.release_identity:
        request = BackupRequest(
            **{**request.__dict__, "release_identity": release_identity}
        )
    if not request.quiesce_command or not request.resume_command:
        raise BackupRestoreError(
            "quiesce_boundary_required",
            "backup requires both a quiesce command and a resume command",
        )
    labels = _validate_labels(request.retention_labels)
    if labels != request.retention_labels:
        request = BackupRequest(**{**request.__dict__, "retention_labels": labels})
    request.transforms.validate_for_backup(environment=request.environment)
    repository_heads, _ = _repository_revisions(request.repo_root)
    if request.dry_run:
        return _report_backup_plan(request, repository_heads)

    output_dir = request.output_dir.resolve()
    if output_dir.exists():
        raise BackupRestoreError(
            "backup_destination_exists",
            "backup destination already exists; refusing to mix artifacts",
            details={"output_dir": str(output_dir)},
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = output_dir.parent / f".{output_dir.name}.partial-{uuid.uuid4().hex}"
    staging_dir.mkdir()

    quiesced = False
    failure: BaseException | None = None
    manifest: dict[str, object] | None = None
    try:
        _run_template(
            request.quiesce_command,
            label="backup quiesce command",
            required_placeholders=(),
            values={},
        )
        quiesced = True
        quiesce_completed_at = _utcnow()
        database_revisions = _assert_database_is_at_repository_head(
            request.database_url, repository_heads
        )
        release_identity = _assert_release_identity_matches_snapshot(
            request.release_identity,
            repository_heads=repository_heads,
            database_revisions=database_revisions,
            repo_root=request.repo_root,
        )
        if release_identity != request.release_identity:
            request = BackupRequest(
                **{**request.__dict__, "release_identity": release_identity}
            )
        encrypted_config_keys = _sensitive_app_config_keys(request.database_url)
        key_inventory = _key_inventory(request.key_material or _runtime_key_material())

        raw_dump = staging_dir / "database.dump.raw"
        dump_started_at = _utcnow()
        _dump_database(request.database_url, raw_dump)
        dump_completed_at = _utcnow()
        database_artifact = _seal_artifact(
            raw_dump,
            package_root=staging_dir,
            final_relative_path="database.dump",
            transforms=request.transforms,
        )
        # Sampled under the same quiesce, so the counts are consistent with the
        # dump snapshot; a later drill compares restored counts against them.
        verification_baseline = _record_verification_baseline(request.database_url)
        consistency_boundary = _consistency_boundary_record(
            quiesce_completed_at=quiesce_completed_at,
            dump_started_at=dump_started_at,
            dump_completed_at=dump_completed_at,
        )

        source_client = _client_for(request.object_store)
        if not source_client.bucket_exists(request.object_store.bucket):
            raise BackupRestoreError(
                "source_bucket_missing",
                "configured MinIO backup bucket does not exist",
                details={"bucket": request.object_store.bucket},
            )
        listed = sorted(
            object_key
            for item in source_client.list_objects(
                request.object_store.bucket, recursive=True
            )
            if (object_key := item.object_name)
        )
        objects = [
            _copy_object_to_package(
                source_client,
                bucket=request.object_store.bucket,
                object_key=object_key,
                index=index,
                package_root=staging_dir,
                transforms=request.transforms,
            )
            for index, object_key in enumerate(listed, start=1)
        ]
        manifest = _backup_manifest(
            request=request,
            database_artifact=database_artifact,
            database_revisions=database_revisions,
            repository_heads=repository_heads,
            objects=objects,
            encrypted_config_keys=encrypted_config_keys,
            key_inventory=key_inventory,
            consistency_boundary=consistency_boundary,
            verification_baseline=verification_baseline,
        )
        _write_manifest(staging_dir, manifest, request.transforms)
    except BaseException as exc:
        failure = exc
    finally:
        if quiesced:
            try:
                _run_template(
                    request.resume_command,
                    label="backup resume command",
                    required_placeholders=(),
                    values={},
                )
            except BaseException as resume_error:
                if failure is None:
                    failure = BackupRestoreError(
                        "backup_resume_failed",
                        "backup resume command failed; backup package was not published",
                        details={"error_type": type(resume_error).__name__},
                    )
                else:
                    failure = BackupRestoreError(
                        "backup_failed_and_resume_failed",
                        "backup failed and the resume command also failed; inspect the source immediately",
                        details={
                            "backup_error_type": type(failure).__name__,
                            "resume_error_type": type(resume_error).__name__,
                        },
                    )
    if failure is not None:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise failure

    try:
        os.replace(staging_dir, output_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    assert manifest is not None
    database_record = manifest["database"]
    manifest_objects = manifest["objects"]
    assert isinstance(database_record, Mapping)
    assert isinstance(manifest_objects, list)
    return {
        "report_format": "cygnus-backup-report/v1",
        "operation": "backup",
        "status": "completed",
        "backup_dir": str(output_dir),
        "source": manifest["source"],
        "release_identity": manifest.get("release_identity"),
        "database_revisions": database_record["database_revisions"],
        "object_count": len(manifest_objects),
        "retention_labels": manifest["retention_labels"],
        "artifact_encryption": manifest["artifact_encryption"],
        "generated_at": _utcnow(),
    }


def _validate_envelope(
    package_dir: Path,
    transforms: TransformCommands,
    *,
    require_protected_manifest: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    complete = _read_json(package_dir / COMPLETE_FILE, label="completion marker")
    envelope_path = package_dir / MANIFEST_ENVELOPE_FILE
    envelope = _read_json(envelope_path, label="manifest envelope")
    if (
        complete.get("format_version") != BACKUP_FORMAT
        or envelope.get("format_version") != BACKUP_FORMAT
    ):
        raise BackupRestoreError(
            "backup_format_unsupported",
            "backup package does not use the supported coordinated backup format",
        )
    actual_envelope_sha256, _ = _file_digest(envelope_path)
    if complete.get("manifest_envelope_sha256") != actual_envelope_sha256:
        raise BackupRestoreError(
            "completion_marker_checksum_mismatch",
            "completion marker does not match the manifest envelope",
        )
    artifact_name = envelope.get("manifest_artifact")
    if not isinstance(artifact_name, str):
        raise BackupRestoreError(
            "manifest_envelope_invalid",
            "manifest envelope does not name its artifact",
        )
    manifest_path = _archive_path(package_dir, artifact_name)
    expected_sha256 = envelope.get("manifest_sha256")
    actual_sha256, actual_bytes = _file_digest(manifest_path)
    if (
        expected_sha256 != actual_sha256
        or envelope.get("manifest_bytes") != actual_bytes
    ):
        raise BackupRestoreError(
            "manifest_checksum_mismatch",
            "manifest artifact checksum or size does not match its envelope",
            details={"artifact": artifact_name},
        )
    encrypted = envelope.get("encrypted") is True
    signature_artifact = envelope.get("signature_artifact")
    if signature_artifact is not None and not isinstance(signature_artifact, str):
        raise BackupRestoreError(
            "manifest_envelope_invalid",
            "manifest signature artifact name is invalid",
        )
    if require_protected_manifest and (not encrypted or not signature_artifact):
        raise BackupRestoreError(
            "production_manifest_protection_required",
            "production restore requires an encrypted, signed manifest",
        )
    if signature_artifact:
        if not transforms.manifest_verify:
            raise BackupRestoreError(
                "manifest_signature_verifier_required",
                "backup contains a manifest signature but no verification command was supplied",
            )
        signature_path = _archive_path(package_dir, signature_artifact)
        _run_template(
            transforms.manifest_verify,
            label="manifest signature verification command",
            required_placeholders=("input", "signature"),
            values={"input": str(manifest_path), "signature": str(signature_path)},
        )
    if encrypted:
        if not transforms.manifest_decrypt:
            raise BackupRestoreError(
                "manifest_decryptor_required",
                "backup contains an encrypted manifest but no decrypt command was supplied",
            )
        with tempfile.TemporaryDirectory(prefix="cygnus-manifest-") as temporary:
            plaintext = Path(temporary) / "manifest.json"
            _run_template(
                transforms.manifest_decrypt,
                label="manifest decryption command",
                required_placeholders=("input", "output"),
                values={"input": str(manifest_path), "output": str(plaintext)},
            )
            manifest = _read_json(plaintext, label="decrypted manifest")
    else:
        manifest = _read_json(manifest_path, label="manifest")
    return envelope, manifest


def _artifact_records(
    manifest: Mapping[str, object],
) -> list[tuple[str, Mapping[str, object]]]:
    database = manifest.get("database")
    if not isinstance(database, Mapping) or not isinstance(
        database.get("artifact"), Mapping
    ):
        raise BackupRestoreError(
            "manifest_invalid",
            "manifest is missing the database artifact record",
        )
    records: list[tuple[str, Mapping[str, object]]] = [
        ("database", database["artifact"])
    ]
    objects = manifest.get("objects")
    if not isinstance(objects, list):
        raise BackupRestoreError(
            "manifest_invalid", "manifest objects must be an array"
        )
    for index, object_entry in enumerate(objects, start=1):
        if not isinstance(object_entry, Mapping) or not isinstance(
            object_entry.get("artifact"), Mapping
        ):
            raise BackupRestoreError(
                "manifest_invalid",
                "manifest object entry is missing its artifact record",
                details={"object_index": index},
            )
        object_key = object_entry.get("object_key")
        if not isinstance(object_key, str) or not object_key:
            raise BackupRestoreError(
                "manifest_invalid",
                "manifest object entry is missing its object key",
                details={"object_index": index},
            )
        records.append((f"object:{object_key}", object_entry["artifact"]))
    return records


def _validate_manifest_shape(manifest: Mapping[str, object]) -> None:
    required = (
        "format_version",
        "source",
        "database",
        "objects",
        "configuration_inventory",
        "key_material",
        "queue_reconciliation",
        "retention_labels",
    )
    missing = [key for key in required if key not in manifest]
    if missing or manifest.get("format_version") != BACKUP_FORMAT:
        raise BackupRestoreError(
            "manifest_invalid",
            "manifest is missing required coordinated backup fields",
            details={"missing": missing},
        )
    source = manifest.get("source")
    if (
        not isinstance(source, Mapping)
        or not isinstance(source.get("identity"), str)
        or not source["identity"].strip()
        or source.get("environment") not in {"development", "staging", "production"}
    ):
        raise BackupRestoreError(
            "manifest_invalid",
            "manifest source environment and identity are invalid",
        )
    if manifest.get("release_identity") is not None:
        _release_identity_from_manifest(manifest, required=False)


def _validate_artifact_checksums(
    package_dir: Path, manifest: Mapping[str, object]
) -> None:
    issues: list[dict[str, object]] = []
    for label, artifact in _artifact_records(manifest):
        path_value = artifact.get("path")
        expected_sha256 = artifact.get("sha256")
        expected_bytes = artifact.get("bytes")
        if (
            not isinstance(path_value, str)
            or not isinstance(expected_sha256, str)
            or not isinstance(expected_bytes, int)
        ):
            issues.append({"artifact": label, "reason": "record_invalid"})
            continue
        try:
            artifact_path = _archive_path(package_dir, path_value)
            actual_sha256, actual_bytes = _file_digest(artifact_path)
        except BackupRestoreError as exc:
            issues.append({"artifact": label, "reason": exc.code})
            continue
        except FileNotFoundError:
            issues.append({"artifact": label, "reason": "missing", "path": path_value})
            continue
        if actual_sha256 != expected_sha256 or actual_bytes != expected_bytes:
            issues.append(
                {
                    "artifact": label,
                    "reason": "checksum_or_size_mismatch",
                    "path": path_value,
                }
            )
    if issues:
        raise BackupRestoreError(
            "backup_artifact_validation_failed",
            "backup package has missing or invalid artifacts",
            details={"issues": issues},
        )


def load_backup(
    package_dir: Path,
    transforms: TransformCommands,
    *,
    require_protected_manifest: bool = False,
) -> LoadedBackup:
    package = package_dir.resolve()
    if not package.is_dir():
        raise BackupRestoreError(
            "backup_directory_missing",
            "backup directory does not exist",
            details={"backup_dir": str(package)},
        )
    envelope, manifest = _validate_envelope(
        package, transforms, require_protected_manifest=require_protected_manifest
    )
    _validate_manifest_shape(manifest)
    _validate_artifact_checksums(package, manifest)
    return LoadedBackup(package_dir=package, envelope=envelope, manifest=manifest)


@contextmanager
def materialized_artifact(
    loaded: LoadedBackup,
    artifact: Mapping[str, object],
    transforms: TransformCommands,
    *,
    label: str,
) -> Iterator[Path]:
    path_value = artifact.get("path")
    expected_plaintext_sha256 = artifact.get("payload_sha256")
    expected_plaintext_bytes = artifact.get("payload_bytes")
    encrypted = artifact.get("encrypted") is True
    if (
        not isinstance(path_value, str)
        or not isinstance(expected_plaintext_sha256, str)
        or not isinstance(expected_plaintext_bytes, int)
    ):
        raise BackupRestoreError(
            "artifact_record_invalid",
            "artifact record is missing plaintext integrity data",
            details={"artifact": label},
        )
    stored_path = _archive_path(loaded.package_dir, path_value)
    if encrypted:
        if not transforms.artifact_decrypt:
            raise BackupRestoreError(
                "artifact_decryptor_required",
                "backup contains encrypted artifacts but no decrypt command was supplied",
                details={"artifact": label},
            )
        with tempfile.TemporaryDirectory(prefix="cygnus-artifact-") as temporary:
            plaintext = Path(temporary) / "payload"
            _run_template(
                transforms.artifact_decrypt,
                label="artifact decryption command",
                required_placeholders=("input", "output"),
                values={"input": str(stored_path), "output": str(plaintext)},
            )
            if not plaintext.is_file():
                raise BackupRestoreError(
                    "artifact_decryption_output_missing",
                    "artifact decryption command did not create plaintext output",
                    details={"artifact": label},
                )
            actual_sha256, actual_bytes = _file_digest(plaintext)
            if (
                actual_sha256 != expected_plaintext_sha256
                or actual_bytes != expected_plaintext_bytes
            ):
                raise BackupRestoreError(
                    "artifact_plaintext_checksum_mismatch",
                    "decrypted artifact does not match the manifest checksum",
                    details={"artifact": label},
                )
            yield plaintext
    else:
        actual_sha256, actual_bytes = _file_digest(stored_path)
        if (
            actual_sha256 != expected_plaintext_sha256
            or actual_bytes != expected_plaintext_bytes
        ):
            raise BackupRestoreError(
                "artifact_plaintext_checksum_mismatch",
                "artifact does not match the manifest plaintext checksum",
                details={"artifact": label},
            )
        yield stored_path


def _validate_plaintext_artifacts(
    loaded: LoadedBackup, transforms: TransformCommands
) -> None:
    for label, artifact in _artifact_records(loaded.manifest):
        with materialized_artifact(loaded, artifact, transforms, label=label):
            pass


def _validate_key_prerequisites(
    manifest: Mapping[str, object],
    supplied: Mapping[str, str],
) -> list[str]:
    inventory = manifest.get("key_material")
    if not isinstance(inventory, Mapping):
        raise BackupRestoreError(
            "manifest_invalid", "key material inventory is invalid"
        )
    issues: list[dict[str, str]] = []
    validated: list[str] = []
    for key_id, record in inventory.items():
        if not isinstance(key_id, str) or not isinstance(record, Mapping):
            issues.append({"key_id": str(key_id), "reason": "record_invalid"})
            continue
        expected = record.get("fingerprint")
        value = supplied.get(key_id)
        if not isinstance(expected, str):
            issues.append({"key_id": key_id, "reason": "fingerprint_invalid"})
        elif not value:
            issues.append({"key_id": key_id, "reason": "missing"})
        elif _fingerprint(value) != expected:
            issues.append({"key_id": key_id, "reason": "fingerprint_mismatch"})
        else:
            validated.append(key_id)
    if issues:
        raise BackupRestoreError(
            "key_material_precondition_failed",
            "target key material does not satisfy the backup inventory",
            details={"issues": issues},
        )
    return validated


def _assert_backup_revision_compatible(
    manifest: Mapping[str, object], repo_root: Path | None
) -> tuple[str, ...]:
    database = manifest.get("database")
    if not isinstance(database, Mapping):
        raise BackupRestoreError("manifest_invalid", "database section is invalid")
    revisions = database.get("database_revisions")
    if not isinstance(revisions, list) or not all(
        isinstance(item, str) for item in revisions
    ):
        raise BackupRestoreError("manifest_invalid", "database revisions are invalid")
    heads, script = _repository_revisions(repo_root)
    unknown: list[str] = []
    for revision in revisions:
        try:
            known = script.get_revision(revision)
        except Exception:
            known = None
        if known is None:
            unknown.append(revision)
    if unknown:
        raise BackupRestoreError(
            "backup_revision_unknown",
            "backup database revision is not present in the checked-out migration history",
            details={"unknown_revisions": unknown},
        )
    return heads


def _validate_target_guard(
    manifest: Mapping[str, object], request: RestoreRequest
) -> None:
    if request.target_environment not in {"isolated", "production"}:
        raise BackupRestoreError(
            "restore_target_environment_invalid",
            "restore target environment must be isolated or production",
        )
    _validate_identifier(request.target_id, label="target_id")
    if request.confirm_target != request.target_id:
        raise BackupRestoreError(
            "restore_target_confirmation_mismatch",
            "confirm_target must exactly match target_id",
        )
    source = manifest.get("source")
    source_id = source.get("identity") if isinstance(source, Mapping) else None
    if not isinstance(source_id, str):
        raise BackupRestoreError(
            "manifest_invalid", "backup source identity is invalid"
        )
    if request.target_id == source_id:
        raise BackupRestoreError(
            "restore_target_matches_source",
            "restore target identity must differ from the backup source identity",
            details={"source_id": source_id},
        )
    if (
        request.target_environment == "production"
        and not request.allow_production_restore
    ):
        raise BackupRestoreError(
            "production_restore_guard_required",
            "production restore requires --allow-production-restore in addition to exact target confirmation",
        )


def _target_public_tables(database_url: str) -> tuple[str, ...]:
    rows = _psql_rows(
        database_url,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name;",
    )
    return tuple(row[0] for row in rows if row)


def _ensure_empty_target_database(database_url: str) -> None:
    tables = _target_public_tables(database_url)
    if tables:
        raise BackupRestoreError(
            "restore_target_database_not_empty",
            "destructive restore only accepts an empty isolated target database",
            details={"tables": list(tables)},
        )


def _ensure_empty_target_bucket(
    client: Minio,
    bucket: str,
    *,
    create: bool,
) -> tuple[bool, int]:
    exists = client.bucket_exists(bucket)
    if not exists:
        if create:
            client.make_bucket(bucket)
        return False, 0
    count = sum(1 for _ in client.list_objects(bucket, recursive=True))
    if count:
        raise BackupRestoreError(
            "restore_target_bucket_not_empty",
            "destructive restore only accepts an empty target object bucket",
            details={"bucket": bucket, "object_count": count},
        )
    return True, 0


def _validate_custom_dump(loaded: LoadedBackup, transforms: TransformCommands) -> None:
    database = loaded.manifest["database"]
    assert isinstance(database, Mapping)
    artifact = database["artifact"]
    assert isinstance(artifact, Mapping)
    with materialized_artifact(
        loaded, artifact, transforms, label="database"
    ) as dump_path:
        _run_checked(
            ("pg_restore", "--list", str(dump_path)),
            label="backup custom dump validation",
        )


def _restore_database(
    loaded: LoadedBackup,
    request: RestoreRequest,
) -> None:
    database = loaded.manifest["database"]
    assert isinstance(database, Mapping)
    artifact = database["artifact"]
    assert isinstance(artifact, Mapping)
    with materialized_artifact(
        loaded, artifact, request.transforms, label="database"
    ) as dump_path:
        _run_checked(
            (
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                _normalize_database_url(request.target_database_url),
                str(dump_path),
            ),
            label="PostgreSQL restore",
        )
    expected_revisions = tuple(database["database_revisions"])
    restored_revisions = _database_revisions(request.target_database_url)
    if set(restored_revisions) != set(expected_revisions):
        raise BackupRestoreError(
            "restored_database_revision_mismatch",
            "restored database Alembic revisions do not match the backup manifest",
            details={
                "expected_revisions": list(expected_revisions),
                "restored_revisions": list(restored_revisions),
            },
        )


def _restore_objects(
    loaded: LoadedBackup,
    request: RestoreRequest,
    client: Minio,
) -> int:
    object_entries = loaded.manifest["objects"]
    assert isinstance(object_entries, list)
    for index, object_entry in enumerate(object_entries, start=1):
        assert isinstance(object_entry, Mapping)
        object_key = object_entry["object_key"]
        artifact = object_entry["artifact"]
        assert isinstance(object_key, str) and isinstance(artifact, Mapping)
        metadata = object_entry.get("metadata")
        if not isinstance(metadata, Mapping):
            raise BackupRestoreError(
                "manifest_invalid",
                "object metadata is invalid",
                details={"object_key": object_key},
            )
        content_type = object_entry.get("content_type")
        if not isinstance(content_type, str) or not content_type:
            raise BackupRestoreError(
                "manifest_invalid",
                "object content type is invalid",
                details={"object_key": object_key},
            )
        with materialized_artifact(
            loaded,
            artifact,
            request.transforms,
            label=f"object:{object_key}",
        ) as source_path:
            size = source_path.stat().st_size
            with source_path.open("rb") as stream:
                client.put_object(
                    request.target_object_store.bucket,
                    object_key,
                    stream,
                    size,
                    content_type=content_type,
                    metadata={str(key): str(value) for key, value in metadata.items()},
                )
            response = client.get_object(request.target_object_store.bucket, object_key)
            with tempfile.NamedTemporaryFile(
                prefix="cygnus-object-verify-", delete=False
            ) as temporary:
                verification_path = Path(temporary.name)
            try:
                _stream_response_to_file(response, verification_path)
                actual_sha256, actual_bytes = _file_digest(verification_path)
            finally:
                verification_path.unlink(missing_ok=True)
            expected_sha256 = artifact.get("payload_sha256")
            expected_bytes = artifact.get("payload_bytes")
            if actual_sha256 != expected_sha256 or actual_bytes != expected_bytes:
                raise BackupRestoreError(
                    "restored_object_checksum_mismatch",
                    "restored object does not match the backup checksum",
                    details={"object_key": object_key, "object_index": index},
                )
    return len(object_entries)


def _run_forward_migrations(target_database_url: str, repo_root: Path | None) -> None:
    root = _repo_root(repo_root)
    environment = os.environ.copy()
    environment["database_url"] = target_database_url
    _run_checked(
        ("alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"),
        label="forward Alembic migration",
        cwd=root,
        env=environment,
    )


def _database_object_references(database_url: str) -> list[tuple[str, str, str]]:
    query = """
        SELECT 'exact' AS reference_kind, 'sources.minio_key' AS owner, minio_key AS object_key
        FROM sources WHERE NULLIF(minio_key, '') IS NOT NULL
        UNION ALL
        SELECT 'exact', 'source_images.minio_key', minio_key
        FROM source_images WHERE NULLIF(minio_key, '') IS NOT NULL
        UNION ALL
        SELECT 'prefix', 'skills.storage_path', storage_path
        FROM skills WHERE NULLIF(storage_path, '') IS NOT NULL
        UNION ALL
        SELECT 'prefix', 'skill_versions.storage_path', storage_path
        FROM skill_versions WHERE NULLIF(storage_path, '') IS NOT NULL
        UNION ALL
        SELECT 'prefix', 'skill_contributions.storage_path', storage_path
        FROM skill_contributions WHERE NULLIF(storage_path, '') IS NOT NULL
        ORDER BY 1, 2, 3;
    """
    rows = _psql_rows(database_url, query)
    result: list[tuple[str, str, str]] = []
    for row in rows:
        if len(row) != 3:
            raise BackupRestoreError(
                "object_reference_query_invalid",
                "object reference query returned an invalid row",
            )
        result.append((row[0], row[1], row[2]))
    return result


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _public_base_tables(database_url: str) -> tuple[str, ...]:
    rows = _psql_rows(
        database_url,
        "SELECT c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' AND n.nspname = 'public' "
        "ORDER BY c.relname;",
    )
    return tuple(row[0] for row in rows if row and row[0])


def _table_row_counts(
    database_url: str,
    tables: Sequence[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        rows = _psql_rows(
            database_url,
            f"SELECT count(*) FROM {_quote_identifier(table)};",
        )
        if rows and rows[0] and rows[0][0]:
            counts[table] = int(rows[0][0])
    return counts


def _fk_constraints(database_url: str) -> list[dict[str, object]]:
    """Validated public-schema FKs with positionally paired child/parent columns."""
    rows = _psql_rows(
        database_url,
        "SELECT con.conname AS constraint_name, "
        "child.relname AS child_table, parent.relname AS parent_table, "
        "att.attname AS child_column, patt.attname AS parent_column "
        "FROM pg_constraint con "
        "JOIN pg_class child ON child.oid = con.conrelid "
        "JOIN pg_class parent ON parent.oid = con.confrelid "
        "JOIN pg_namespace nsp ON nsp.oid = con.connamespace "
        "CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ord(attnum, ordinality) "
        "CROSS JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS pord(attnum, pordinality) "
        "JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ord.attnum "
        "JOIN pg_attribute patt ON patt.attrelid = con.confrelid AND patt.attnum = pord.attnum "
        "WHERE con.contype = 'f' AND nsp.nspname = 'public' AND con.convalidated "
        "AND ord.ordinality = pord.pordinality "
        "ORDER BY con.conname, ord.ordinality;",
    )
    grouped: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for row in rows:
        if len(row) != 5:
            raise BackupRestoreError(
                "fk_query_invalid",
                "foreign key metadata query returned an invalid row",
            )
        constraint_name, child_table, parent_table, child_column, parent_column = row
        entry = grouped.get(constraint_name)
        if entry is None:
            entry = {
                "constraint_name": constraint_name,
                "child_table": child_table,
                "parent_table": parent_table,
                "columns": [],
            }
            grouped[constraint_name] = entry
            order.append(constraint_name)
        columns = entry["columns"]
        assert isinstance(columns, list)
        columns.append([child_column, parent_column])
    return [grouped[name] for name in order]


def _fk_orphan_query(fk: Mapping[str, object]) -> str:
    """MATCH SIMPLE orphan scan: all child columns non-null and no parent row."""
    child = _quote_identifier(str(fk["child_table"]))
    parent = _quote_identifier(str(fk["parent_table"]))
    columns = fk["columns"]
    assert isinstance(columns, list) and columns
    joins = " AND ".join(
        f"p.{_quote_identifier(parent_column)} = c.{_quote_identifier(child_column)}"
        for child_column, parent_column in columns
    )
    child_not_null = " AND ".join(
        f"c.{_quote_identifier(child_column)} IS NOT NULL"
        for child_column, _ in columns
    )
    parent_missing = " AND ".join(
        f"p.{_quote_identifier(parent_column)} IS NULL" for _, parent_column in columns
    )
    return (
        f"SELECT count(*) FROM {child} AS c "
        f"LEFT JOIN {parent} AS p ON {joins} "
        f"WHERE {child_not_null} AND {parent_missing};"
    )


def _fk_orphan_count(database_url: str, fk: Mapping[str, object]) -> int:
    rows = _psql_rows(database_url, _fk_orphan_query(fk))
    if rows and rows[0] and rows[0][0]:
        return int(rows[0][0])
    return 0


def _duplicate_column_values(
    database_url: str,
    table: str,
    column: str,
) -> list[tuple[str, int]]:
    rows = _psql_rows(
        database_url,
        f"SELECT {_quote_identifier(column)}, count(*) "
        f"FROM {_quote_identifier(table)} "
        f"GROUP BY {_quote_identifier(column)} HAVING count(*) > 1 ORDER BY 1;",
    )
    return [(row[0], int(row[1])) for row in rows if len(row) == 2]


def _outbox_nonterminal_count(
    database_url: str,
    *,
    table: str = OUTBOX_TABLE,
    statuses: Sequence[str] = OUTBOX_NONTERMINAL_STATUSES,
) -> int:
    quoted_statuses = ", ".join(f"'{status}'" for status in statuses)
    rows = _psql_rows(
        database_url,
        f"SELECT count(*) FROM {_quote_identifier(table)} "
        f"WHERE dispatch_status IN ({quoted_statuses});",
    )
    if rows and rows[0] and rows[0][0]:
        return int(rows[0][0])
    return 0


def _record_verification_baseline(database_url: str) -> dict[str, object]:
    """Sample row counts and FK shape under quiesce for later drill comparison."""
    tables = _public_base_tables(database_url)
    counts = _table_row_counts(database_url, tables)
    fk_constraints = _fk_constraints(database_url)
    return {
        "table_row_counts": counts,
        "fk_constraint_count": len(fk_constraints),
        "measured_at": _utcnow(),
    }


def _consistency_boundary_record(
    *,
    quiesce_completed_at: str,
    dump_started_at: str,
    dump_completed_at: str,
) -> dict[str, object]:
    quiesce_done = datetime.fromisoformat(quiesce_completed_at)
    dump_start = datetime.fromisoformat(dump_started_at)
    dump_done = datetime.fromisoformat(dump_completed_at)
    return {
        "mode": "operator_quiesce_commands",
        "writes_stopped_before_snapshot": True,
        "resume_runs_only_after_artifacts_and_manifest_are_complete": True,
        "quiesce_completed_at": quiesce_completed_at,
        "dump_started_at": dump_started_at,
        "dump_completed_at": dump_completed_at,
        # Upper bound on data age in the backup: writes stopped at quiesce
        # completion, the dump snapshot is established at dump start.
        "measured_rpo_upper_bound_seconds": round(
            max((dump_start - quiesce_done).total_seconds(), 0.0), 3
        ),
        "dump_duration_seconds": round(
            max((dump_done - dump_start).total_seconds(), 0.0), 3
        ),
    }


def _measured_rpo_from_manifest(manifest: Mapping[str, object]) -> RpoEvidence:
    boundary = manifest.get("consistency_boundary")
    if not isinstance(boundary, Mapping):
        return {
            "measured": False,
            "seconds": None,
            "basis": DRILL_RPO_BASIS,
            "measured_at": "backup",
            "reason": "consistency_boundary_absent",
        }
    quiesce_completed_at = boundary.get("quiesce_completed_at")
    dump_started_at = boundary.get("dump_started_at")
    if not isinstance(quiesce_completed_at, str) or not isinstance(
        dump_started_at, str
    ):
        return {
            "measured": False,
            "seconds": None,
            "basis": DRILL_RPO_BASIS,
            "measured_at": "backup",
            "reason": "boundary_timestamps_absent",
        }
    try:
        seconds = round(
            max(
                (
                    datetime.fromisoformat(dump_started_at)
                    - datetime.fromisoformat(quiesce_completed_at)
                ).total_seconds(),
                0.0,
            ),
            3,
        )
    except ValueError:
        return {
            "measured": False,
            "seconds": None,
            "basis": DRILL_RPO_BASIS,
            "measured_at": "backup",
            "reason": "boundary_timestamps_invalid",
        }
    return {
        "measured": True,
        "seconds": seconds,
        "basis": DRILL_RPO_BASIS,
        "measured_at": "backup",
    }


def _redis_env_from_url(redis_url: str) -> dict[str, str]:
    parsed = urlsplit(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise BackupRestoreError(
            "restore_redis_url_invalid",
            "target Redis URL must use the redis or rediss scheme",
            details={"url": redis_url},
        )
    database = parsed.path.lstrip("/") or "0"
    if not database.isdigit():
        raise BackupRestoreError(
            "restore_redis_url_invalid",
            "target Redis URL database must be numeric",
            details={"url": redis_url},
        )
    return {
        "REDIS_HOST": parsed.hostname or "localhost",
        "REDIS_PORT": str(parsed.port or 6379),
        "REDIS_PASSWORD": parsed.password or "",
        "REDIS_DB": database,
    }


def _target_runtime_environment(
    database_url: str,
    redis_url: str,
    object_store: ObjectStoreTarget,
) -> dict[str, str]:
    """Bind a reconciler subprocess only to the restored target's services."""
    environment = {"database_url": database_url, "DATABASE_URL": database_url}
    environment.update(_redis_env_from_url(redis_url))
    environment.update(
        {
            "MINIO_ENDPOINT": object_store.endpoint,
            "MINIO_ACCESS_KEY": object_store.access_key,
            "MINIO_SECRET_KEY": object_store.secret_key,
            "MINIO_BUCKET": object_store.bucket,
            "MINIO_SECURE": "true" if object_store.secure else "false",
        }
    )
    return environment


def _validate_reconciler_spec(specification: str) -> tuple[str, str]:
    module_name, separator, attribute_name = specification.partition(":")
    if not separator or not module_name or not attribute_name:
        raise BackupRestoreError(
            "queue_reconciler_invalid",
            "queue reconciler must use module:function notation",
            details={"reconciler": specification},
        )
    if not attribute_name.isidentifier() or not all(
        part.isidentifier() for part in module_name.split(".")
    ):
        raise BackupRestoreError(
            "queue_reconciler_invalid",
            "queue reconciler must name an importable module and function",
            details={"reconciler": specification},
        )
    return module_name, attribute_name


def _run_reconciler_subprocess(
    specification: str,
    *,
    target_database_url: str,
    target_redis_url: str,
    target_object_store: ObjectStoreTarget,
    repo_root: Path | None,
) -> dict[str, object]:
    """Replay a durable reconciler against the restored target only.

    The reconciler runs in a fresh interpreter whose runtime settings resolve
    to the target database, Redis, and object store, so it cannot touch source
    rows, queues, or objects during restore.
    """
    module_name, attribute_name = _validate_reconciler_spec(specification)
    script = (
        "import asyncio, json\n"
        f"from {module_name} import {attribute_name} as _reconciler\n"
        "async def _main():\n"
        "    value = _reconciler()\n"
        "    if hasattr(value, '__await__'):\n"
        "        value = await value\n"
        "    if value is None or isinstance(value, (str, int, float, bool)):\n"
        "        result = value\n"
        "    else:\n"
        "        result = {'result_type': type(value).__name__}\n"
        "    print(json.dumps({'reconciler': _reconciler.__name__, 'result': result}, sort_keys=True))\n"
        "asyncio.run(_main())\n"
    )
    environment = os.environ.copy()
    environment.update(
        _target_runtime_environment(
            target_database_url,
            target_redis_url,
            target_object_store,
        )
    )
    output = _run_checked(
        (sys.executable, "-c", script),
        label=f"durable queue reconciler {specification}",
        cwd=_repo_root(repo_root),
        env=environment,
    )
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise BackupRestoreError(
            "queue_reconciler_output_invalid",
            "durable queue reconciler returned unparseable output",
            details={"reconciler": specification},
        ) from exc
    if not isinstance(parsed, dict):
        raise BackupRestoreError(
            "queue_reconciler_output_invalid",
            "durable queue reconciler returned an invalid result",
            details={"reconciler": specification},
        )
    return {"reconciler": specification, "result": parsed.get("result")}


async def _redis_evidence(
    redis_url: str,
    expected_job_ids: Sequence[str],
) -> RedisEvidence:
    connection = redis.from_url(redis_url)
    try:
        dbsize = int(await connection.dbsize())
        keys = [
            key.decode("utf-8", errors="replace")
            if isinstance(key, bytes)
            else str(key)
            async for key in connection.scan_iter(match="arq:*", count=500)
        ]
        missing_jobs = [
            job_id
            for job_id in expected_job_ids
            if not any(job_id in key for key in keys)
        ]
        return {
            "dbsize": dbsize,
            "arq_key_count": len(keys),
            "expected_arq_job_ids": len(expected_job_ids),
            "enqueued_outbox_without_arq_job": missing_jobs,
        }
    finally:
        await connection.aclose()


def _verify_restored_object_hashes(
    loaded: LoadedBackup,
    request: RestoreRequest,
    client: Minio,
) -> ObjectHashVerification:
    """Re-read every restored object from the target bucket and hash it."""
    object_entries = loaded.manifest["objects"]
    assert isinstance(object_entries, list)
    checked = 0
    mismatches: list[dict[str, object]] = []
    for index, object_entry in enumerate(object_entries, start=1):
        assert isinstance(object_entry, Mapping)
        object_key = object_entry["object_key"]
        artifact = object_entry["artifact"]
        assert isinstance(object_key, str) and isinstance(artifact, Mapping)
        expected_sha256 = artifact.get("payload_sha256")
        expected_bytes = artifact.get("payload_bytes")
        if not isinstance(expected_sha256, str) or not isinstance(expected_bytes, int):
            mismatches.append({"object_key": object_key, "reason": "record_invalid"})
            continue
        response = client.get_object(request.target_object_store.bucket, object_key)
        with tempfile.NamedTemporaryFile(
            prefix="cygnus-drill-object-", delete=False
        ) as temporary:
            verification_path = Path(temporary.name)
        try:
            _stream_response_to_file(response, verification_path)
            actual_sha256, actual_bytes = _file_digest(verification_path)
        finally:
            verification_path.unlink(missing_ok=True)
        checked += 1
        if actual_sha256 != expected_sha256 or actual_bytes != expected_bytes:
            mismatches.append({"object_key": object_key, "object_index": index})
    return {
        "checked": checked,
        "matched": checked - len(mismatches),
        "mismatches": mismatches,
    }


def _verify_encrypted_config_decryptability(
    database_url: str,
    key_material: Mapping[str, str],
) -> EncryptedConfigVerification:
    """Decrypt restored sensitive app_config values with the supplied secret.

    This proves encrypted-config key continuity: the same secret material that
    matched the backup fingerprint must decrypt the restored ciphertext.
    """
    secret = key_material.get("runtime.secret_key")
    if not secret:
        return {
            "checked": False,
            "reason": "runtime.secret_key_not_supplied",
            "sensitive_keys_checked": 0,
            "decrypt_ok": 0,
            "decrypt_failures": [],
        }
    from cryptography.fernet import Fernet, InvalidToken
    from cygnus.runtime.services.config_service import _derive_fernet_key, _is_sensitive

    rows = _psql_rows(
        database_url,
        "SELECT key, value FROM app_config ORDER BY key;",
    )
    sensitive = [
        (row[0], row[1])
        for row in rows
        if len(row) == 2 and row[0] and row[1] and _is_sensitive(row[0])
    ]
    fernet = Fernet(_derive_fernet_key(secret))
    decrypt_ok = 0
    failures: list[dict[str, str]] = []
    for key, value in sensitive:
        try:
            fernet.decrypt(value.encode("utf-8"))
            decrypt_ok += 1
        except (InvalidToken, ValueError):
            failures.append({"key": key})
    return {
        "checked": True,
        "sensitive_keys_checked": len(sensitive),
        "decrypt_ok": decrypt_ok,
        "decrypt_failures": failures,
    }


def _verify_restored_target(
    loaded: LoadedBackup,
    request: RestoreRequest,
) -> VerificationEvidence:
    manifest = loaded.manifest
    baseline = manifest.get("verification")
    expected_counts: dict[str, int] = {}
    if isinstance(baseline, Mapping) and isinstance(
        baseline.get("table_row_counts"), Mapping
    ):
        expected_counts = {
            str(key): int(value) for key, value in baseline["table_row_counts"].items()
        }

    mismatches: list[dict[str, object]] = []
    for table, expected in sorted(expected_counts.items()):
        rows = _psql_rows(
            request.target_database_url,
            f"SELECT count(*) FROM {_quote_identifier(table)};",
        )
        actual = int(rows[0][0]) if rows and rows[0] and rows[0][0] else 0
        if actual != expected:
            mismatches.append({"table": table, "expected": expected, "actual": actual})

    target_client = _client_for(request.target_object_store)
    object_hashes = _verify_restored_object_hashes(loaded, request, target_client)

    fks = _fk_constraints(request.target_database_url)
    orphans: list[ForeignKeyOrphan] = []
    for fk in fks:
        orphan_count = _fk_orphan_count(request.target_database_url, fk)
        if orphan_count:
            orphans.append(
                {
                    "constraint_name": str(fk["constraint_name"]),
                    "orphan_rows": orphan_count,
                }
            )

    ledger_duplicates = _duplicate_column_values(
        request.target_database_url, LEDGER_TABLE, LEDGER_IDEMPOTENCY_COLUMN
    )
    outbox_duplicates = _duplicate_column_values(
        request.target_database_url, OUTBOX_TABLE, OUTBOX_JOB_ID_COLUMN
    )
    source_dispatch_duplicates = _duplicate_column_values(
        request.target_database_url,
        SOURCE_DISPATCH_OUTBOX_TABLE,
        OUTBOX_JOB_ID_COLUMN,
    )

    def _count_compare(table: str) -> CountComparison:
        rows = _psql_rows(
            request.target_database_url,
            f"SELECT count(*) FROM {_quote_identifier(table)};",
        )
        actual = int(rows[0][0]) if rows and rows[0] and rows[0][0] else 0
        if table in expected_counts:
            expected = expected_counts[table]
            return {
                "expected": expected,
                "actual": actual,
                "matched": expected == actual,
                "measured": True,
            }
        return {
            "expected": None,
            "actual": actual,
            "matched": None,
            "measured": False,
        }

    nonterminal = _outbox_nonterminal_count(request.target_database_url)
    source_dispatch_nonterminal = _outbox_nonterminal_count(
        request.target_database_url,
        table=SOURCE_DISPATCH_OUTBOX_TABLE,
        statuses=SOURCE_DISPATCH_NONTERMINAL_STATUSES,
    )

    def _enqueued_job_ids(table: str) -> list[str]:
        return [
            str(row[0])
            for row in _psql_rows(
                request.target_database_url,
                f"SELECT {_quote_identifier(OUTBOX_JOB_ID_COLUMN)} "
                f"FROM {_quote_identifier(table)} "
                "WHERE dispatch_status = 'enqueued' ORDER BY 1;",
            )
            if row and row[0]
        ]

    enqueued_job_ids = _enqueued_job_ids(OUTBOX_TABLE)
    enqueued_job_ids.extend(_enqueued_job_ids(SOURCE_DISPATCH_OUTBOX_TABLE))

    return {
        "table_row_counts": {
            "baseline_tables": len(expected_counts),
            "checked": len(expected_counts),
            "matched": len(expected_counts) - len(mismatches),
            "mismatches": mismatches,
            "measured": bool(expected_counts),
        },
        "object_hashes": object_hashes,
        "foreign_keys": {
            "constraints_checked": len(fks),
            "orphan_rows": sum(orphan["orphan_rows"] for orphan in orphans),
            "orphans": orphans,
        },
        "idempotency_receipts": {
            "ledger_table": LEDGER_TABLE,
            "ledger_event_duplicate_idempotency_keys": [
                list(duplicate) for duplicate in ledger_duplicates
            ],
            "ledger_event_count": _count_compare(LEDGER_TABLE),
            "outbox_table": OUTBOX_TABLE,
            "outbox_job_id_duplicates": [
                list(duplicate) for duplicate in outbox_duplicates
            ],
            "outbox_row_count": _count_compare(OUTBOX_TABLE),
            "source_dispatch_table": SOURCE_DISPATCH_OUTBOX_TABLE,
            "source_dispatch_job_id_duplicates": [
                list(duplicate) for duplicate in source_dispatch_duplicates
            ],
            "source_dispatch_row_count": _count_compare(SOURCE_DISPATCH_OUTBOX_TABLE),
        },
        "pending_jobs": {
            "nonterminal_outbox_rows_after_replay": nonterminal,
            "source_dispatch_nonterminal_rows_after_replay": source_dispatch_nonterminal,
            "checked_statuses": list(OUTBOX_NONTERMINAL_STATUSES),
        },
        "redis": asyncio.run(
            _redis_evidence(request.target_redis_url, enqueued_job_ids)
        ),
        "encrypted_config": _verify_encrypted_config_decryptability(
            request.target_database_url, request.key_material
        ),
    }


def _drill_checks(
    verification: VerificationEvidence,
    rpo: RpoEvidence,
    rto_seconds: float,
    objectives: Mapping[str, float | None],
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []

    counts = verification["table_row_counts"]
    counts_mismatches = counts.get("mismatches") or []
    checks.append(
        {
            "name": "table_row_counts",
            "passed": bool(counts.get("measured")) and not counts_mismatches,
            "detail": (
                f"{counts.get('matched')}/{counts.get('baseline_tables')} tables matched"
                if counts.get("measured")
                else "backup carries no row-count baseline; count verification not measured"
            ),
        }
    )

    hashes = verification["object_hashes"]
    checks.append(
        {
            "name": "object_hashes",
            "passed": not (hashes.get("mismatches") or []),
            "detail": f"{hashes.get('matched')}/{hashes.get('checked')} objects matched",
        }
    )

    fks = verification["foreign_keys"]
    checks.append(
        {
            "name": "foreign_key_integrity",
            "passed": not (fks.get("orphans") or []),
            "detail": (
                f"{fks.get('constraints_checked')} constraints checked, "
                f"{fks.get('orphan_rows')} orphan rows"
            ),
        }
    )

    receipts = verification["idempotency_receipts"]
    ledger_duplicates = receipts.get("ledger_event_duplicate_idempotency_keys") or []
    outbox_duplicates = receipts.get("outbox_job_id_duplicates") or []
    source_dispatch_duplicates = receipts.get("source_dispatch_job_id_duplicates") or []
    ledger_count = receipts.get("ledger_event_count") or {}
    outbox_count = receipts.get("outbox_row_count") or {}
    source_dispatch_count: Mapping[str, object] = (
        receipts.get("source_dispatch_row_count") or {}
    )
    checks.append(
        {
            "name": "idempotency_receipts",
            "passed": (
                not ledger_duplicates
                and not outbox_duplicates
                and not source_dispatch_duplicates
                and ledger_count.get("matched") is not False
                and outbox_count.get("matched") is not False
                and source_dispatch_count.get("matched") is not False
            ),
            "detail": (
                f"{len(ledger_duplicates)} duplicate ledger idempotency keys, "
                f"{len(outbox_duplicates)} duplicate pre-review job ids, "
                f"{len(source_dispatch_duplicates)} duplicate source-dispatch job ids, "
                f"ledger rows "
                f"{'matched' if ledger_count.get('matched') else 'not measured'}, "
                f"pre-review rows "
                f"{'matched' if outbox_count.get('matched') else 'not measured'}, "
                f"source-dispatch rows "
                f"{'matched' if source_dispatch_count.get('matched') else 'not measured'}"
            ),
        }
    )

    pending = verification["pending_jobs"]
    nonterminal = pending.get("nonterminal_outbox_rows_after_replay") or 0
    source_dispatch_nonterminal = (
        pending.get("source_dispatch_nonterminal_rows_after_replay") or 0
    )
    checks.append(
        {
            "name": "pending_jobs_replayed",
            "passed": nonterminal == 0 and source_dispatch_nonterminal == 0,
            "detail": (
                f"{nonterminal} non-terminal pre-review rows and "
                f"{source_dispatch_nonterminal} non-terminal source-dispatch rows "
                "remain after replay"
            ),
        }
    )

    redis_evidence = verification["redis"]
    checks.append(
        {
            "name": "redis_replay",
            "passed": not (redis_evidence.get("enqueued_outbox_without_arq_job") or []),
            "detail": (
                f"dbsize={redis_evidence.get('dbsize')}, "
                f"arq keys={redis_evidence.get('arq_key_count')}, "
                f"expected={redis_evidence.get('expected_arq_job_ids')}, "
                f"missing={redis_evidence.get('enqueued_outbox_without_arq_job')}"
            ),
        }
    )

    config = verification["encrypted_config"]
    checks.append(
        {
            "name": "encrypted_config_continuity",
            "passed": bool(config.get("checked"))
            and not (config.get("decrypt_failures") or []),
            "detail": (
                f"{config.get('decrypt_ok')}/{config.get('sensitive_keys_checked')} "
                "sensitive values decrypt"
                if config.get("checked")
                else "runtime.secret_key not supplied; continuity not measured"
            ),
        }
    )

    rpo_seconds = rpo["seconds"]
    rpo_max_seconds = objectives.get("rpo_max_seconds")
    if rpo.get("measured"):
        assert rpo_seconds is not None
        checks.append(
            {
                "name": "rpo_objective",
                "passed": (
                    rpo_max_seconds is None or rpo_seconds <= float(rpo_max_seconds)
                ),
                "detail": (
                    f"measured rpo {rpo_seconds}s (max {rpo_max_seconds}s)"
                    if rpo_max_seconds is not None
                    else f"measured rpo {rpo_seconds}s (no objective)"
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "rpo_objective",
                "passed": rpo_max_seconds is None,
                "detail": "rpo not measured; no objective can be asserted",
            }
        )

    rto_max_seconds = objectives.get("rto_max_seconds")
    checks.append(
        {
            "name": "rto_objective",
            "passed": (
                rto_max_seconds is None or rto_seconds <= float(rto_max_seconds)
            ),
            "detail": (
                f"measured rto {rto_seconds}s (max {rto_max_seconds}s)"
                if rto_max_seconds is not None
                else f"measured rto {rto_seconds}s (no objective)"
            ),
        }
    )
    return checks


def _drill_requires_explicit_objectives(
    manifest: Mapping[str, object],
    *,
    require_recovery_objectives: bool,
) -> bool:
    """Return whether this drill may serve as production/release evidence."""
    if require_recovery_objectives:
        return True
    source = manifest.get("source")
    return (
        isinstance(source, Mapping)
        and str(source.get("environment", "")).strip().lower() == "production"
    )


def _require_drill_objectives(
    objectives: Mapping[str, float | None],
    refs: RecoveryObjectiveRefs,
    *,
    required: bool,
    source: object,
) -> None:
    if not required:
        return
    missing = [name for name, value in objectives.items() if value is None]
    missing.extend(name for name, value in refs.to_dict().items() if value is None)
    if missing:
        raise BackupRestoreError(
            "drill_recovery_objectives_required",
            "production/release drill evidence requires explicit approved RPO/RTO objectives and references before any restore writes",
            details={
                "source": source,
                "missing": missing,
                "required_arguments": [
                    "--rpo-max-seconds",
                    "--rto-max-seconds",
                    "--rpo-objective-ref",
                    "--rto-objective-ref",
                ],
            },
        )


def run_drill(
    request: RestoreRequest,
    *,
    rpo_max_seconds: float | None = None,
    rto_max_seconds: float | None = None,
    rpo_objective_ref: str | None = None,
    rto_objective_ref: str | None = None,
    expected_release_identity: ReleaseIdentity | None = None,
    require_recovery_objectives: bool = False,
) -> dict[str, object]:
    """Restore into a disposable isolated target and emit measured PASS/FAIL evidence.

    A production-source backup, or a caller explicitly requesting release
    evidence, must supply both approved RPO and RTO objectives before the
    destructive restore begins. Development drills remain useful integrity
    exercises without an objective, but cannot be represented as release proof.

    The drill performs the exact destructive restore pipeline into an empty
    target, then measures recovery evidence: row counts vs the backup baseline,
    object hashes, FK integrity, idempotency receipts, pending outbox jobs, and
    encrypted-config decryptability. RPO is reported from the value measured at
    backup time; RTO is measured across this drill. Neither value is ever
    invented: unmeasured fields carry ``measured: false`` and null seconds.
    """
    if request.target_environment != "isolated":
        raise BackupRestoreError(
            "drill_target_must_be_isolated",
            "a recovery drill only runs against a disposable isolated target",
            details={"target_environment": request.target_environment},
        )
    if request.dry_run:
        raise BackupRestoreError(
            "drill_requires_live_target",
            "a recovery drill measures RTO and recovery evidence against a live restore; dry-run is unsupported",
        )
    loaded = load_backup(
        request.backup_dir,
        request.transforms,
        require_protected_manifest=False,
    )
    manifest = loaded.manifest
    objectives = {
        "rpo_max_seconds": (
            round(rpo_max_seconds, 3) if rpo_max_seconds is not None else None
        ),
        "rto_max_seconds": (
            round(rto_max_seconds, 3) if rto_max_seconds is not None else None
        ),
    }
    objective_refs = _normalize_objective_refs(
        RecoveryObjectiveRefs(
            rpo_objective_ref=rpo_objective_ref,
            rto_objective_ref=rto_objective_ref,
        )
    )
    objectives_required = _drill_requires_explicit_objectives(
        manifest,
        require_recovery_objectives=require_recovery_objectives,
    )
    _require_drill_objectives(
        objectives,
        objective_refs,
        required=objectives_required,
        source=manifest.get("source"),
    )
    recorded_release_identity = _release_identity_from_manifest(
        manifest,
        required=objectives_required,
    )
    if require_recovery_objectives or expected_release_identity is not None:
        recorded_release_identity = _assert_release_identity_matches_expected(
            manifest,
            expected=expected_release_identity,
            required=require_recovery_objectives,
        )

    restore_started = time.monotonic()
    restore_report = run_restore(request)
    rto_seconds = round(time.monotonic() - restore_started, 3)
    verification = _verify_restored_target(loaded, request)
    rpo = _measured_rpo_from_manifest(manifest)
    checks = _drill_checks(verification, rpo, rto_seconds, objectives)
    failed = [check for check in checks if not check["passed"]]
    return {
        "report_format": DRILL_REPORT_FORMAT,
        "operation": "drill",
        "status": "failed" if failed else "passed",
        "backup_dir": str(loaded.package_dir),
        "backup_created_at": manifest.get("created_at"),
        "source": manifest.get("source"),
        "release_identity": (
            recorded_release_identity.to_dict()
            if recorded_release_identity is not None
            else None
        ),
        "release_identity_requirement": {
            "manifest_required": objectives_required,
            "expected_match_required": require_recovery_objectives,
            "expected_match_verified": expected_release_identity is not None,
        },
        "target": {
            "environment": request.target_environment,
            "identity": request.target_id,
        },
        "rpo": rpo,
        "rto": {
            "measured": True,
            "seconds": rto_seconds,
            "basis": DRILL_RTO_BASIS,
            "measured_at": "drill",
        },
        "objectives": objectives,
        "objective_refs": objective_refs.to_dict(),
        "objective_requirement": {
            "required": objectives_required,
            "source": (
                "explicit_release_mode"
                if require_recovery_objectives
                else "production_source_backup"
                if objectives_required
                else "non_production_integrity_drill"
            ),
            "both_declared": (
                all(value is not None for value in objectives.values())
                and all(
                    value is not None for value in objective_refs.to_dict().values()
                )
            ),
        },
        "verification": verification,
        "restore": {
            "completed_stages": restore_report.get("completed_stages"),
            "object_count": restore_report.get("object_count"),
            "validated_key_ids": restore_report.get("validated_key_ids"),
        },
        "checks": checks,
        "generated_at": _utcnow(),
    }


def reconcile_object_references(
    database_url: str,
    client: Minio,
    bucket: str,
) -> dict[str, object]:
    target_keys = {
        object_name
        for item in client.list_objects(bucket, recursive=True)
        if (object_name := item.object_name)
    }
    missing: list[dict[str, str]] = []
    references = _database_object_references(database_url)
    for kind, owner, object_key in references:
        exists = (
            object_key in target_keys
            if kind == "exact"
            else any(key.startswith(object_key) for key in target_keys)
        )
        if not exists:
            missing.append({"kind": kind, "owner": owner, "object_key": object_key})
    report = {
        "reference_count": len(references),
        "target_object_count": len(target_keys),
        "missing_references": missing,
    }
    if missing:
        raise BackupRestoreError(
            "object_reference_reconciliation_failed",
            "restored database references objects absent from the target bucket",
            details=report,
        )
    return report


def _load_reconciler(specification: str):
    """Resolve a recorded reconciler in-process for plan validation only.

    Execution always happens in a fresh interpreter (see
    :func:`_run_reconciler_subprocess`) so runtime settings resolve to the
    restored target, never to the operator host's source runtime.
    """
    module_name, attribute_name = _validate_reconciler_spec(specification)
    try:
        module = import_module(module_name)
        callable_object = getattr(module, attribute_name)
    except (ImportError, AttributeError) as exc:
        raise BackupRestoreError(
            "queue_reconciler_unavailable",
            "recorded durable queue reconciler is unavailable in this runtime",
            details={"reconciler": specification},
        ) from exc
    if not callable(callable_object):
        raise BackupRestoreError(
            "queue_reconciler_invalid",
            "recorded queue reconciler is not callable",
            details={"reconciler": specification},
        )
    return callable_object


async def _reset_redis_and_reconcile(
    redis_url: str,
    reconcilers: tuple[str, ...],
    *,
    dry_run: bool,
    target_database_url: str,
    target_object_store: ObjectStoreTarget,
    repo_root: Path | None,
) -> dict[str, object]:
    connection = redis.from_url(redis_url)
    try:
        await connection.ping()
        if dry_run:
            return {
                "redis_reset": False,
                "reconcilers": list(reconcilers),
                "mode": "dry_run",
            }
        await connection.flushdb()
        dbsize_after_flush = int(await connection.dbsize())
        results: list[dict[str, object]] = []
        for specification in reconcilers:
            _load_reconciler(specification)  # fail fast on an unavailable reconciler
            results.append(
                _run_reconciler_subprocess(
                    specification,
                    target_database_url=target_database_url,
                    target_redis_url=redis_url,
                    target_object_store=target_object_store,
                    repo_root=repo_root,
                )
            )
        return {
            "redis_reset": True,
            "dbsize_after_flush": dbsize_after_flush,
            "reconcilers": results,
            "mode": "completed",
        }
    finally:
        await connection.aclose()


def _manifest_reconcilers(
    manifest: Mapping[str, object], override: tuple[str, ...] | None
) -> tuple[str, ...]:
    if override is not None:
        if not override:
            raise BackupRestoreError(
                "queue_reconciler_missing",
                "restore cannot skip durable outbox reconciliation",
            )
        return override
    queue_policy = manifest.get("queue_reconciliation")
    if not isinstance(queue_policy, Mapping):
        raise BackupRestoreError(
            "manifest_invalid", "queue reconciliation policy is invalid"
        )
    reconcilers = queue_policy.get("reconcilers")
    if not isinstance(reconcilers, list) or not all(
        isinstance(item, str) for item in reconcilers
    ):
        raise BackupRestoreError(
            "queue_reconciler_missing",
            "backup does not contain a valid durable queue reconciliation policy",
        )
    if not reconcilers:
        raise BackupRestoreError(
            "queue_reconciler_missing",
            "backup has no durable queue reconcilers",
        )
    return tuple(reconcilers)


def _restore_preflight(
    loaded: LoadedBackup, request: RestoreRequest
) -> tuple[str, ...]:
    _validate_target_guard(loaded.manifest, request)
    validated_keys = _validate_key_prerequisites(loaded.manifest, request.key_material)
    _assert_backup_revision_compatible(loaded.manifest, request.repo_root)
    _validate_plaintext_artifacts(loaded, request.transforms)
    _validate_custom_dump(loaded, request.transforms)
    return tuple(validated_keys)


def run_restore(request: RestoreRequest) -> dict[str, object]:
    """Restore a complete package into an empty target, then replay durable work."""

    require_protected_manifest = request.target_environment == "production"
    loaded = load_backup(
        request.backup_dir,
        request.transforms,
        require_protected_manifest=require_protected_manifest,
    )
    validated_keys = _restore_preflight(loaded, request)
    target_client = _client_for(request.target_object_store)
    reconcilers = _manifest_reconcilers(loaded.manifest, request.queue_reconcilers)

    # These checks are read-only and intentionally run for a dry run too.
    _ensure_empty_target_database(request.target_database_url)
    bucket_existed, target_bucket_objects = _ensure_empty_target_bucket(
        target_client,
        request.target_object_store.bucket,
        create=not request.dry_run,
    )
    queue_plan = asyncio.run(
        _reset_redis_and_reconcile(
            request.target_redis_url,
            reconcilers,
            dry_run=True,
            target_database_url=request.target_database_url,
            target_object_store=request.target_object_store,
            repo_root=request.repo_root,
        )
    )
    if request.dry_run:
        return {
            "report_format": "cygnus-restore-report/v1",
            "operation": "restore",
            "status": "dry_run",
            "backup_dir": str(loaded.package_dir),
            "target": {
                "environment": request.target_environment,
                "identity": request.target_id,
                "bucket_existed": bucket_existed,
                "bucket_object_count": target_bucket_objects,
            },
            "validated_key_ids": list(validated_keys),
            "queue_reconciliation": queue_plan,
            "generated_at": _utcnow(),
        }

    completed_stages: list[str] = []
    try:
        _restore_database(loaded, request)
        completed_stages.append("database_restored")
        object_count = _restore_objects(loaded, request, target_client)
        completed_stages.append("objects_restored")
        _run_forward_migrations(request.target_database_url, request.repo_root)
        completed_stages.append("forward_migrations_applied")
        reference_report = reconcile_object_references(
            request.target_database_url,
            target_client,
            request.target_object_store.bucket,
        )
        completed_stages.append("object_references_reconciled")
        queue_report = asyncio.run(
            _reset_redis_and_reconcile(
                request.target_redis_url,
                reconcilers,
                dry_run=False,
                target_database_url=request.target_database_url,
                target_object_store=request.target_object_store,
                repo_root=request.repo_root,
            )
        )
        completed_stages.append("durable_outboxes_replayed")
    except BaseException as exc:
        if isinstance(exc, BackupRestoreError):
            error = exc
        else:
            error = BackupRestoreError(
                "restore_execution_failed",
                "restore did not complete; the isolated target may contain partial state and must be discarded",
                details={"error_type": type(exc).__name__},
            )
        error.details.setdefault("completed_stages", completed_stages)
        error.details.setdefault("target_requires_discard", True)
        raise error

    return {
        "report_format": "cygnus-restore-report/v1",
        "operation": "restore",
        "status": "completed",
        "backup_dir": str(loaded.package_dir),
        "target": {
            "environment": request.target_environment,
            "identity": request.target_id,
        },
        "validated_key_ids": list(validated_keys),
        "object_count": object_count,
        "object_reconciliation": reference_report,
        "queue_reconciliation": queue_report,
        "completed_stages": completed_stages,
        "generated_at": _utcnow(),
    }


def run_inventory(
    backup_dir: Path,
    transforms: TransformCommands,
    *,
    key_material_file: str | None = None,
    report_format: str = "cygnus-backup-inventory/v1",
) -> dict[str, object]:
    loaded = load_backup(backup_dir, transforms)
    _validate_plaintext_artifacts(loaded, transforms)
    manifest = loaded.manifest
    database = manifest["database"]
    assert isinstance(database, Mapping)
    inventory = manifest["configuration_inventory"]
    assert isinstance(inventory, Mapping)
    objects = manifest["objects"]
    key_material = manifest["key_material"]
    assert isinstance(objects, list)
    assert isinstance(key_material, Mapping)
    key_material_status: dict[str, object] | None = None
    if key_material_file:
        supplied = _load_key_material_file(key_material_file)
        validated = _validate_key_prerequisites(manifest, supplied)
        key_material_status = {
            "mode": "validated",
            "validated_key_ids": list(validated),
        }
    return {
        "report_format": report_format,
        "operation": "inventory",
        "status": "completed",
        "backup_dir": str(loaded.package_dir),
        "source": manifest["source"],
        "created_at": manifest.get("created_at"),
        "database": {
            "format": database.get("format"),
            "database_revisions": database.get("database_revisions"),
            "repository_heads": database.get("repository_heads"),
        },
        "object_count": len(objects),
        "retention_labels": manifest["retention_labels"],
        "encrypted_app_config_keys": inventory.get("encrypted_app_config_keys"),
        "key_material_ids": sorted(key_material),
        "key_material_status": key_material_status,
        "queue_reconciliation": manifest["queue_reconciliation"],
        "manifest_encrypted": loaded.envelope.get("encrypted") is True,
        "manifest_signed": bool(loaded.envelope.get("signature_artifact")),
        "generated_at": _utcnow(),
    }


def run_reconcile(request: RestoreRequest) -> dict[str, object]:
    """Validate object references and rebuild the target ephemeral queue only."""

    loaded = load_backup(
        request.backup_dir,
        request.transforms,
        require_protected_manifest=request.target_environment == "production",
    )
    _validate_target_guard(loaded.manifest, request)
    validated_keys = _validate_key_prerequisites(loaded.manifest, request.key_material)
    reconcilers = _manifest_reconcilers(loaded.manifest, request.queue_reconcilers)
    target_client = _client_for(request.target_object_store)
    reference_report = reconcile_object_references(
        request.target_database_url,
        target_client,
        request.target_object_store.bucket,
    )
    queue_report = asyncio.run(
        _reset_redis_and_reconcile(
            request.target_redis_url,
            reconcilers,
            dry_run=request.dry_run,
            target_database_url=request.target_database_url,
            target_object_store=request.target_object_store,
            repo_root=request.repo_root,
        )
    )
    return {
        "report_format": "cygnus-reconcile-report/v1",
        "operation": "reconcile",
        "status": "dry_run" if request.dry_run else "completed",
        "target": {
            "environment": request.target_environment,
            "identity": request.target_id,
        },
        "validated_key_ids": validated_keys,
        "object_reconciliation": reference_report,
        "queue_reconciliation": queue_report,
        "generated_at": _utcnow(),
    }


def _parse_boolean(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise BackupRestoreError(
        "boolean_environment_invalid",
        "boolean environment value is invalid",
    )


def _source_storage_from_args(args: argparse.Namespace) -> ObjectStoreTarget:
    from cygnus.runtime.config import get_settings

    settings = get_settings()
    return ObjectStoreTarget(
        endpoint=args.minio_endpoint
        or os.environ.get("CYGNUS_BACKUP_MINIO_ENDPOINT")
        or settings.minio_endpoint,
        access_key=args.minio_access_key
        or os.environ.get("CYGNUS_BACKUP_MINIO_ACCESS_KEY")
        or settings.minio_access_key,
        secret_key=args.minio_secret_key
        or os.environ.get("CYGNUS_BACKUP_MINIO_SECRET_KEY")
        or settings.minio_secret_key,
        bucket=args.minio_bucket
        or os.environ.get("CYGNUS_BACKUP_MINIO_BUCKET")
        or settings.minio_bucket,
        secure=(
            args.minio_secure
            if args.minio_secure is not None
            else _parse_boolean(
                os.environ.get("CYGNUS_BACKUP_MINIO_SECURE"),
                default=settings.minio_secure,
            )
        ),
    )


def _target_storage_from_args(args: argparse.Namespace) -> ObjectStoreTarget:
    fields = {
        "endpoint": args.target_minio_endpoint
        or os.environ.get("CYGNUS_RESTORE_MINIO_ENDPOINT"),
        "access_key": args.target_minio_access_key
        or os.environ.get("CYGNUS_RESTORE_MINIO_ACCESS_KEY"),
        "secret_key": args.target_minio_secret_key
        or os.environ.get("CYGNUS_RESTORE_MINIO_SECRET_KEY"),
        "bucket": args.target_minio_bucket
        or os.environ.get("CYGNUS_RESTORE_MINIO_BUCKET"),
    }
    missing = [name for name, value in fields.items() if not value]
    if missing:
        raise BackupRestoreError(
            "restore_target_storage_missing",
            "target MinIO configuration must be supplied explicitly",
            details={"missing": missing},
        )
    return ObjectStoreTarget(
        endpoint=str(fields["endpoint"]),
        access_key=str(fields["access_key"]),
        secret_key=str(fields["secret_key"]),
        bucket=str(fields["bucket"]),
        secure=(
            args.target_minio_secure
            if args.target_minio_secure is not None
            else _parse_boolean(
                os.environ.get("CYGNUS_RESTORE_MINIO_SECURE"), default=False
            )
        ),
    )


def _load_key_material_file(path_value: str) -> dict[str, str]:
    path = Path(path_value).expanduser().resolve()
    loaded = _read_json(path, label="target key material file")
    values: dict[str, str] = {}
    invalid: list[str] = []
    for key, value in loaded.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            invalid.append(str(key))
        else:
            values[key] = value
    if invalid:
        raise BackupRestoreError(
            "key_material_file_invalid",
            "target key material file must map key IDs to non-empty strings",
            details={"invalid_key_ids": invalid},
        )
    return values


def _transforms_from_args(args: argparse.Namespace) -> TransformCommands:
    return TransformCommands(
        artifact_encrypt=getattr(args, "artifact_encrypt_command", None),
        artifact_decrypt=getattr(args, "artifact_decrypt_command", None),
        manifest_encrypt=getattr(args, "manifest_encrypt_command", None),
        manifest_decrypt=getattr(args, "manifest_decrypt_command", None),
        manifest_sign=getattr(args, "manifest_sign_command", None),
        manifest_verify=getattr(args, "manifest_verify_command", None),
    )


def _restore_request_from_args(args: argparse.Namespace) -> RestoreRequest:
    target_database_url = args.target_database_url or os.environ.get(
        "CYGNUS_RESTORE_DATABASE_URL"
    )
    target_redis_url = args.target_redis_url or os.environ.get(
        "CYGNUS_RESTORE_REDIS_URL"
    )
    missing = [
        label
        for label, value in (
            ("target_database_url", target_database_url),
            ("target_redis_url", target_redis_url),
        )
        if not value
    ]
    if missing:
        raise BackupRestoreError(
            "restore_target_configuration_missing",
            "target database and Redis URLs must be supplied explicitly",
            details={"missing": missing},
        )
    return RestoreRequest(
        backup_dir=Path(args.backup_dir),
        target_database_url=str(target_database_url),
        target_object_store=_target_storage_from_args(args),
        target_redis_url=str(target_redis_url),
        target_environment=args.target_environment,
        target_id=args.target_id,
        confirm_target=args.confirm_target,
        allow_production_restore=bool(args.allow_production_restore),
        key_material=_load_key_material_file(args.key_material_file),
        transforms=_transforms_from_args(args),
        queue_reconcilers=(
            tuple(args.queue_reconciler) if args.queue_reconciler else None
        ),
        dry_run=bool(args.dry_run),
    )


def _add_transform_arguments(parser: argparse.ArgumentParser, *, backup: bool) -> None:
    if backup:
        parser.add_argument(
            "--artifact-encrypt-command",
            help="argv template with {input} and {output}; encrypts each dump/object artifact",
        )
        parser.add_argument(
            "--manifest-encrypt-command",
            help="argv template with {input} and {output}; encrypts the completed manifest",
        )
        parser.add_argument(
            "--manifest-sign-command",
            help="argv template with {input} and {signature}; signs the manifest artifact",
        )
    parser.add_argument(
        "--artifact-decrypt-command",
        help="argv template with {input} and {output}; required for encrypted backup artifacts",
    )
    parser.add_argument(
        "--manifest-decrypt-command",
        help="argv template with {input} and {output}; required for encrypted manifest",
    )
    parser.add_argument(
        "--manifest-verify-command",
        help="argv template with {input} and {signature}; required for a signed manifest",
    )


def _add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-database-url")
    parser.add_argument("--target-redis-url")
    parser.add_argument("--target-minio-endpoint")
    parser.add_argument("--target-minio-access-key")
    parser.add_argument("--target-minio-secret-key")
    parser.add_argument("--target-minio-bucket")
    parser.add_argument(
        "--target-minio-secure",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--target-environment", choices=("isolated", "production"), required=True
    )
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--confirm-target", required=True)
    parser.add_argument("--allow-production-restore", action="store_true")
    parser.add_argument(
        "--key-material-file",
        required=True,
        help="local JSON key-ID mapping; it is validated but never copied into the backup",
    )
    parser.add_argument(
        "--queue-reconciler",
        action="append",
        help="optional module:function override for a recorded durable outbox reconciler",
    )
    parser.add_argument("--dry-run", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="operation", required=True)

    backup = subcommands.add_parser(
        "backup", help="create an atomic coordinated backup package"
    )
    backup.add_argument("--output-dir", required=True)
    backup.add_argument("--database-url")
    backup.add_argument("--minio-endpoint")
    backup.add_argument("--minio-access-key")
    backup.add_argument("--minio-secret-key")
    backup.add_argument("--minio-bucket")
    backup.add_argument(
        "--minio-secure", action=argparse.BooleanOptionalAction, default=None
    )
    backup.add_argument(
        "--environment", choices=("development", "staging", "production"), required=True
    )
    backup.add_argument("--source-id", required=True)
    backup.add_argument("--git-commit", help="full checked-out Git commit")
    backup.add_argument(
        "--backend-image-ref", help="immutable backend image @sha256 ref"
    )
    backup.add_argument(
        "--frontend-image-ref", help="immutable frontend image @sha256 ref"
    )
    backup.add_argument("--alembic-head", help="exact deployed Alembic head")
    backup.add_argument("--quiesce-command", required=True)
    backup.add_argument("--resume-command", required=True)
    backup.add_argument("--retention-label", action="append", default=[])
    backup.add_argument("--queue-reconciler", action="append")
    backup.add_argument("--dry-run", action="store_true")
    _add_transform_arguments(backup, backup=True)

    restore = subcommands.add_parser(
        "restore", help="destructively restore into an empty isolated target"
    )
    restore.add_argument("--backup-dir", required=True)
    _add_target_arguments(restore)
    _add_transform_arguments(restore, backup=False)

    inventory = subcommands.add_parser(
        "inventory", help="validate and report backup contents"
    )
    inventory.add_argument("--backup-dir", required=True)
    inventory.add_argument(
        "--key-material-file",
        help="optional local JSON key-ID mapping; fingerprints are validated against the manifest",
    )
    _add_transform_arguments(inventory, backup=False)

    reconcile = subcommands.add_parser(
        "reconcile", help="validate object references and replay durable outboxes"
    )
    reconcile.add_argument("--backup-dir", required=True)
    _add_target_arguments(reconcile)
    _add_transform_arguments(reconcile, backup=False)

    drill = subcommands.add_parser(
        "drill",
        help="restore into a disposable isolated target and emit a PASS/FAIL drill report with measured RPO/RTO",
    )
    drill.add_argument("--backup-dir", required=True)
    drill.add_argument(
        "--rpo-max-seconds",
        type=float,
        help="optional RPO objective; the drill fails if the measured value exceeds it",
    )
    drill.add_argument(
        "--require-recovery-objectives",
        action="store_true",
        help=(
            "require explicit approved --rpo-max-seconds and --rto-max-seconds "
            "before this drill can run as release evidence"
        ),
    )
    drill.add_argument(
        "--rto-max-seconds",
        type=float,
        help="optional RTO objective; the drill fails if the measured value exceeds it",
    )
    drill.add_argument("--rpo-objective-ref", help="approved RPO objective reference")
    drill.add_argument("--rto-objective-ref", help="approved RTO objective reference")
    drill.add_argument(
        "--expected-git-commit",
        help="full release Git commit expected by the certifier",
    )
    drill.add_argument(
        "--expected-backend-image-ref",
        help="immutable backend image expected by the certifier",
    )
    drill.add_argument(
        "--expected-frontend-image-ref",
        help="immutable frontend image expected by the certifier",
    )
    drill.add_argument(
        "--expected-alembic-head", help="exact Alembic head expected by the certifier"
    )
    _add_target_arguments(drill)
    _add_transform_arguments(drill, backup=False)

    for command in (backup, restore, inventory, reconcile, drill):
        command.add_argument("--report-file")
    return parser


def _write_report(path_value: str | None, report: Mapping[str, object]) -> None:
    if path_value:
        _write_json_atomic(Path(path_value).expanduser().resolve(), report)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.operation == "backup":
            from cygnus.runtime.config import get_settings

            settings = get_settings()
            request = BackupRequest(
                output_dir=Path(args.output_dir),
                database_url=args.database_url
                or os.environ.get("CYGNUS_BACKUP_DATABASE_URL")
                or settings.database_url,
                object_store=_source_storage_from_args(args),
                environment=args.environment,
                source_id=args.source_id,
                quiesce_command=args.quiesce_command,
                resume_command=args.resume_command,
                retention_labels=tuple(args.retention_label)
                or (DEFAULT_RETENTION_LABEL,),
                transforms=_transforms_from_args(args),
                queue_reconcilers=tuple(
                    args.queue_reconciler or DEFAULT_QUEUE_RECONCILERS
                ),
                dry_run=bool(args.dry_run),
                release_identity=_release_identity_from_cli(
                    args,
                    option_prefix="",
                    environment_prefix="CYGNUS_RELEASE_",
                ),
            )
            report = run_backup(request)
        elif args.operation == "restore":
            report = run_restore(_restore_request_from_args(args))
        elif args.operation == "inventory":
            report = run_inventory(
                Path(args.backup_dir),
                _transforms_from_args(args),
                key_material_file=args.key_material_file,
            )
        elif args.operation == "reconcile":
            report = run_reconcile(_restore_request_from_args(args))
        elif args.operation == "drill":
            report = run_drill(
                _restore_request_from_args(args),
                rpo_max_seconds=args.rpo_max_seconds,
                rto_max_seconds=args.rto_max_seconds,
                rpo_objective_ref=args.rpo_objective_ref,
                rto_objective_ref=args.rto_objective_ref,
                expected_release_identity=_release_identity_from_cli(
                    args,
                    option_prefix="expected_",
                    environment_prefix="CYGNUS_EXPECTED_RELEASE_",
                ),
                require_recovery_objectives=bool(args.require_recovery_objectives),
            )
        else:  # argparse makes this unreachable; keep a machine-readable failure.
            raise BackupRestoreError("operation_invalid", "unknown backup operation")
    except BackupRestoreError as exc:
        report = {
            "report_format": (
                DRILL_REPORT_FORMAT
                if args.operation == "drill"
                else "cygnus-backup-report/v1"
            ),
            "operation": args.operation,
            "status": "failed",
            "error": exc.as_report(),
            "generated_at": _utcnow(),
        }
        status = 1
    except BaseException as exc:
        report = {
            "report_format": "cygnus-backup-report/v1",
            "operation": args.operation,
            "status": "failed",
            "error": {
                "code": "unexpected_error",
                "message": "backup operation failed unexpectedly",
                "details": {"error_type": type(exc).__name__},
            },
            "generated_at": _utcnow(),
        }
        status = 1
    else:
        status = 0 if report.get("status") != "failed" else 1
    try:
        _write_report(args.report_file, report)
    except BackupRestoreError as report_error:
        print(json.dumps(report, sort_keys=True), file=sys.stdout)
        print(json.dumps(report_error.as_report(), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True), file=sys.stdout)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
