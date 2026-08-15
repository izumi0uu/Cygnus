from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias, cast

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SHA = "b" * 40
DIGEST = "sha256:" + "c" * 64

JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


writer = load("write_image_manifest")
image_gate = load("image_gate")
release_gate = load("release_gate")
live_report_gate = load("live_certification_report_gate")


class ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "production/evidence"
        self.evidence.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_manifest(self) -> Path:
        manifest = writer.build_manifest(
            git_sha=SHA,
            git_ref="v1.0.0",
            version="1.0.0",
            created="2026-08-15T00:00:00Z",
            alembic_head="head_1",
            backend_image="ghcr.io/example/cygnus/backend:rc",
            backend_digest=DIGEST,
            sbom_backend="production/sboms/backend.json",
            signature_backend="production/signatures/backend.sig",
            certificate_backend="production/signatures/backend.crt",
            verification_backend="production/signatures/backend.verify.json",
            provenance_backend="production/provenance/backend.json",
            scan_backend="production/scans/backend.json",
            frontend_image="ghcr.io/example/cygnus/frontend:rc",
            frontend_digest=DIGEST,
            sbom_frontend="production/sboms/frontend.json",
            signature_frontend="production/signatures/frontend.sig",
            certificate_frontend="production/signatures/frontend.crt",
            verification_frontend="production/signatures/frontend.verify.json",
            provenance_frontend="production/provenance/frontend.json",
            scan_frontend="production/scans/frontend.json",
        )
        for entry in manifest["images"].values():
            for artifact in (
                "sbom",
                "signature",
                "certificate",
                "verification",
                "provenance",
                "scan",
            ):
                path = self.root / entry[artifact]
                path.parent.mkdir(parents=True, exist_ok=True)
                value: JSONValue
                if artifact == "sbom":
                    value = {"SPDXID": "SPDXRef-DOCUMENT"}
                elif artifact == "provenance":
                    value = {
                        "_type": "https://in-toto.io/Statement/v1",
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [{"digest": {"sha256": DIGEST[7:]}}],
                    }
                elif artifact == "verification":
                    value = [
                        {"critical": {"image": {"docker-manifest-digest": DIGEST}}}
                    ]
                elif artifact == "scan":
                    value = {"Results": [{"Vulnerabilities": []}]}
                else:
                    path.write_text("non-empty", encoding="utf-8")
                    continue
                path.write_text(json.dumps(value), encoding="utf-8")
        path = self.root / "production/image-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def wrapper(self, name: str, report: Path | None = None, **checks: str) -> None:
        if report:
            checks["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
        (self.evidence / f"{name}.json").write_text(
            json.dumps({"passed": True, "git_sha": SHA, "checks": checks}),
            encoding="utf-8",
        )

    @staticmethod
    def live_checks(name: str) -> list[dict[str, object]]:
        return [
            {
                "name": check_name,
                "passed": True,
                "details": {"observation": f"{name}:{check_name}"},
            }
            for check_name in sorted(release_gate.REQUIRED_LIVE_REPORT_CHECKS[name])
        ]

    @staticmethod
    def report_checks(report: dict[str, object]) -> list[dict[str, object]]:
        checks = report.get("checks")
        assert isinstance(checks, list) and all(
            isinstance(check, dict) for check in checks
        )
        return cast(list[dict[str, object]], checks)

    def write_complete_evidence(self) -> None:
        for name in release_gate.DEFAULT_REQUIRED_EVIDENCE:
            if name not in release_gate.STRUCTURED_REPORTS:
                self.wrapper(name)
        backend_ref = f"ghcr.io/example/cygnus/backend:rc@{DIGEST}"
        capacity = {
            "suite_name": "cygnus-production-capacity-gate",
            "status": "PASS",
            "environment": "staging",
            "release": {
                "commit_sha": SHA,
                "image_tag": backend_ref,
                "alembic_revision": "head_1",
                "identity_verified": True,
            },
            "routes": [
                {
                    "route": route,
                    "measured": True,
                    "status": "PASS",
                    "checks": [{"passed": True}],
                }
                for route in (
                    "publish",
                    "ticket_import",
                    "ingestion",
                    "worker",
                    "query",
                )
            ],
            "failure_injection": {
                "enabled": True,
                "guard_allowed": True,
                "recovered_all": True,
                "expected_targets": ["db", "queue", "tool", "provider"],
                "exercised_targets": ["db", "queue", "tool", "provider"],
            },
        }
        drill = {
            "report_format": "cygnus-drill-report/v1",
            "operation": "drill",
            "status": "passed",
            "source": {"environment": "production", "identity": "prod-1"},
            "target": {"environment": "isolated", "identity": "drill-1"},
            "release_identity": {
                "git_commit": SHA,
                "backend_image_ref": backend_ref,
                "frontend_image_ref": f"ghcr.io/example/cygnus/frontend:rc@{DIGEST}",
                "alembic_head": "head_1",
            },
            "release_identity_requirement": {
                "manifest_required": True,
                "expected_match_required": True,
                "expected_match_verified": True,
            },
            "rpo": {"measured": True, "seconds": 1},
            "rto": {"measured": True, "seconds": 2},
            "objectives": {"rpo_max_seconds": 10, "rto_max_seconds": 20},
            "objective_refs": {
                "rpo_objective_ref": "approval://rpo",
                "rto_objective_ref": "approval://rto",
            },
            "objective_requirement": {"required": True, "both_declared": True},
            "verification": {
                "table_row_counts": {"mismatches": []},
                "object_hashes": {"mismatches": []},
                "foreign_keys": {"orphans": []},
                "idempotency_receipts": {
                    "ledger_event_duplicate_idempotency_keys": [],
                    "outbox_job_id_duplicates": [],
                },
                "pending_jobs": {"nonterminal_outbox_rows_after_replay": 0},
                "redis": {"enqueued_outbox_without_arq_job": []},
                "encrypted_config": {"decrypt_failures": []},
            },
            "checks": [{"passed": True}],
        }
        production_inputs = {
            "gate": "production_inputs_gate",
            "git_sha": SHA,
            "ok": True,
            "failures": [],
            "checks": {
                "release_git_sha": {"matches": True},
                "release_backend_image": {"matches": True},
                "release_frontend_image": {"matches": True},
                "release_alembic_head": {"matches": True},
                "metrics_allowlist_binding": True,
                "public_domain_binding": True,
                "capacity_threshold_binding": True,
                "alert_threshold_binding": True,
                "backup_objective_binding": True,
                "delivery_target_binding": True,
                "delivery_hmac_ref_binding": True,
                "input_fingerprint_sha256": "d" * 64,
            },
        }
        reports = {
            "production-inputs": production_inputs,
            "capacity-gate": capacity,
            "backup-restore-drill": drill,
        }
        for name in (
            "production-e2e",
            "browser-e2e",
            "security-failure-injection",
            "persisted-domain-eval",
        ):
            reports[name] = {
                "report_format": f"cygnus-{name}-report/v1",
                "status": "passed",
                "git_sha": SHA,
                "generated_at": "2026-08-15T00:00:00Z",
                "release_identity": {
                    "git_commit": SHA,
                    "backend_image_ref": backend_ref,
                    "frontend_image_ref": f"ghcr.io/example/cygnus/frontend:rc@{DIGEST}",
                    "alembic_head": "head_1",
                },
                "checks": self.live_checks(name),
            }
        for name, report in reports.items():
            path = self.evidence / release_gate.STRUCTURED_REPORTS[name]
            path.write_text(json.dumps(report), encoding="utf-8")
            if name == "backup-restore-drill":
                self.wrapper(
                    name,
                    path,
                    source_identity="prod-1",
                    rpo_objective_ref="approval://rpo",
                    rto_objective_ref="approval://rto",
                )
            else:
                self.wrapper(name, path)

    def assert_live_report_rejected_by_both(
        self,
        *,
        name: str,
        mutate: Callable[[dict[str, object]], None],
        expected_failure: str,
    ) -> None:
        manifest = self.write_manifest()
        self.write_complete_evidence()
        report_path = self.evidence / release_gate.STRUCTURED_REPORTS[name]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert isinstance(report, dict)
        mutate(report)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        self.wrapper(name, report_path)

        _, wrapper_failures = live_report_gate.validate(
            name=name,
            report_path=report_path,
            git_sha=SHA,
            backend_image=f"ghcr.io/example/cygnus/backend:rc@{DIGEST}",
            frontend_image=f"ghcr.io/example/cygnus/frontend:rc@{DIGEST}",
            alembic_head="head_1",
        )
        self.assertTrue(
            any(expected_failure in failure for failure in wrapper_failures),
            wrapper_failures,
        )

        result = release_gate.validate_release(
            manifest_path=manifest,
            evidence_dir=self.evidence,
            required_evidence=release_gate.DEFAULT_REQUIRED_EVIDENCE,
            repo_root=self.root,
        )
        self.assertFalse(result["ok"])
        final_failures = result["failures"]
        assert isinstance(final_failures, list)
        self.assertTrue(
            any(
                expected_failure in failure
                for failure in final_failures
                if isinstance(failure, str)
            ),
            final_failures,
        )

    def test_complete_release_passes(self) -> None:
        manifest = self.write_manifest()
        self.write_complete_evidence()
        result = release_gate.validate_release(
            manifest_path=manifest,
            evidence_dir=self.evidence,
            required_evidence=release_gate.DEFAULT_REQUIRED_EVIDENCE,
            repo_root=self.root,
        )
        self.assertTrue(result["ok"], result["failures"])

    def test_truthy_string_false_blocks(self) -> None:
        manifest = self.write_manifest()
        self.write_complete_evidence()
        path = self.evidence / "backend-tests.json"
        path.write_text(
            json.dumps({"passed": "false", "git_sha": SHA, "checks": {}}),
            encoding="utf-8",
        )
        result = release_gate.validate_release(
            manifest_path=manifest,
            evidence_dir=self.evidence,
            required_evidence=release_gate.DEFAULT_REQUIRED_EVIDENCE,
            repo_root=self.root,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("JSON boolean" in failure for failure in result["failures"])
        )

    def test_live_report_with_wrong_image_identity_blocks(self) -> None:
        manifest = self.write_manifest()
        self.write_complete_evidence()
        report_path = self.evidence / "cygnus.browser-e2e.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["release_identity"]["frontend_image_ref"] = (
            "ghcr.io/example/cygnus/frontend:wrong@" + DIGEST
        )
        report_path.write_text(json.dumps(report), encoding="utf-8")
        self.wrapper("browser-e2e", report_path)

        result = release_gate.validate_release(
            manifest_path=manifest,
            evidence_dir=self.evidence,
            required_evidence=release_gate.DEFAULT_REQUIRED_EVIDENCE,
            repo_root=self.root,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(
            any(
                "browser-e2e release_identity does not exactly match" in failure
                for failure in result["failures"]
            )
        )

    def test_each_live_report_missing_required_semantic_check_blocks(self) -> None:
        for name, required in release_gate.REQUIRED_LIVE_REPORT_CHECKS.items():
            missing = sorted(required)[0]

            def remove_required(
                report: dict[str, object], check_name: str = missing
            ) -> None:
                report["checks"] = [
                    check
                    for check in self.report_checks(report)
                    if check.get("name") != check_name
                ]

            with self.subTest(name=name, missing=missing):
                self.assert_live_report_rejected_by_both(
                    name=name,
                    mutate=remove_required,
                    expected_failure=(
                        f"{name} report is missing required checks: {missing}"
                    ),
                )

    def test_live_report_with_unnamed_passed_check_blocks(self) -> None:
        def add_unnamed(report: dict[str, object]) -> None:
            self.report_checks(report).append(
                {"passed": True, "details": {"observation": "completed"}}
            )

        self.assert_live_report_rejected_by_both(
            name="production-e2e",
            mutate=add_unnamed,
            expected_failure="must have a non-empty, trimmed string name",
        )

    def test_live_report_with_duplicate_check_name_blocks(self) -> None:
        def duplicate_check(report: dict[str, object]) -> None:
            checks = self.report_checks(report)
            checks.append(dict(checks[0]))

        self.assert_live_report_rejected_by_both(
            name="security-failure-injection",
            mutate=duplicate_check,
            expected_failure="report has duplicate check name",
        )

    def test_required_live_check_with_empty_evidence_or_details_blocks(self) -> None:
        empty_values: tuple[tuple[str, object], ...] = (
            ("details", {}),
            ("evidence", []),
        )
        for field, empty_value in empty_values:

            def empty_required_evidence(
                report: dict[str, object],
                field_name: str = field,
                value: object = empty_value,
            ) -> None:
                check = self.report_checks(report)[0]
                check.pop("details", None)
                check.pop("evidence", None)
                check[field_name] = value

            with self.subTest(field=field):
                self.assert_live_report_rejected_by_both(
                    name="persisted-domain-eval",
                    mutate=empty_required_evidence,
                    expected_failure=(
                        "must contain non-empty structured evidence or details"
                    ),
                )

    def test_live_report_check_without_json_boolean_pass_blocks(self) -> None:
        def replace_boolean(report: dict[str, object]) -> None:
            self.report_checks(report)[0]["passed"] = "true"

        self.assert_live_report_rejected_by_both(
            name="browser-e2e",
            mutate=replace_boolean,
            expected_failure="must contain JSON boolean passed: true",
        )

    def test_live_report_with_malformed_extra_check_blocks(self) -> None:
        def add_malformed(report: dict[str, object]) -> None:
            report["checks"] = [*self.report_checks(report), "malformed"]

        self.assert_live_report_rejected_by_both(
            name="production-e2e",
            mutate=add_malformed,
            expected_failure="must be an object",
        )

    def test_complete_browser_contract_allows_named_extra_check(self) -> None:
        manifest = self.write_manifest()
        self.write_complete_evidence()
        report_path = self.evidence / "cygnus.browser-e2e.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert isinstance(report, dict)
        self.report_checks(report).append(
            {"name": "operator-approved-extra-probe", "passed": True}
        )
        report_path.write_text(json.dumps(report), encoding="utf-8")
        self.wrapper("browser-e2e", report_path)

        _, wrapper_failures = live_report_gate.validate(
            name="browser-e2e",
            report_path=report_path,
            git_sha=SHA,
            backend_image=f"ghcr.io/example/cygnus/backend:rc@{DIGEST}",
            frontend_image=f"ghcr.io/example/cygnus/frontend:rc@{DIGEST}",
            alembic_head="head_1",
        )
        self.assertEqual([], wrapper_failures)

        result = release_gate.validate_release(
            manifest_path=manifest,
            evidence_dir=self.evidence,
            required_evidence=release_gate.DEFAULT_REQUIRED_EVIDENCE,
            repo_root=self.root,
        )
        self.assertTrue(result["ok"], result["failures"])

    def test_unbound_production_inputs_report_blocks(self) -> None:
        manifest = self.write_manifest()
        self.write_complete_evidence()
        report_path = self.evidence / "cygnus.production-inputs.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["checks"]["delivery_target_binding"] = False
        report_path.write_text(json.dumps(report), encoding="utf-8")
        self.wrapper("production-inputs", report_path)

        result = release_gate.validate_release(
            manifest_path=manifest,
            evidence_dir=self.evidence,
            required_evidence=release_gate.DEFAULT_REQUIRED_EVIDENCE,
            repo_root=self.root,
        )

        self.assertFalse(result["ok"])
        self.assertIn(
            "production inputs report delivery_target_binding did not pass",
            result["failures"],
        )

    def test_live_report_validator_rejects_wrong_candidate_identity(self) -> None:
        report_path = self.evidence / "native.json"
        report_path.write_text(
            json.dumps(
                {
                    "report_format": "cygnus-production-e2e-report/v1",
                    "status": "passed",
                    "git_sha": SHA,
                    "generated_at": "2026-08-15T00:00:00Z",
                    "release_identity": {
                        "git_commit": SHA,
                        "backend_image_ref": "wrong",
                        "frontend_image_ref": "frontend",
                        "alembic_head": "head_1",
                    },
                    "checks": self.live_checks("production-e2e"),
                }
            ),
            encoding="utf-8",
        )

        _, failures = live_report_gate.validate(
            name="production-e2e",
            report_path=report_path,
            git_sha=SHA,
            backend_image="backend",
            frontend_image="frontend",
            alembic_head="head_1",
        )

        self.assertIn(
            "release_identity must exactly match the candidate release",
            failures,
        )


if __name__ == "__main__":
    unittest.main()
