#!/usr/bin/env python3
"""Collect platform-bound BuildKit SBOM and provenance evidence for one OCI index."""

from __future__ import annotations

import argparse
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


def _platform_document(
    evidence: Mapping[str, object], platform: str, key: str, label: str
) -> dict[str, object]:
    raw_entry = evidence.get(platform)
    if not isinstance(raw_entry, dict):
        raise ValueError(f"{label} has no {platform} entry")
    entry = cast(dict[str, object], raw_entry)
    raw_document = entry.get(key)
    if not isinstance(raw_document, dict) or not raw_document:
        raise ValueError(f"{label} has no {platform} {key} document")
    return cast(dict[str, object], raw_document)


def collect_image_attestations(
    image_ref: str,
    *,
    runner: CommandRunner = _run,
    docker: str = "docker",
) -> CollectionResult:
    index_digest = _index_digest(image_ref)
    inspect_command = [docker, "buildx", "imagetools", "inspect", image_ref]
    index = _json_object(runner([*inspect_command, "--raw"]), "OCI index")
    manifests = _platform_digests(index)
    sbom_evidence = _json_object(
        runner([*inspect_command, "--format", "{{ json .SBOM }}"]),
        "BuildKit SBOM evidence",
    )
    provenance_evidence = _json_object(
        runner([*inspect_command, "--format", "{{ json .Provenance }}"]),
        "BuildKit provenance evidence",
    )
    sbom_platforms: dict[str, object] = {}
    provenance_platforms: dict[str, object] = {}

    for platform in REQUIRED_PLATFORMS:
        manifest_digest = manifests[platform]
        sbom = _platform_document(
            sbom_evidence, platform, "SPDX", "BuildKit SBOM evidence"
        )
        if not isinstance(sbom.get("SPDXID"), str):
            raise ValueError(f"{platform} BuildKit SBOM is not an SPDX document")
        provenance = _platform_document(
            provenance_evidence, platform, "SLSA", "BuildKit provenance evidence"
        )
        build_definition = provenance.get("buildDefinition")
        build_type = (
            cast(dict[str, object], build_definition).get("buildType")
            if isinstance(build_definition, dict)
            else None
        )
        if not isinstance(build_type, str) or not build_type:
            raise ValueError(f"{platform} BuildKit provenance has no SLSA build type")
        sbom_platforms[platform] = {
            "manifest_digest": manifest_digest,
            "predicate_type": "https://spdx.dev/Document",
            "document": sbom,
        }
        provenance_platforms[platform] = {
            "manifest_digest": manifest_digest,
            "predicate_type": "https://slsa.dev/provenance/v1",
            "predicate": provenance,
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
    result = collect_image_attestations(image_ref, docker=docker)
    _write_json(sbom_out, result["sbom_bundle"])
    _write_json(provenance_out, result["provenance_bundle"])
    print(
        f"[image-attestations] collected platform-bound SBOM and provenance for {image_ref}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
