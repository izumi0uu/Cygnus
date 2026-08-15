#!/usr/bin/env python3
"""Collect platform-bound BuildKit SBOM and provenance evidence for one OCI index."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypedDict, cast

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_PLATFORMS = ("linux/amd64", "linux/arm64")


class CollectionResult(TypedDict):
    sbom_bundle: dict[str, object]
    provenance_bundle: dict[str, object]


CommandRunner = Callable[[list[str]], str]


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "")
        detail = str(stderr).strip() or str(exc)
        raise RuntimeError(f"command failed: {' '.join(command)}: {detail}") from exc
    return result.stdout


def _require_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"{name} is required to collect image attestations")
    return executable


def _index_digest(image_ref: str) -> str:
    if "@" not in image_ref:
        raise ValueError("image reference must include an immutable index digest")
    digest = image_ref.rsplit("@", 1)[1]
    if not DIGEST_RE.fullmatch(digest):
        raise ValueError("image reference has an invalid index digest")
    return digest


def _json_object(text: str, label: str) -> dict[str, object]:
    try:
        value = cast(object, json.loads(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return cast(dict[str, object], value)


def _json_stream(text: str, label: str) -> list[object]:
    values: list[object] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            values.append(cast(object, json.loads(line)))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{label} line {line_number} is not valid JSON: {exc}"
            ) from exc
    if not values:
        raise ValueError(f"{label} did not contain any attestations")
    return values


def _platform_digests(index: Mapping[str, object]) -> dict[str, str]:
    raw_manifests = index.get("manifests")
    if not isinstance(raw_manifests, list):
        raise ValueError("OCI index has no manifests array")
    selected: dict[str, str] = {}
    for raw_descriptor in cast(list[object], raw_manifests):
        if not isinstance(raw_descriptor, dict):
            continue
        descriptor = cast(dict[str, object], raw_descriptor)
        raw_platform = descriptor.get("platform")
        digest = descriptor.get("digest")
        if not isinstance(raw_platform, dict) or not isinstance(digest, str):
            continue
        platform_data = cast(dict[str, object], raw_platform)
        operating_system = platform_data.get("os")
        architecture = platform_data.get("architecture")
        if not isinstance(operating_system, str) or not isinstance(architecture, str):
            continue
        platform = f"{operating_system}/{architecture}"
        if platform in REQUIRED_PLATFORMS:
            if platform in selected:
                raise ValueError(f"OCI index contains duplicate {platform} manifests")
            if not DIGEST_RE.fullmatch(digest):
                raise ValueError(f"OCI index {platform} manifest digest is invalid")
            selected[platform] = digest
    missing = [platform for platform in REQUIRED_PLATFORMS if platform not in selected]
    if missing:
        raise ValueError(
            f"OCI index is missing required platforms: {', '.join(missing)}"
        )
    return selected


def _walk(value: object) -> list[object]:
    values = [value]
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        for item in mapping.values():
            values.extend(_walk(item))
        payload = mapping.get("payload")
        if isinstance(payload, str):
            try:
                decoded = base64.b64decode(payload + "===")
                values.extend(_walk(cast(object, json.loads(decoded.decode("utf-8")))))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass
    elif isinstance(value, list):
        for item in cast(list[object], value):
            values.extend(_walk(item))
    return values


def _has_digest(value: object, digest: str) -> bool:
    plain = digest.removeprefix("sha256:")
    return any(
        isinstance(item, str) and item in {digest, plain} for item in _walk(value)
    )


def _contains_text(value: object, fragment: str) -> bool:
    return any(isinstance(item, str) and fragment in item for item in _walk(value))


def _has_slsa_provenance(attestations: list[object], manifest_digest: str) -> bool:
    return any(
        _contains_text(attestation, "slsa.dev/provenance")
        and _has_digest(attestation, manifest_digest)
        for attestation in attestations
    )


def collect_image_attestations(
    image_ref: str,
    *,
    runner: CommandRunner = _run,
    docker: str = "docker",
    cosign: str = "cosign",
) -> CollectionResult:
    index_digest = _index_digest(image_ref)
    index = _json_object(
        runner([docker, "buildx", "imagetools", "inspect", image_ref, "--raw"]),
        "OCI index",
    )
    manifests = _platform_digests(index)
    sbom_platforms: dict[str, object] = {}
    provenance_platforms: dict[str, object] = {}

    for platform in REQUIRED_PLATFORMS:
        manifest_digest = manifests[platform]
        sbom = _json_object(
            runner(
                [
                    cosign,
                    "download",
                    "sbom",
                    "--platform",
                    platform,
                    image_ref,
                ]
            ),
            f"{platform} SBOM",
        )
        if not isinstance(sbom.get("SPDXID"), str):
            raise ValueError(f"{platform} SBOM is not an SPDX document")
        attestations = _json_stream(
            runner(
                [
                    cosign,
                    "download",
                    "attestation",
                    "--platform",
                    platform,
                    image_ref,
                ]
            ),
            f"{platform} provenance",
        )
        if not _has_slsa_provenance(attestations, manifest_digest):
            raise ValueError(f"{platform} provenance is not bound to {manifest_digest}")
        sbom_platforms[platform] = {
            "manifest_digest": manifest_digest,
            "document": sbom,
        }
        provenance_platforms[platform] = {
            "manifest_digest": manifest_digest,
            "attestations": attestations,
        }

    common = {
        "schema_version": 1,
        "image_ref": image_ref,
        "image_index_digest": index_digest,
    }
    return {
        "sbom_bundle": {**common, "platforms": sbom_platforms},
        "provenance_bundle": {**common, "platforms": provenance_platforms},
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--image", required=True)
    _ = parser.add_argument("--sbom-out", type=Path, required=True)
    _ = parser.add_argument("--provenance-out", type=Path, required=True)
    args = parser.parse_args(argv)
    image_ref = cast(str, args.image)
    sbom_out = cast(Path, args.sbom_out)
    provenance_out = cast(Path, args.provenance_out)
    docker = _require_tool("docker")
    cosign = _require_tool("cosign")
    result = collect_image_attestations(
        image_ref,
        docker=docker,
        cosign=cosign,
    )
    _write_json(sbom_out, result["sbom_bundle"])
    _write_json(provenance_out, result["provenance_bundle"])
    print(
        f"[image-attestations] collected platform-bound SBOM and provenance for {image_ref}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
