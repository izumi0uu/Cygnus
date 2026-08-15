from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypeAlias, cast

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


writer = load("write_image_manifest")
gate = load("image_gate")
DIGEST = "sha256:" + "a" * 64

JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)


class ImageGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def manifest(self) -> dict[str, object]:
        return writer.build_manifest(
            git_sha="a" * 40,
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

    def materialize(self, manifest: dict[str, object]) -> None:
        images = cast(dict[str, dict[str, object]], manifest["images"])
        for entry in images.values():
            for artifact in (
                "sbom",
                "signature",
                "certificate",
                "verification",
                "provenance",
                "scan",
            ):
                path = self.root / str(entry[artifact])
                path.parent.mkdir(parents=True, exist_ok=True)
                content: JSONValue
                if artifact == "sbom":
                    content = {"SPDXID": "SPDXRef-DOCUMENT", "spdxVersion": "SPDX-2.3"}
                elif artifact == "provenance":
                    content = {
                        "_type": "https://in-toto.io/Statement/v1",
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [
                            {"digest": {"sha256": DIGEST.removeprefix("sha256:")}}
                        ],
                    }
                elif artifact == "verification":
                    content = [
                        {"critical": {"image": {"docker-manifest-digest": DIGEST}}}
                    ]
                elif artifact == "scan":
                    content = {"Results": [{"Vulnerabilities": []}]}
                else:
                    path.write_text("non-empty", encoding="utf-8")
                    continue
                path.write_text(json.dumps(content), encoding="utf-8")

    def test_complete_digest_bound_manifest_passes(self) -> None:
        manifest = self.manifest()
        self.materialize(manifest)
        result = gate.validate_manifest(manifest, repo_root=self.root)
        self.assertTrue(result["ok"], result["failures"])

    def test_unbound_provenance_blocks(self) -> None:
        manifest = self.manifest()
        self.materialize(manifest)
        path = self.root / "production/provenance/backend.json"
        path.write_text(
            json.dumps(
                {
                    "_type": "https://in-toto.io/Statement/v1",
                    "predicateType": "https://slsa.dev/provenance/v1",
                }
            ),
            encoding="utf-8",
        )
        result = gate.validate_manifest(manifest, repo_root=self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("provenance is not bound" in item for item in result["failures"])
        )

    def test_high_finding_blocks(self) -> None:
        manifest = self.manifest()
        self.materialize(manifest)
        path = self.root / "production/scans/backend.json"
        path.write_text(
            json.dumps(
                {
                    "Results": [
                        {
                            "Vulnerabilities": [
                                {"VulnerabilityID": "CVE-x", "Severity": "HIGH"}
                            ]
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = gate.validate_manifest(manifest, repo_root=self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("HIGH/CRITICAL" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
