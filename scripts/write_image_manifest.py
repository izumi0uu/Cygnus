#!/usr/bin/env python3
"""Write the immutable, release-bound Cygnus image manifest.

Only CI creates a released manifest. It binds both multi-architecture image
index digests, SBOM/provenance/signature verification artifacts, Git commit,
and the Alembic head compiled into the backend image. A pending manifest is
visible schema documentation only and every release gate rejects it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "production" / "image-manifest.json"
SCHEMA_VERSION = 2
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _image_entry(
    *,
    name: str,
    digest: str,
    sbom: str,
    signature: str,
    certificate: str,
    verification: str,
    provenance: str,
    scan: str,
    pending: bool,
) -> dict[str, object]:
    if pending:
        return {
            "image": name,
            "digest": None,
            "status": "pending",
            "sbom": None,
            "signature": None,
            "certificate": None,
            "verification": None,
            "provenance": None,
            "scan": None,
        }
    if not DIGEST_PATTERN.fullmatch(digest):
        raise ValueError(f"invalid digest {digest!r}; expected sha256:<64 hex>")
    if not IMAGE_REF_PATTERN.fullmatch(name):
        raise ValueError(f"invalid lowercase image reference {name!r}")
    if not all((sbom, signature, certificate, verification, provenance, scan)):
        raise ValueError(
            f"image {name!r} is missing a required supply-chain artifact path"
        )
    return {
        "image": name,
        "digest": digest,
        "status": "released",
        "sbom": sbom,
        "signature": signature,
        "certificate": certificate,
        "verification": verification,
        "provenance": provenance,
        "scan": scan,
    }


def build_manifest(
    *,
    git_sha: str,
    git_ref: str,
    version: str,
    created: str,
    alembic_head: str,
    backend_image: str,
    backend_digest: str,
    sbom_backend: str,
    signature_backend: str,
    certificate_backend: str,
    verification_backend: str,
    scan_backend: str,
    provenance_backend: str,
    frontend_image: str,
    frontend_digest: str,
    sbom_frontend: str,
    signature_frontend: str,
    certificate_frontend: str,
    verification_frontend: str,
    scan_frontend: str,
    provenance_frontend: str,
    pending: bool = False,
) -> dict[str, object]:
    if not pending:
        if not SHA_PATTERN.fullmatch(git_sha):
            raise ValueError("git_sha must be an immutable commit SHA")
        if not alembic_head:
            raise ValueError("alembic_head is required for a released manifest")
    return {
        "schema_version": SCHEMA_VERSION,
        "git": {"sha": git_sha, "ref": git_ref, "version": version},
        "alembic_head": alembic_head if not pending else None,
        "created": created,
        "images": {
            "backend": _image_entry(
                name=backend_image,
                digest=backend_digest,
                sbom=sbom_backend,
                signature=signature_backend,
                certificate=certificate_backend,
                verification=verification_backend,
                provenance=provenance_backend,
                scan=scan_backend,
                pending=pending,
            ),
            "frontend": _image_entry(
                name=frontend_image,
                digest=frontend_digest,
                sbom=sbom_frontend,
                signature=signature_frontend,
                certificate=certificate_frontend,
                verification=verification_frontend,
                provenance=provenance_frontend,
                scan=scan_frontend,
                pending=pending,
            ),
        },
        "generated_by": "scripts/write_image_manifest.py",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--git-ref", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--created", required=True)
    parser.add_argument("--alembic-head", default="")
    for key in ("backend", "frontend"):
        parser.add_argument(f"--{key}-image", required=True)
        parser.add_argument(f"--{key}-digest", default="")
        parser.add_argument(f"--sbom-{key}", default="")
        parser.add_argument(f"--signature-{key}", default="")
        parser.add_argument(f"--certificate-{key}", default="")
        parser.add_argument(f"--verification-{key}", default="")
        parser.add_argument(f"--scan-{key}", default="")
        parser.add_argument(f"--provenance-{key}", default="")
    parser.add_argument("--pending", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            git_sha=args.git_sha,
            git_ref=args.git_ref,
            version=args.version,
            created=args.created,
            alembic_head=args.alembic_head,
            backend_image=args.backend_image,
            backend_digest=args.backend_digest,
            sbom_backend=args.sbom_backend,
            signature_backend=args.signature_backend,
            certificate_backend=args.certificate_backend,
            verification_backend=args.verification_backend,
            scan_backend=args.scan_backend,
            provenance_backend=args.provenance_backend,
            frontend_image=args.frontend_image,
            frontend_digest=args.frontend_digest,
            sbom_frontend=args.sbom_frontend,
            signature_frontend=args.signature_frontend,
            certificate_frontend=args.certificate_frontend,
            verification_frontend=args.verification_frontend,
            scan_frontend=args.scan_frontend,
            provenance_frontend=args.provenance_frontend,
            pending=args.pending,
        )
    except ValueError as exc:
        print(f"[write-image-manifest] ERROR: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[write-image-manifest] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
