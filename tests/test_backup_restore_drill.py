"""Focused tests for the CYG-132 coordinated backup/restore/drill contract.

Unit tests exercise the fail-closed package validation, target guards, key
material fingerprint preconditions, RPO/RTO measurement schema, and the generic
FK orphan scan without any live service. The integration test performs a real
backup -> drill round trip against the local PostgreSQL/MinIO/Redis stack and is
skipped unless ``CYGNUS_BACKUP_RESTORE_TEST_DATABASE_URL`` is configured, in
line with the repository's other Postgres-backed suites.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from typing import cast
from unittest.mock import patch

from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType, governed_object_ref
from cygnus.evidence.records import FreshnessState
from cygnus.governance.audience_bindings import (
    AudienceBindingCreate,
    create_audience_binding,
)
from cygnus.governance.signals import GovernanceSignalInput, create_governance_signal
from cygnus.publish import (
    DurablePublishCommand,
    acknowledge_propagation_delivery,
    apply_durable_publish,
    durable_publish_command_for_signal,
)
from cygnus.publish.delivery import canonical_json, sign_body
from cygnus.review.contributions import approve_wiki_draft, create_wiki_draft
from cygnus.review.intake import PressureSignalType
from cygnus.runtime.backup_restore import (
    BACKUP_FORMAT,
    COMPLETE_FILE,
    DEFAULT_QUEUE_RECONCILERS,
    DRILL_REPORT_FORMAT,
    LEDGER_TABLE,
    MANIFEST_ENVELOPE_FILE,
    OUTBOX_NONTERMINAL_STATUSES,
    OUTBOX_TABLE,
    BackupRequest,
    BackupRestoreError,
    ObjectStoreTarget,
    RestoreRequest,
    RpoEvidence,
    TransformCommands,
    VerificationEvidence,
    _drill_checks,
    _fk_orphan_query,
    _measured_rpo_from_manifest,
    _redis_env_from_url,
    _validate_key_prerequisites,
    load_backup,
    main,
    run_backup,
    run_drill,
    run_inventory,
)
from cygnus.runtime.database.models import (
    AppConfig,
    GovernanceLedgerEvent,
    AuditLog,
    Employee,
    GovernanceAudienceBinding,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
    GovernanceSignal,
    WikiDraftAiPreReviewDispatch,
    Source,
    WikiPage,
    SourceDispatchExecution,
    WikiPageDraft,
)
from cygnus.runtime.services.config_service import _derive_fernet_key
from cygnus.runtime.services.audit_service import log_audit
from cygnus.runtime.source_dispatch import record_source_dispatch

_REPO_ROOT = Path(__file__).resolve().parents[1]

_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_BACKUP_RESTORE_TEST_DATABASE_URL")
_INTEGRATION_MINIO_ENDPOINT = os.getenv(
    "CYGNUS_BACKUP_RESTORE_TEST_MINIO_ENDPOINT", "localhost:9000"
)
_INTEGRATION_MINIO_ACCESS_KEY = os.getenv(
    "CYGNUS_BACKUP_RESTORE_TEST_MINIO_ACCESS_KEY", "minioadmin"
)
_INTEGRATION_MINIO_SECRET_KEY = os.getenv(
    "CYGNUS_BACKUP_RESTORE_TEST_MINIO_SECRET_KEY", "minioadmin123"
)
_INTEGRATION_REDIS_URL = os.getenv(
    "CYGNUS_BACKUP_RESTORE_TEST_REDIS_URL", "redis://localhost:6379/14"
)

_DRILL_DELIVERY_SECRET = "cyg132-drill-delivery-hmac-secret"
_UNIT_SECRET = "unit-secret-key"
_UNIT_PEPPER = "unit-mcp-pepper"


def _digest(data: bytes) -> tuple[str, int]:
    return hashlib.sha256(data).hexdigest(), len(data)


def _publish_command_from_envelope(
    envelope: dict[str, object], *, command_id: str
) -> DurablePublishCommand:
    target_channels = envelope.get("target_channels")
    if not isinstance(target_channels, list) or not all(
        isinstance(channel, str) for channel in target_channels
    ):
        raise AssertionError("durable publish envelope has invalid target channels")
    expected_version = cast(int, envelope["expected_version"])
    return DurablePublishCommand(
        draft_id=uuid.UUID(str(envelope["draft_id"])),
        approval_ref=uuid.UUID(str(envelope["approval_ref"])),
        approval_digest=str(envelope["approval_digest"]),
        scope_digest=str(envelope["scope_digest"]),
        signal_id=uuid.UUID(str(envelope["signal_id"])),
        signal_freshness=str(envelope["signal_freshness"]),
        command_id=command_id,
        action_key=str(envelope["action_key"]),
        target_channels=tuple(target_channels),
        expected_version=int(expected_version),
        reason=str(envelope["reason"]),
    )


def _write_backup_package(
    root: Path,
    *,
    artifact_bytes: bytes = b"db payload",
    manifest_overrides: dict[str, object] | None = None,
) -> Path:
    """Write a structurally valid, unencrypted coordinated backup package."""
    package = root / "backup"
    package.mkdir(parents=True)
    artifact = package / "database.dump"
    artifact.write_bytes(artifact_bytes)
    payload_sha, payload_bytes = _digest(artifact_bytes)
    stored_sha, stored_bytes = _digest(artifact_bytes)
    manifest: dict[str, object] = {
        "format_version": BACKUP_FORMAT,
        "created_at": "2026-08-12T00:00:00+00:00",
        "source": {"environment": "development", "identity": "unit-src"},
        "consistency_boundary": {
            "mode": "operator_quiesce_commands",
            "writes_stopped_before_snapshot": True,
            "resume_runs_only_after_artifacts_and_manifest_are_complete": True,
            "quiesce_completed_at": "2026-08-12T00:00:00+00:00",
            "dump_started_at": "2026-08-12T00:00:00.500000+00:00",
            "dump_completed_at": "2026-08-12T00:00:01+00:00",
            "measured_rpo_upper_bound_seconds": 0.5,
            "dump_duration_seconds": 0.5,
        },
        "database": {
            "format": "postgres_custom",
            "artifact": {
                "path": "database.dump",
                "sha256": stored_sha,
                "bytes": stored_bytes,
                "payload_sha256": payload_sha,
                "payload_bytes": payload_bytes,
                "encrypted": False,
            },
            "database_revisions": ["abc123"],
            "repository_heads": ["abc123"],
        },
        "objects": [],
        "configuration_inventory": {
            "runtime_setting_names": [],
            "encrypted_app_config_keys": ["llm_api_key"],
            "plaintext_key_material_archived": False,
        },
        "key_material": {
            "runtime.secret_key": {
                "algorithm": "sha256",
                "fingerprint": hashlib.sha256(_UNIT_SECRET.encode()).hexdigest(),
            },
            "runtime.mcp_token_pepper": {
                "algorithm": "sha256",
                "fingerprint": hashlib.sha256(_UNIT_PEPPER.encode()).hexdigest(),
            },
        },
        "queue_reconciliation": {
            "redis_persistence": "ephemeral",
            "restore_action": "flush_target_redis_db_then_replay_durable_outboxes",
            "durable_truth": "postgresql_outbox_rows",
            "reconcilers": [DEFAULT_QUEUE_RECONCILERS[0]],
        },
        "retention_labels": ["unit"],
        "verification": {
            "table_row_counts": {
                "sources": 1,
                "wiki_page_drafts": 1,
                "governance_ledger_events": 1,
                "wiki_draft_ai_pre_review_dispatches": 1,
            },
            "fk_constraint_count": 1,
            "measured_at": "2026-08-12T00:00:01+00:00",
        },
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    manifest_path = package / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    manifest_sha, manifest_bytes = _digest(manifest_path.read_bytes())
    envelope_path = package / MANIFEST_ENVELOPE_FILE
    envelope_path.write_text(
        json.dumps(
            {
                "format_version": BACKUP_FORMAT,
                "manifest_artifact": "manifest.json",
                "manifest_sha256": manifest_sha,
                "manifest_bytes": manifest_bytes,
                "encrypted": False,
                "signature_artifact": None,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    envelope_sha, _ = _digest(envelope_path.read_bytes())
    (package / COMPLETE_FILE).write_text(
        json.dumps(
            {
                "format_version": BACKUP_FORMAT,
                "manifest_envelope_sha256": envelope_sha,
                "completed_at": "2026-08-12T00:00:01+00:00",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return package


def _fixture_manifest() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
        package = _write_backup_package(Path(temporary))
        return json.loads((package / "manifest.json").read_text(encoding="utf-8"))


def _restore_request(
    backup_dir: Path,
    *,
    target_id: str = "unit-dst",
    confirm_target: str | None = None,
    target_environment: str = "isolated",
    allow_production_restore: bool = False,
) -> RestoreRequest:
    return RestoreRequest(
        backup_dir=backup_dir,
        target_database_url="postgresql+asyncpg://unit@localhost:5432/unit",
        target_object_store=ObjectStoreTarget(
            endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin123",
            bucket="unit-dst",
            secure=False,
        ),
        target_redis_url="redis://localhost:6379/0",
        target_environment=target_environment,
        target_id=target_id,
        confirm_target=confirm_target if confirm_target is not None else target_id,
        allow_production_restore=allow_production_restore,
        key_material={
            "runtime.secret_key": _UNIT_SECRET,
            "runtime.mcp_token_pepper": _UNIT_PEPPER,
        },
        transforms=TransformCommands(),
        queue_reconcilers=None,
        dry_run=False,
        repo_root=_REPO_ROOT,
    )


class BackupPackageValidationTests(unittest.TestCase):
    """Fail-closed package loading: missing/corrupt markers and artifacts."""

    def test_missing_completion_marker_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            (package / COMPLETE_FILE).unlink()
            with self.assertRaises(BackupRestoreError) as raised:
                load_backup(package, TransformCommands())
            self.assertEqual(raised.exception.code, "required_backup_file_missing")

    def test_completion_marker_checksum_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            complete = json.loads((package / COMPLETE_FILE).read_text(encoding="utf-8"))
            complete["manifest_envelope_sha256"] = "0" * 64
            (package / COMPLETE_FILE).write_text(
                json.dumps(complete, sort_keys=True), encoding="utf-8"
            )
            with self.assertRaises(BackupRestoreError) as raised:
                load_backup(package, TransformCommands())
            self.assertEqual(
                raised.exception.code, "completion_marker_checksum_mismatch"
            )

    def test_manifest_checksum_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            manifest_path = package / "manifest.json"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8") + " ",
                encoding="utf-8",
            )
            with self.assertRaises(BackupRestoreError) as raised:
                load_backup(package, TransformCommands())
            self.assertEqual(raised.exception.code, "manifest_checksum_mismatch")

    def test_path_traversal_in_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(
                Path(temporary),
                manifest_overrides={
                    "database": {
                        "format": "postgres_custom",
                        "artifact": {
                            "path": "../escape.dump",
                            "sha256": "0" * 64,
                            "bytes": 0,
                            "payload_sha256": "0" * 64,
                            "payload_bytes": 0,
                            "encrypted": False,
                        },
                        "database_revisions": ["abc123"],
                        "repository_heads": ["abc123"],
                    }
                },
            )
            with self.assertRaises(BackupRestoreError) as raised:
                load_backup(package, TransformCommands())
            self.assertEqual(raised.exception.code, "backup_artifact_validation_failed")
            issues = raised.exception.details.get("issues")
            self.assertIsInstance(issues, list)
            self.assertTrue(
                any(
                    issue.get("reason") == "unsafe_archive_path"
                    for issue in cast(list[dict[str, object]], issues)
                )
            )

    def test_tampered_artifact_with_resigned_manifest_blocks_inventory(self) -> None:
        """A tampered artifact that also re-signs the manifest still fails."""
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(
                Path(temporary), artifact_bytes=b"original payload"
            )
            # Tamper the artifact and fully re-sign manifest + envelope so the
            # envelope checks pass; only the plaintext payload checksum differs.
            tampered = b"attacker replaced this file"
            (package / "database.dump").write_bytes(tampered)
            tampered_sha, tampered_bytes = _digest(tampered)
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact = manifest["database"]["artifact"]
            artifact["sha256"] = tampered_sha
            artifact["bytes"] = tampered_bytes
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True), encoding="utf-8"
            )
            manifest_sha, manifest_bytes = _digest(manifest_path.read_bytes())
            envelope_path = package / MANIFEST_ENVELOPE_FILE
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            envelope["manifest_sha256"] = manifest_sha
            envelope["manifest_bytes"] = manifest_bytes
            envelope_path.write_text(
                json.dumps(envelope, sort_keys=True), encoding="utf-8"
            )
            envelope_sha, _ = _digest(envelope_path.read_bytes())
            complete = json.loads((package / COMPLETE_FILE).read_text(encoding="utf-8"))
            complete["manifest_envelope_sha256"] = envelope_sha
            (package / COMPLETE_FILE).write_text(
                json.dumps(complete, sort_keys=True), encoding="utf-8"
            )
            # Envelope-level validation passes; plaintext validation must fail.
            load_backup(package, TransformCommands())
            with self.assertRaises(BackupRestoreError) as raised:
                run_inventory(package, TransformCommands())
            self.assertEqual(
                raised.exception.code, "artifact_plaintext_checksum_mismatch"
            )

    def test_inventory_rejects_key_material_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            key_file = Path(temporary) / "keys.json"
            key_file.write_text(
                json.dumps(
                    {
                        "runtime.secret_key": "wrong-secret",
                        "runtime.mcp_token_pepper": _UNIT_PEPPER,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BackupRestoreError) as raised:
                run_inventory(
                    package, TransformCommands(), key_material_file=str(key_file)
                )
            self.assertEqual(raised.exception.code, "key_material_precondition_failed")


class KeyMaterialTests(unittest.TestCase):
    def test_key_fingerprint_mismatch_blocks_restore(self) -> None:
        manifest = _fixture_manifest()
        with self.assertRaises(BackupRestoreError) as raised:
            _validate_key_prerequisites(
                manifest,
                {
                    "runtime.secret_key": "wrong-secret",
                    "runtime.mcp_token_pepper": _UNIT_PEPPER,
                },
            )
        self.assertEqual(raised.exception.code, "key_material_precondition_failed")

    def test_missing_key_material_blocks_restore(self) -> None:
        manifest = _fixture_manifest()
        with self.assertRaises(BackupRestoreError) as raised:
            _validate_key_prerequisites(
                manifest,
                {"runtime.secret_key": _UNIT_SECRET},
            )
        self.assertEqual(raised.exception.code, "key_material_precondition_failed")


class TargetGuardTests(unittest.TestCase):
    def test_confirm_target_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            from cygnus.runtime.backup_restore import _validate_target_guard

            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8")
            )
            request = _restore_request(package, confirm_target="someone-else")
            with self.assertRaises(BackupRestoreError) as raised:
                _validate_target_guard(manifest, request)
            self.assertEqual(
                raised.exception.code, "restore_target_confirmation_mismatch"
            )

    def test_restore_target_matching_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            from cygnus.runtime.backup_restore import _validate_target_guard

            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8")
            )
            request = _restore_request(package, target_id="unit-src")
            with self.assertRaises(BackupRestoreError) as raised:
                _validate_target_guard(manifest, request)
            self.assertEqual(raised.exception.code, "restore_target_matches_source")

    def test_production_restore_requires_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            from cygnus.runtime.backup_restore import _validate_target_guard

            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8")
            )
            request = _restore_request(
                package,
                target_id="prod-dst",
                target_environment="production",
                allow_production_restore=False,
            )
            with self.assertRaises(BackupRestoreError) as raised:
                _validate_target_guard(manifest, request)
            self.assertEqual(raised.exception.code, "production_restore_guard_required")

    def test_drill_refuses_non_isolated_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            request = _restore_request(
                package,
                target_id="prod-dst",
                target_environment="production",
                allow_production_restore=True,
            )
            with self.assertRaises(BackupRestoreError) as raised:
                run_drill(request)
            self.assertEqual(raised.exception.code, "drill_target_must_be_isolated")


class BackupCommandGuardTests(unittest.TestCase):
    def _stub_repository_revisions(self) -> None:
        """The alembic graph is in-flight swarm work; these tests cover guards."""
        patcher = patch(
            "cygnus.runtime.backup_restore._repository_revisions",
            return_value=(("head-rev",), None),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_backup_destination_exists_is_refused(self) -> None:
        self._stub_repository_revisions()
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            existing = Path(temporary) / "backup"
            existing.mkdir()
            request = BackupRequest(
                output_dir=existing,
                database_url="postgresql+asyncpg://unit@localhost:5432/unit",
                object_store=ObjectStoreTarget(
                    endpoint="localhost:9000",
                    access_key="minioadmin",
                    secret_key="minioadmin123",
                    bucket="unit",
                    secure=False,
                ),
                environment="development",
                source_id="unit-src",
                quiesce_command="true",
                resume_command="true",
                retention_labels=("unit",),
                transforms=TransformCommands(),
                queue_reconcilers=DEFAULT_QUEUE_RECONCILERS,
                repo_root=_REPO_ROOT,
            )
            with self.assertRaises(BackupRestoreError) as raised:
                run_backup(request)
            self.assertEqual(raised.exception.code, "backup_destination_exists")

    def test_quiesce_command_failure_is_fail_closed(self) -> None:
        self._stub_repository_revisions()
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            request = BackupRequest(
                output_dir=Path(temporary) / "backup",
                database_url="postgresql+asyncpg://unit@localhost:5432/unit",
                object_store=ObjectStoreTarget(
                    endpoint="localhost:9000",
                    access_key="minioadmin",
                    secret_key="minioadmin123",
                    bucket="unit",
                    secure=False,
                ),
                environment="development",
                source_id="unit-src",
                quiesce_command="false",
                resume_command="true",
                retention_labels=("unit",),
                transforms=TransformCommands(),
                queue_reconcilers=DEFAULT_QUEUE_RECONCILERS,
                repo_root=_REPO_ROOT,
            )
            with self.assertRaises(BackupRestoreError) as raised:
                run_backup(request)
            self.assertEqual(raised.exception.code, "external_command_failed")
            self.assertFalse((Path(temporary) / "backup").exists())

    def test_backup_requires_quiesce_and_resume_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            request = BackupRequest(
                output_dir=Path(temporary) / "backup",
                database_url="postgresql+asyncpg://unit@localhost:5432/unit",
                object_store=ObjectStoreTarget(
                    endpoint="localhost:9000",
                    access_key="minioadmin",
                    secret_key="minioadmin123",
                    bucket="unit",
                    secure=False,
                ),
                environment="development",
                source_id="unit-src",
                quiesce_command="",
                resume_command="true",
                retention_labels=("unit",),
                transforms=TransformCommands(),
                queue_reconcilers=DEFAULT_QUEUE_RECONCILERS,
                repo_root=_REPO_ROOT,
            )
            with self.assertRaises(BackupRestoreError) as raised:
                run_backup(request)
            self.assertEqual(raised.exception.code, "quiesce_boundary_required")


class DrillMeasurementTests(unittest.TestCase):
    def test_rpo_measured_from_backup_boundary(self) -> None:
        manifest = _fixture_manifest()
        rpo = _measured_rpo_from_manifest(manifest)
        self.assertTrue(rpo["measured"])
        self.assertEqual(rpo["seconds"], 0.5)
        self.assertEqual(rpo["basis"], "quiesce_completed_to_dump_started")

    def test_rpo_never_claimed_when_unmeasured(self) -> None:
        manifest = _fixture_manifest()
        del manifest["consistency_boundary"]
        rpo = _measured_rpo_from_manifest(manifest)
        self.assertFalse(rpo["measured"])
        self.assertIsNone(rpo["seconds"])

    def test_rpo_never_claimed_when_timestamps_invalid(self) -> None:
        manifest = _fixture_manifest()
        boundary = manifest["consistency_boundary"]
        assert isinstance(boundary, dict)
        boundary["dump_started_at"] = "not-a-timestamp"
        rpo = _measured_rpo_from_manifest(manifest)
        self.assertFalse(rpo["measured"])
        self.assertIsNone(rpo["seconds"])

    def test_drill_checks_never_fail_on_unmeasured_rpo_without_objective(self) -> None:
        verification: VerificationEvidence = {
            "table_row_counts": {
                "baseline_tables": 2,
                "checked": 2,
                "matched": 2,
                "mismatches": [],
                "measured": True,
            },
            "object_hashes": {"checked": 0, "matched": 0, "mismatches": []},
            "foreign_keys": {"constraints_checked": 0, "orphan_rows": 0, "orphans": []},
            "idempotency_receipts": {
                "ledger_table": LEDGER_TABLE,
                "ledger_event_duplicate_idempotency_keys": [],
                "ledger_event_count": {
                    "expected": 1,
                    "actual": 1,
                    "matched": True,
                    "measured": True,
                },
                "outbox_table": OUTBOX_TABLE,
                "outbox_job_id_duplicates": [],
                "outbox_row_count": {
                    "expected": 1,
                    "actual": 1,
                    "matched": True,
                    "measured": True,
                },
            },
            "pending_jobs": {
                "nonterminal_outbox_rows_after_replay": 0,
                "checked_statuses": list(OUTBOX_NONTERMINAL_STATUSES),
            },
            "redis": {
                "dbsize": 1,
                "arq_key_count": 1,
                "expected_arq_job_ids": 1,
                "enqueued_outbox_without_arq_job": [],
            },
            "encrypted_config": {
                "checked": True,
                "sensitive_keys_checked": 1,
                "decrypt_ok": 1,
                "decrypt_failures": [],
            },
        }
        rpo: RpoEvidence = {"measured": False, "seconds": None}
        checks = _drill_checks(
            verification,
            rpo,
            rto_seconds=3.0,
            objectives={"rpo_max_seconds": None, "rto_max_seconds": None},
        )
        by_name = {cast(str, check["name"]): check for check in checks}
        self.assertTrue(by_name["rpo_objective"]["passed"])
        self.assertIn("not measured", cast(str, by_name["rpo_objective"]["detail"]))
        self.assertTrue(by_name["rto_objective"]["passed"])
        self.assertIn("3.0s", cast(str, by_name["rto_objective"]["detail"]))

    def test_drill_checks_fail_closed_when_objective_unprovable(self) -> None:
        verification: VerificationEvidence = {
            "table_row_counts": {
                "baseline_tables": 0,
                "checked": 0,
                "matched": 0,
                "mismatches": [],
                "measured": False,
            },
            "object_hashes": {"checked": 0, "matched": 0, "mismatches": []},
            "foreign_keys": {"constraints_checked": 0, "orphan_rows": 0, "orphans": []},
            "idempotency_receipts": {
                "ledger_table": LEDGER_TABLE,
                "ledger_event_duplicate_idempotency_keys": [],
                "ledger_event_count": {
                    "expected": None,
                    "actual": 0,
                    "matched": None,
                    "measured": False,
                },
                "outbox_table": OUTBOX_TABLE,
                "outbox_job_id_duplicates": [],
                "outbox_row_count": {
                    "expected": None,
                    "actual": 0,
                    "matched": None,
                    "measured": False,
                },
            },
            "pending_jobs": {
                "nonterminal_outbox_rows_after_replay": 0,
                "checked_statuses": list(OUTBOX_NONTERMINAL_STATUSES),
            },
            "redis": {
                "dbsize": 0,
                "arq_key_count": 0,
                "expected_arq_job_ids": 0,
                "enqueued_outbox_without_arq_job": [],
            },
            "encrypted_config": {
                "checked": False,
                "reason": "runtime.secret_key_not_supplied",
                "sensitive_keys_checked": 0,
                "decrypt_ok": 0,
                "decrypt_failures": [],
            },
        }
        rpo: RpoEvidence = {"measured": False, "seconds": None}
        checks = _drill_checks(
            verification,
            rpo,
            rto_seconds=30.0,
            objectives={"rpo_max_seconds": 5.0, "rto_max_seconds": 10.0},
        )
        by_name = {check["name"]: check for check in checks}
        self.assertFalse(by_name["rpo_objective"]["passed"])
        self.assertFalse(by_name["rto_objective"]["passed"])

    def test_explicit_release_drill_rejects_missing_objectives_before_restore(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(Path(temporary))
            with patch("cygnus.runtime.backup_restore.run_restore") as restore:
                with self.assertRaises(BackupRestoreError) as raised:
                    run_drill(
                        _restore_request(package),
                        require_recovery_objectives=True,
                    )
            self.assertEqual(
                raised.exception.code,
                "drill_recovery_objectives_required",
            )
            restore.assert_not_called()

    def test_production_source_cli_writes_failed_drill_report_without_restore(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            root = Path(temporary)
            package = _write_backup_package(
                root,
                manifest_overrides={
                    "source": {"environment": "production", "identity": "prod-01"}
                },
            )
            key_file = root / "keys.json"
            key_file.write_text(
                json.dumps(
                    {
                        "runtime.secret_key": _UNIT_SECRET,
                        "runtime.mcp_token_pepper": _UNIT_PEPPER,
                    }
                ),
                encoding="utf-8",
            )
            report_file = root / "drill-report.json"
            with patch("cygnus.runtime.backup_restore.run_restore") as restore:
                exit_code = main(
                    [
                        "drill",
                        "--backup-dir",
                        str(package),
                        "--target-database-url",
                        "postgresql+asyncpg://unit@localhost:5432/unit",
                        "--target-redis-url",
                        "redis://localhost:6379/0",
                        "--target-minio-endpoint",
                        "localhost:9000",
                        "--target-minio-access-key",
                        "minioadmin",
                        "--target-minio-secret-key",
                        "minioadmin123",
                        "--target-minio-bucket",
                        "unit-dst",
                        "--target-environment",
                        "isolated",
                        "--target-id",
                        "unit-dst",
                        "--confirm-target",
                        "unit-dst",
                        "--key-material-file",
                        str(key_file),
                        "--report-file",
                        str(report_file),
                    ]
                )
            self.assertEqual(exit_code, 1)
            restore.assert_not_called()
            report = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(report["report_format"], DRILL_REPORT_FORMAT)
            self.assertEqual(report["operation"], "drill")
            self.assertEqual(report["status"], "failed")
            error = cast(dict[str, object], report["error"])
            self.assertEqual(error["code"], "drill_recovery_objectives_required")
            details = cast(dict[str, object], error["details"])
            self.assertEqual(
                details["required_arguments"],
                [
                    "--rpo-max-seconds",
                    "--rto-max-seconds",
                    "--rpo-objective-ref",
                    "--rto-objective-ref",
                ],
            )

    def test_release_drill_rejects_missing_expected_identity_before_restore(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="cygnus-unit-") as temporary:
            package = _write_backup_package(
                Path(temporary),
                manifest_overrides={
                    "release_identity": {
                        "git_commit": "a" * 40,
                        "backend_image_ref": "registry.example/api@sha256:" + "b" * 64,
                        "frontend_image_ref": "registry.example/web@sha256:" + "c" * 64,
                        "alembic_head": "20260815_01",
                    }
                },
            )
            with patch("cygnus.runtime.backup_restore.run_restore") as restore:
                with self.assertRaises(BackupRestoreError) as raised:
                    run_drill(
                        _restore_request(package),
                        rpo_max_seconds=60,
                        rto_max_seconds=1800,
                        rpo_objective_ref="CYG-RPO-1",
                        rto_objective_ref="CYG-RTO-1",
                        require_recovery_objectives=True,
                    )
            self.assertEqual(raised.exception.code, "release_identity_required")
            restore.assert_not_called()


class ForeignKeyQueryTests(unittest.TestCase):
    def test_composite_fk_orphan_query(self) -> None:
        fk = {
            "constraint_name": "fk_draft_revision",
            "child_table": "wiki_page_drafts",
            "parent_table": "wiki_pages",
            "columns": [["page_id", "id"]],
        }
        query = _fk_orphan_query(fk)
        self.assertIn('FROM "wiki_page_drafts" AS c', query)
        self.assertIn('LEFT JOIN "wiki_pages" AS p ON p."id" = c."page_id"', query)
        self.assertIn('c."page_id" IS NOT NULL', query)
        self.assertIn('p."id" IS NULL', query)

    def test_composite_fk_pairs_all_columns(self) -> None:
        fk = {
            "constraint_name": "fk_composite",
            "child_table": "child_table",
            "parent_table": "parent_table",
            "columns": [["child_a", "parent_a"], ["child_b", "parent_b"]],
        }
        query = _fk_orphan_query(fk)
        self.assertIn('p."parent_a" = c."child_a"', query)
        self.assertIn('p."parent_b" = c."child_b"', query)
        self.assertIn('c."child_a" IS NOT NULL', query)
        self.assertIn('c."child_b" IS NOT NULL', query)
        self.assertIn('p."parent_a" IS NULL', query)
        self.assertIn('p."parent_b" IS NULL', query)

    def test_identifier_quoting(self) -> None:
        fk = {
            "constraint_name": "fk_odd",
            "child_table": 'select"me',
            "parent_table": "parent",
            "columns": [["from", "id"]],
        }
        query = _fk_orphan_query(fk)
        self.assertIn('"select""me"', query)
        self.assertIn('"from"', query)


class RedisEnvironmentTests(unittest.TestCase):
    def test_redis_url_parses_host_port_db_password(self) -> None:
        env = _redis_env_from_url("redis://:sekrit@redis.example:6380/3")
        self.assertEqual(
            env,
            {
                "REDIS_HOST": "redis.example",
                "REDIS_PORT": "6380",
                "REDIS_PASSWORD": "sekrit",
                "REDIS_DB": "3",
            },
        )

    def test_redis_url_defaults(self) -> None:
        env = _redis_env_from_url("redis://localhost:6379/0")
        self.assertEqual(env["REDIS_HOST"], "localhost")
        self.assertEqual(env["REDIS_PORT"], "6379")
        self.assertEqual(env["REDIS_DB"], "0")
        self.assertEqual(env["REDIS_PASSWORD"], "")

    def test_redis_url_rejects_bad_scheme_and_db(self) -> None:
        from cygnus.runtime.backup_restore import BackupRestoreError as BRE

        with self.assertRaises(BRE) as scheme_error:
            _redis_env_from_url("http://localhost:6379/0")
        self.assertEqual(scheme_error.exception.code, "restore_redis_url_invalid")
        with self.assertRaises(BRE) as db_error:
            _redis_env_from_url("redis://localhost:6379/not-a-db")
        self.assertEqual(db_error.exception.code, "restore_redis_url_invalid")


class ProductionRunbookTests(unittest.TestCase):
    def test_production_quiesce_and_resume_target_the_production_stack(self) -> None:
        expected_prefix = (
            "docker compose --project-directory ${CYGNUS_REPO} "
            "--project-name cygnus-prod "
            "-f ${CYGNUS_REPO}/deploy/docker-compose.prod.yml "
            "--env-file ${CYGNUS_REPO}/deploy/.env.prod "
            "--env-file ${CYGNUS_REPO}/deploy/releases/${CYGNUS_RELEASE}.env"
        )
        for relative_path in (
            "docs/en/backup-restore-runbook.md",
            "docs/zh/backup-restore-runbook.md",
        ):
            text = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
            production_section = text[text.index("### 4.2") : text.index("## 5.")]
            self.assertIn(
                f'--quiesce-command "{expected_prefix} stop api worker worker-skills"',
                production_section,
            )
            self.assertIn(
                f'--resume-command  "{expected_prefix} start api worker worker-skills"',
                production_section,
            )
            self.assertNotIn(
                '--quiesce-command "docker compose stop api worker worker-skills"',
                production_section,
            )
            self.assertNotIn(
                '--resume-command  "docker compose start api worker worker-skills"',
                production_section,
            )

    def test_restore_examples_use_a_dedicated_nonzero_redis_database(self) -> None:
        for relative_path in (
            "docs/en/backup-restore-runbook.md",
            "docs/zh/backup-restore-runbook.md",
        ):
            text = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(
                '--target-redis-url "redis://:CHANGE_ME@restore-host:6379/14" \\',
                text,
            )
            self.assertNotIn(
                '--target-redis-url "redis://:CHANGE_ME@restore-host:6379/0"',
                text,
            )


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_BACKUP_RESTORE_TEST_DATABASE_URL is not configured",
)
class BackupDrillRoundTripTests(unittest.TestCase):
    """Real backup -> drill recovery evidence against the local stack."""

    def test_backup_and_drill_roundtrip_proves_measured_recovery(self) -> None:
        import asyncio

        from minio import Minio

        base_async = _INTEGRATION_DATABASE_URL
        assert base_async is not None
        parsed = base_async.split("://", 1)
        base_sync = (
            f"postgresql://{parsed[1]}"
            if parsed[0].startswith("postgresql+")
            else base_async
        )
        suffix = uuid.uuid4().hex[:8]
        src_db = f"cygnus_bk_src_{suffix}"
        dst_db = f"cygnus_bk_dst_{suffix}"
        src_async = base_async.rsplit("/", 1)[0] + f"/{src_db}"
        dst_async = base_async.rsplit("/", 1)[0] + f"/{dst_db}"
        src_bucket = f"cygnus-bk-src-{suffix}"
        dst_bucket = f"cygnus-bk-dst-{suffix}"
        secret_key = f"integration-secret-{suffix}"
        pepper = f"integration-pepper-{suffix}"
        temporary = Path(tempfile.mkdtemp(prefix="cygnus-drill-"))
        client = Minio(
            _INTEGRATION_MINIO_ENDPOINT,
            access_key=_INTEGRATION_MINIO_ACCESS_KEY,
            secret_key=_INTEGRATION_MINIO_SECRET_KEY,
            secure=False,
        )
        engine = None
        try:
            for statement in (
                f'CREATE DATABASE "{src_db}"',
                f'CREATE DATABASE "{dst_db}"',
            ):
                subprocess.run(
                    [
                        "psql",
                        "--no-psqlrc",
                        "--quiet",
                        "--dbname",
                        base_sync,
                        "--command",
                        statement,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            migration_env = os.environ.copy()
            migration_env["database_url"] = src_async
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    "alembic.ini",
                    "upgrade",
                    "head",
                ],
                cwd=_REPO_ROOT,
                env=migration_env,
                check=True,
                capture_output=True,
                text=True,
            )
            if not client.bucket_exists(src_bucket):
                client.make_bucket(src_bucket)
            if not client.bucket_exists(dst_bucket):
                client.make_bucket(dst_bucket)
            client.put_object(
                src_bucket,
                "drill/sample.txt",
                __import__("io").BytesIO(b"drill payload"),
                length=13,
                content_type="text/plain",
                metadata={"x-amz-meta-drill": "yes"},
            )

            engine = create_async_engine(src_async)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def seed() -> dict[str, object]:
                async with sessions() as session:
                    actor = Employee(
                        id=uuid.uuid4(),
                        name="Backup drill administrator",
                        email=f"backup-drill-{suffix}@example.test",
                        role="admin",
                        global_role="admin",
                    )
                    source = Source(
                        title="Drill source",
                        full_text="Drill source content for governed recovery.",
                        source_type="file",
                        status="ready",
                        progress=100,
                        language="en",
                        minio_key="drill/sample.txt",
                        file_name="sample.txt",
                        file_size=13,
                        contributed_by_employee_id=actor.id,
                    )
                    session.add_all((actor, source))
                    await session.flush()
                    attested_at = source.updated_at or datetime.now(timezone.utc)
                    source.freshness_state = FreshnessState.FRESH.value
                    source.freshness_actor_id = actor.id
                    source.freshness_reason = "backup drill source attested"
                    source.freshness_attested_at = attested_at
                    source.freshness_expires_at = attested_at + timedelta(hours=1)
                    await session.flush()

                    source_dispatch, _, _ = await record_source_dispatch(
                        session,
                        source,
                        stage="ingest",
                        task_name="ingest_file_task",
                        task_args=(str(source.id),),
                        new_generation=True,
                    )
                    governed_draft = await create_wiki_draft(
                        session,
                        page_id=None,
                        author_id=actor.id,
                        content_md=(
                            "# Drill governed troubleshooting flow\n\n"
                            "- Reproduce the issue with the source evidence.\n"
                            "- Escalate only after the supported check fails."
                        ),
                        note="Durable backup drill governed source",
                        source_metadata={"source_ids": [str(source.id)]},
                        draft_kind="create",
                        suggested_metadata={
                            "slug": f"drill-governed-{suffix}",
                            "title": "Drill governed troubleshooting flow",
                            "summary": "A source-backed governed recovery fixture.",
                            "page_type": "concept",
                            "knowledge_type_slugs": ["troubleshooting_flow"],
                            "scope_type": "global",
                            "scope_id": None,
                            "language": "en",
                        },
                    )
                    page = await approve_wiki_draft(
                        session,
                        governed_draft,
                        reviewer_id=actor.id,
                        reviewer_note="Approved for durable recovery verification.",
                    )
                    object_ref = governed_object_ref(page.id)
                    audience = AudienceFilter(
                        visibility=Visibility.INTERNAL,
                        languages=("en",),
                    )
                    binding, binding_replayed = await create_audience_binding(
                        session,
                        command=AudienceBindingCreate(
                            page_id=page.id,
                            object_ref=object_ref,
                            variant_ref="drill-internal-governed",
                            channel="internal-copilot",
                            audience_filter=audience,
                        ),
                        actor_id=actor.id,
                    )
                    if binding_replayed:
                        raise AssertionError(
                            "new drill audience binding unexpectedly replayed"
                        )
                    signal = await create_governance_signal(
                        session,
                        GovernanceSignalInput(
                            signal_ref=f"drill-signal:{suffix}",
                            signal_type=PressureSignalType.HUMAN_REWRITE,
                            object_ref=object_ref,
                            title="Drill governed recovery signal",
                            object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
                            audience_filter=audience,
                            audience_binding_ref=binding.binding_key,
                            affected_surfaces=("internal-copilot",),
                            trigger_signals=("human_rewrite",),
                            freshness=FreshnessState.FRESH,
                            page_id=page.id,
                            source_id=source.id,
                            summary="A source-backed signal used only by this recovery drill.",
                            reason="Validate durable publication survives restore.",
                            evidence_excerpt="The source requires the governed troubleshooting flow.",
                        ),
                        created_by_id=actor.id,
                    )
                    envelope = await durable_publish_command_for_signal(
                        session,
                        signal=signal,
                    )
                    if envelope is None:
                        raise AssertionError(
                            "qualified drill signal did not produce publish command"
                        )
                    command = _publish_command_from_envelope(
                        envelope,
                        command_id=f"drill-publish:{suffix}",
                    )
                    publish_result = await apply_durable_publish(
                        session,
                        command=command,
                        actor_id=actor.id,
                    )
                    publication_id = uuid.UUID(
                        str(publish_result["publication_record_id"])
                    )
                    delivery = await session.scalar(
                        select(GovernancePropagationDelivery).where(
                            GovernancePropagationDelivery.publication_id
                            == publication_id
                        )
                    )
                    if delivery is None:
                        raise AssertionError(
                            "durable publication did not stage delivery"
                        )
                    ack_body = canonical_json(
                        {
                            "publication_id": str(publication_id),
                            "surface_id": delivery.surface_id,
                            "version": delivery.expected_page_version,
                            "digest": delivery.desired_digest,
                            "receipt_ref": f"drill-receipt:{suffix}",
                        }
                    )
                    receipt = await acknowledge_propagation_delivery(
                        session,
                        delivery_id=delivery.id,
                        ack_body=ack_body,
                        signature=f"sha256={sign_body(ack_body, _DRILL_DELIVERY_SECRET)}",
                        secret=_DRILL_DELIVERY_SECRET,
                    )
                    if receipt.get("status") != "synced":
                        raise AssertionError(
                            "signed drill delivery acknowledgement failed"
                        )
                    pending_draft = await create_wiki_draft(
                        session,
                        page_id=None,
                        author_id=actor.id,
                        content_md="Pending pre-review durable replay fixture.",
                        note="Keep one real pre-review outbox row pending.",
                        source_metadata={"source_ids": [str(source.id)]},
                        draft_kind="create",
                        suggested_metadata={
                            "slug": f"drill-pre-review-{suffix}",
                            "title": "Drill pre-review fixture",
                            "summary": "A pending durable pre-review outbox fixture.",
                            "page_type": "concept",
                            "knowledge_type_slugs": ["answer_card"],
                            "scope_type": "global",
                            "scope_id": None,
                            "language": "en",
                        },
                    )
                    await log_audit(
                        session,
                        actor,
                        "backup_drill_seed",
                        "wiki_page",
                        str(page.id),
                        reason="seeded real governed backup drill fixture",
                    )
                    fernet = Fernet(_derive_fernet_key(secret_key))
                    session.add(
                        AppConfig(
                            key="llm_api_key",
                            value=fernet.encrypt(b"sk-integration").decode(),
                        )
                    )
                    session.add(AppConfig(key="ai_pre_review_enabled", value="true"))
                    await session.commit()
                    return {
                        "actor_id": actor.id,
                        "source_id": source.id,
                        "source_dispatch_id": source_dispatch.id,
                        "page_id": page.id,
                        "draft_id": governed_draft.id,
                        "pending_draft_id": pending_draft.id,
                        "binding_id": binding.id,
                        "signal_id": signal.id,
                        "publication_id": publication_id,
                        "delivery_id": delivery.id,
                        "command": command,
                        "object_ref": object_ref,
                    }

            seeded = asyncio.run(seed())

            backup_dir = temporary / "backup"
            backup_request = BackupRequest(
                output_dir=backup_dir,
                database_url=src_async,
                object_store=ObjectStoreTarget(
                    endpoint=_INTEGRATION_MINIO_ENDPOINT,
                    access_key=_INTEGRATION_MINIO_ACCESS_KEY,
                    secret_key=_INTEGRATION_MINIO_SECRET_KEY,
                    bucket=src_bucket,
                    secure=False,
                ),
                environment="development",
                source_id=f"drill-src-{suffix}",
                quiesce_command="true",
                resume_command="true",
                retention_labels=("drill",),
                transforms=TransformCommands(),
                queue_reconcilers=DEFAULT_QUEUE_RECONCILERS,
                key_material={
                    "runtime.secret_key": secret_key,
                    "runtime.mcp_token_pepper": pepper,
                },
            )
            backup_report = run_backup(backup_request)
            self.assertEqual(backup_report["status"], "completed")
            self.assertEqual(backup_report["object_count"], 1)

            drill_request = RestoreRequest(
                backup_dir=backup_dir,
                target_database_url=dst_async,
                target_object_store=ObjectStoreTarget(
                    endpoint=_INTEGRATION_MINIO_ENDPOINT,
                    access_key=_INTEGRATION_MINIO_ACCESS_KEY,
                    secret_key=_INTEGRATION_MINIO_SECRET_KEY,
                    bucket=dst_bucket,
                    secure=False,
                ),
                target_redis_url=_INTEGRATION_REDIS_URL,
                target_environment="isolated",
                target_id=f"drill-dst-{suffix}",
                confirm_target=f"drill-dst-{suffix}",
                allow_production_restore=False,
                key_material={
                    "runtime.secret_key": secret_key,
                    "runtime.mcp_token_pepper": pepper,
                },
                transforms=TransformCommands(),
                queue_reconcilers=None,
                repo_root=_REPO_ROOT,
            )
            drill_report = run_drill(drill_request)
            self.assertEqual(drill_report["status"], "passed", drill_report)

            # RPO/RTO are measured, never invented.
            rpo = drill_report["rpo"]
            assert isinstance(rpo, dict)
            self.assertTrue(rpo["measured"])
            self.assertIsInstance(rpo["seconds"], float)
            self.assertGreaterEqual(rpo["seconds"], 0.0)
            rto = drill_report["rto"]
            assert isinstance(rto, dict)
            self.assertTrue(rto["measured"])
            self.assertIsInstance(rto["seconds"], float)
            self.assertGreater(rto["seconds"], 0.0)

            verification = drill_report["verification"]
            assert isinstance(verification, dict)
            counts = verification["table_row_counts"]
            self.assertTrue(counts["measured"])
            self.assertEqual(counts["matched"], counts["baseline_tables"])
            self.assertEqual(counts["mismatches"], [])
            hashes = verification["object_hashes"]
            self.assertEqual(hashes["checked"], 1)
            self.assertEqual(hashes["matched"], 1)
            self.assertEqual(verification["foreign_keys"]["orphan_rows"], 0)
            receipts = verification["idempotency_receipts"]
            self.assertEqual(receipts["ledger_event_duplicate_idempotency_keys"], [])
            self.assertTrue(receipts["ledger_event_count"]["matched"])
            self.assertEqual(receipts["outbox_job_id_duplicates"], [])
            self.assertTrue(receipts["outbox_row_count"]["matched"])
            self.assertEqual(receipts["source_dispatch_job_id_duplicates"], [])
            self.assertTrue(receipts["source_dispatch_row_count"]["matched"])
            self.assertEqual(
                verification["pending_jobs"]["nonterminal_outbox_rows_after_replay"],
                0,
            )
            self.assertEqual(
                verification["pending_jobs"][
                    "source_dispatch_nonterminal_rows_after_replay"
                ],
                0,
            )
            config_continuity = verification["encrypted_config"]
            self.assertTrue(config_continuity["checked"])
            self.assertGreaterEqual(config_continuity["decrypt_ok"], 1)
            self.assertEqual(config_continuity["decrypt_failures"], [])

            # The restored target holds actual source, approval, publication,
            # signed delivery, audit, and worker-outbox truth rather than rows
            # hand-shaped around a SQLite-friendly subset of constraints.
            async def verify_restored() -> None:
                dst_engine = create_async_engine(dst_async)
                try:
                    dst_sessions = async_sessionmaker(
                        dst_engine, expire_on_commit=False
                    )
                    async with dst_sessions() as session:
                        source = await session.get(
                            Source, cast(uuid.UUID, seeded["source_id"])
                        )
                        self.assertIsNotNone(source)
                        assert source is not None
                        self.assertEqual(source.title, "Drill source")
                        self.assertEqual(source.status, "ready")
                        self.assertEqual(source.language, "en")
                        self.assertEqual(source.freshness_state, "fresh")
                        self.assertEqual(
                            source.freshness_actor_id,
                            cast(uuid.UUID, seeded["actor_id"]),
                        )
                        self.assertIsNotNone(source.freshness_expires_at)

                        page = await session.get(
                            WikiPage, cast(uuid.UUID, seeded["page_id"])
                        )
                        self.assertIsNotNone(page)
                        assert page is not None
                        self.assertEqual(page.source_ids, [source.id])
                        self.assertEqual(page.language, "en")
                        self.assertEqual(
                            governed_object_ref(page.id), seeded["object_ref"]
                        )
                        draft = await session.get(
                            WikiPageDraft, cast(uuid.UUID, seeded["draft_id"])
                        )
                        self.assertIsNotNone(draft)
                        assert draft is not None
                        self.assertEqual(draft.status, "approved")
                        self.assertEqual(draft.page_id, page.id)

                        binding = await session.get(
                            GovernanceAudienceBinding,
                            cast(uuid.UUID, seeded["binding_id"]),
                        )
                        self.assertIsNotNone(binding)
                        assert binding is not None
                        self.assertEqual(
                            binding.object_ref, governed_object_ref(page.id)
                        )
                        self.assertEqual(binding.page_id, page.id)
                        self.assertEqual(binding.lifecycle_state, "active")

                        signal = await session.get(
                            GovernanceSignal, cast(uuid.UUID, seeded["signal_id"])
                        )
                        self.assertIsNotNone(signal)
                        assert signal is not None
                        self.assertEqual(signal.status, "active")
                        self.assertEqual(signal.page_id, page.id)
                        self.assertEqual(signal.object_ref, binding.object_ref)
                        self.assertEqual(signal.freshness, "fresh")

                        publication = await session.get(
                            GovernancePublication,
                            cast(uuid.UUID, seeded["publication_id"]),
                        )
                        self.assertIsNotNone(publication)
                        assert publication is not None
                        approval = await session.get(
                            GovernanceLedgerEvent, publication.approval_event_id
                        )
                        self.assertIsNotNone(approval)
                        assert approval is not None
                        self.assertEqual(approval.payload["page_id"], str(page.id))
                        self.assertEqual(approval.payload["page_version"], page.version)
                        self.assertEqual(
                            publication.approval_digest,
                            approval.payload["approval_digest"],
                        )
                        self.assertEqual(publication.page_id, page.id)
                        self.assertEqual(publication.object_ref, binding.object_ref)
                        self.assertEqual(publication.object_version, page.version)

                        propagation = await session.scalar(
                            select(GovernancePropagation).where(
                                GovernancePropagation.publication_id == publication.id
                            )
                        )
                        self.assertIsNotNone(propagation)
                        assert propagation is not None
                        self.assertEqual(propagation.status, "synced")
                        delivery = await session.get(
                            GovernancePropagationDelivery,
                            cast(uuid.UUID, seeded["delivery_id"]),
                        )
                        self.assertIsNotNone(delivery)
                        assert delivery is not None
                        self.assertEqual(delivery.status, "synced")
                        self.assertEqual(delivery.propagation_id, propagation.id)
                        self.assertEqual(
                            delivery.desired_digest, propagation.desired_digest
                        )
                        self.assertEqual(
                            delivery.acknowledged_digest, delivery.desired_digest
                        )
                        self.assertEqual(
                            delivery.expected_page_version,
                            delivery.acknowledged_version,
                        )
                        self.assertEqual(delivery.expected_page_version, page.version)
                        self.assertEqual(
                            delivery.expected_approval_version, approval.sequence
                        )
                        self.assertEqual(
                            delivery.expected_binding_versions,
                            [
                                {
                                    "binding_key": binding.binding_key,
                                    "version": binding.version,
                                }
                            ],
                        )

                        pre_review_dispatch = await session.scalar(
                            select(WikiDraftAiPreReviewDispatch).where(
                                WikiDraftAiPreReviewDispatch.draft_id
                                == cast(uuid.UUID, seeded["pending_draft_id"])
                            )
                        )
                        self.assertIsNotNone(pre_review_dispatch)
                        assert pre_review_dispatch is not None
                        self.assertEqual(
                            pre_review_dispatch.dispatch_status, "enqueued"
                        )
                        source_dispatch = await session.get(
                            SourceDispatchExecution,
                            cast(uuid.UUID, seeded["source_dispatch_id"]),
                        )
                        self.assertIsNotNone(source_dispatch)
                        assert source_dispatch is not None
                        self.assertEqual(source_dispatch.source_id, source.id)
                        self.assertEqual(source_dispatch.dispatch_status, "enqueued")

                        audit_rows = await session.scalar(
                            select(func.count())
                            .select_from(AuditLog)
                            .where(
                                AuditLog.action == "backup_drill_seed",
                                AuditLog.resource_id == str(page.id),
                            )
                        )
                        self.assertEqual(audit_rows, 1)
                        restored_config = await session.scalar(
                            select(AppConfig).where(AppConfig.key == "llm_api_key")
                        )
                        self.assertIsNotNone(restored_config)
                        assert restored_config is not None
                        assert restored_config.value is not None
                        self.assertEqual(
                            Fernet(_derive_fernet_key(secret_key)).decrypt(
                                restored_config.value.encode()
                            ),
                            b"sk-integration",
                        )

                        event_count_before = await session.scalar(
                            select(func.count())
                            .select_from(GovernanceLedgerEvent)
                            .where(GovernanceLedgerEvent.draft_id == draft.id)
                        )
                        publish_replay = await apply_durable_publish(
                            session,
                            command=cast(DurablePublishCommand, seeded["command"]),
                            actor_id=cast(uuid.UUID, seeded["actor_id"]),
                        )
                        self.assertTrue(publish_replay["replayed"])
                        ack_body = canonical_json(
                            {
                                "publication_id": str(publication.id),
                                "surface_id": delivery.surface_id,
                                "version": delivery.expected_page_version,
                                "digest": delivery.desired_digest,
                                "receipt_ref": f"drill-receipt:{suffix}",
                            }
                        )
                        ack_replay = await acknowledge_propagation_delivery(
                            session,
                            delivery_id=delivery.id,
                            ack_body=ack_body,
                            signature=(
                                f"sha256={sign_body(ack_body, _DRILL_DELIVERY_SECRET)}"
                            ),
                            secret=_DRILL_DELIVERY_SECRET,
                        )
                        self.assertTrue(ack_replay["replayed"])
                        event_count_after = await session.scalar(
                            select(func.count())
                            .select_from(GovernanceLedgerEvent)
                            .where(GovernanceLedgerEvent.draft_id == draft.id)
                        )
                        self.assertEqual(event_count_after, event_count_before)
                        await session.commit()
                finally:
                    await dst_engine.dispose()

            asyncio.run(verify_restored())
        finally:
            if engine is not None:
                import asyncio as _asyncio

                _asyncio.run(engine.dispose())
            for bucket in (src_bucket, dst_bucket):
                try:
                    for item in client.list_objects(bucket, recursive=True):
                        if item.object_name:
                            client.remove_object(bucket, item.object_name)
                    client.remove_bucket(bucket)
                except Exception:
                    pass
            for database in (dst_db, src_db):
                try:
                    subprocess.run(
                        [
                            "psql",
                            "--no-psqlrc",
                            "--quiet",
                            "--dbname",
                            base_sync,
                            "--command",
                            f'DROP DATABASE IF EXISTS "{database}"',
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except Exception:
                    pass
            import shutil as _shutil

            _shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
