from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypeAlias

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
release_gate = load("release_gate")


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
        reports = {"capacity-gate": capacity, "backup-restore-drill": drill}
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
                "checks": [{"passed": True}],
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


if __name__ == "__main__":
    unittest.main()
