#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_BASE_REF = "origin/main"


@dataclass
class PreservationArtifact:
    artifact_dir: str
    manifest_path: str
    delta_bundle_path: str
    full_bundle_path: str
    patches_dir: str
    base_ref: str
    base_commit: str
    head_commit: str
    ahead_commits: list[dict[str, str]]


@dataclass
class RestoreVerification:
    restore_dir: str
    restored_head: str
    original_head: str
    restored_subjects: list[str]
    expected_subjects: list[str]
    mode: str
    head_matches_original: bool
    subjects_match_expected: bool


def run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def run_git_quiet(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", "-C", str(repo), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def collect_ahead_commits(repo: Path, base_ref: str) -> list[dict[str, str]]:
    lines = run_git(repo, "log", "--reverse", "--format=%H%x09%s", f"{base_ref}..HEAD")
    if not lines:
        return []
    commits = []
    for line in lines.splitlines():
        sha, subject = line.split("\t", 1)
        commits.append({"sha": sha, "subject": subject})
    return commits


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def create_preservation_artifacts(repo: Path, output_root: Path, *, base_ref: str = DEFAULT_BASE_REF) -> PreservationArtifact:
    ensure_dir(output_root)
    patches_dir = output_root / "patches"
    ensure_dir(patches_dir)

    base_commit = run_git(repo, "rev-parse", base_ref)
    head_commit = run_git(repo, "rev-parse", "HEAD")
    ahead_commits = collect_ahead_commits(repo, base_ref)

    manifest_path = output_root / "manifest.txt"
    manifest_lines = [
        f"repo={repo}",
        f"branch={run_git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')}",
        f"base_ref={base_ref}",
        f"base={base_commit}",
        f"head={head_commit}",
        f"generated_at={datetime.now().astimezone().isoformat()}",
        "",
        "[ahead-commits]",
    ]
    manifest_lines.extend(f"{item['sha']} {item['subject']}" for item in ahead_commits)
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    delta_bundle_path = output_root / "arkon-ahead.bundle"
    full_bundle_path = output_root / "arkon-full.bundle"

    if ahead_commits:
        run_git_quiet(repo, "bundle", "create", str(delta_bundle_path), "HEAD", f"^{base_commit}")
        subprocess.check_call(["git", "-C", str(repo), "format-patch", "--quiet", "-o", str(patches_dir), f"{base_commit}..{head_commit}"])
    else:
        delta_bundle_path.write_text("", encoding="utf-8")

    run_git_quiet(repo, "bundle", "create", str(full_bundle_path), "--all")

    return PreservationArtifact(
        artifact_dir=str(output_root),
        manifest_path=str(manifest_path),
        delta_bundle_path=str(delta_bundle_path),
        full_bundle_path=str(full_bundle_path),
        patches_dir=str(patches_dir),
        base_ref=base_ref,
        base_commit=base_commit,
        head_commit=head_commit,
        ahead_commits=ahead_commits,
    )


def _expected_subjects(artifact: PreservationArtifact) -> list[str]:
    return [item["subject"] for item in artifact.ahead_commits]


def verify_delta_bundle(repo: Path, artifact: PreservationArtifact, *, cleanup: bool = True) -> RestoreVerification | None:
    if not artifact.ahead_commits:
        return None
    restore_root = Path(tempfile.mkdtemp(prefix="cygnus-arkon-restore-ahead-", dir="/private/tmp"))
    restore_repo = restore_root / "repo"
    subprocess.check_call(["git", "clone", "--quiet", str(repo), str(restore_repo)])
    run_git_quiet(restore_repo, "checkout", artifact.base_commit)
    subprocess.check_call(["git", "-C", str(restore_repo), "pull", "--quiet", artifact.delta_bundle_path, "HEAD"])
    restored_head = run_git(restore_repo, "rev-parse", "HEAD")
    subjects_raw = run_git(restore_repo, "log", "--reverse", "--format=%s", f"{artifact.base_commit}..{restored_head}")
    subjects = [line for line in subjects_raw.splitlines() if line]
    expected_subjects = _expected_subjects(artifact)
    result = RestoreVerification(
        restore_dir=str(restore_root),
        restored_head=restored_head,
        original_head=artifact.head_commit,
        restored_subjects=subjects,
        expected_subjects=expected_subjects,
        mode="delta_bundle",
        head_matches_original=restored_head == artifact.head_commit,
        subjects_match_expected=subjects == expected_subjects,
    )
    if cleanup:
        shutil.rmtree(restore_root)
    return result


def verify_patch_series(repo: Path, artifact: PreservationArtifact, *, cleanup: bool = True) -> RestoreVerification | None:
    patch_files = sorted(Path(artifact.patches_dir).glob("*.patch"))
    if not patch_files:
        return None
    restore_root = Path(tempfile.mkdtemp(prefix="cygnus-arkon-restore-patch-", dir="/private/tmp"))
    subprocess.check_call(["git", "clone", "--quiet", str(repo), str(restore_root)])
    run_git_quiet(restore_root, "checkout", artifact.base_commit)
    subprocess.check_call(["git", "-C", str(restore_root), "am", "--quiet", *[str(p) for p in patch_files]])
    restored_head = run_git(restore_root, "rev-parse", "HEAD")
    subjects_raw = run_git(restore_root, "log", "--reverse", "--format=%s", f"{artifact.base_commit}..{restored_head}")
    subjects = [line for line in subjects_raw.splitlines() if line]
    expected_subjects = _expected_subjects(artifact)
    result = RestoreVerification(
        restore_dir=str(restore_root),
        restored_head=restored_head,
        original_head=artifact.head_commit,
        restored_subjects=subjects,
        expected_subjects=expected_subjects,
        mode="patch_series",
        head_matches_original=restored_head == artifact.head_commit,
        subjects_match_expected=subjects == expected_subjects,
    )
    if cleanup:
        shutil.rmtree(restore_root)
    return result


def build_report(repo: Path, output_root: Path, *, base_ref: str = DEFAULT_BASE_REF, verify_restore: bool = False, cleanup_restore: bool = True) -> dict[str, Any]:
    artifact = create_preservation_artifacts(repo, output_root, base_ref=base_ref)
    report: dict[str, Any] = {"artifact": asdict(artifact)}

    delta_verify = None
    patch_verify = None
    if verify_restore:
        delta_verify = verify_delta_bundle(repo, artifact, cleanup=cleanup_restore)
        patch_verify = verify_patch_series(repo, artifact, cleanup=cleanup_restore)

    report["verification"] = {
        "delta_bundle": asdict(delta_verify) if delta_verify else None,
        "patch_series": asdict(patch_verify) if patch_verify else None,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Preserve and verify local history for an external checkout before deletion.")
    parser.add_argument("repo", help="Path to the external git checkout to preserve.")
    parser.add_argument("--output-dir", help="Exact output directory. Defaults to a timestamped /private/tmp location.")
    parser.add_argument("--base-ref", default=DEFAULT_BASE_REF, help="Base ref used to define ahead commits. Default: origin/main")
    parser.add_argument("--verify-restore", action="store_true", help="Verify recovery via delta bundle and patch series replay.")
    parser.add_argument("--keep-restore-dirs", action="store_true", help="Keep temporary restore directories created during verification.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"repo does not exist: {repo}")

    if args.output_dir:
        output_root = Path(args.output_dir).expanduser().resolve()
    else:
        output_root = Path("/private/tmp") / f"cygnus-arkon-preserve-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    report = build_report(
        repo,
        output_root,
        base_ref=args.base_ref,
        verify_restore=args.verify_restore,
        cleanup_restore=not args.keep_restore_dirs,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        artifact = report["artifact"]
        print("[external-checkout-preserve]")
        print(f"- artifact dir: {artifact['artifact_dir']}")
        print(f"- ahead commits: {len(artifact['ahead_commits'])}")
        print(f"- delta bundle: {artifact['delta_bundle_path']}")
        print(f"- full bundle: {artifact['full_bundle_path']}")
        print(f"- patches dir: {artifact['patches_dir']}")
        if args.verify_restore:
            print("- restore verification: enabled")
            for key in ("delta_bundle", "patch_series"):
                payload = report["verification"][key]
                if payload is None:
                    print(f"  - {key}: skipped")
                else:
                    print(
                        f"  - {key}: restored={payload['restored_head']} "
                        f"head_match={payload['head_matches_original']} "
                        f"subjects_match={payload['subjects_match_expected']}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
