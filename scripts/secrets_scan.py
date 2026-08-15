#!/usr/bin/env python3
"""Fail-closed secret scanning gate for the Cygnus release pipeline.

Scans every non-ignored file in the repository (tracked files plus untracked
non-ignored files when run inside a git checkout; a plain recursive walk when
not) for high-confidence credential patterns. Any match outside an explicit
ignore list fails the gate, so a leaked key blocks image publication.

Usage:
    scripts/secrets_scan.py [--quiet] [--json] [--report PATH] [--ignore-path GLOB]

Exit status: 0 = clean, 1 = findings (fail-closed).
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_sha(repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# High-confidence credential patterns. These deliberately avoid generic
# "password = ..." heuristics that produce false positives on .env.example
# and test fixtures; the release pipeline's runtime-config hardening covers
# weak credentials separately.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "aws_secret_access_key",
        re.compile(
            r"\b(?:aws[_-]?)?secret(?:[_-]?access)?[_-]?key\s*[=:]\s*['\"][A-Za-z0-9/+=]{40}['\"]",
            re.IGNORECASE,
        ),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("stripe_live_secret", re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "jwt_bearer",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
)

# Paths whose contents are known samples of credentials (test fixtures) are
# never scanned; every other skip must be requested explicitly. The scanner's
# own test file builds sample credentials (including split-literal forms) to
# exercise detection, so it is a fixture rather than a leak.
DEFAULT_IGNORED_PATHS: frozenset[str] = frozenset(
    {"tests/fixtures", "tests/test_secrets_scan.py"}
)

# Binary and generated files are skipped; anything larger is almost certainly
# not a source file holding a credential.
MAX_FILE_BYTES = 2 * 1024 * 1024
BINARY_PROBE_BYTES = 8192
SKIPPED_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".svg",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".lock",
    }
)
SKIPPED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "__pycache__",
        ".venv",
        ".venv-runability",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".uv-cache",
        ".tox",
        ".tmp",
    }
)

# Cheap pre-filter: only lines that look like they join string literals with
# `+` (or implicitly) go through the tokenizer-based merge below.
_STRING_CONCAT_HINT = re.compile(
    r"""['"](?:[^'"\\]|\\.)*['"]\s*\+|['"](?:[^'"\\]|\\.)*['"]\s+['"]"""
)


def _merge_string_literal_concat(line: str) -> str:
    """Collapse Python string-literal concatenation on a single line.

    A credential split across adjacent literals (``'AKIA' + '…'``) is real
    code that assembles the secret at runtime, so the scanner must match the
    merged text. Concatenation nested inside another string literal (e.g. a
    test fixture that merely describes a key) is content rather than code and
    is left untouched.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(line).readline))
    except (tokenize.TokenError, IndentationError):
        return line
    parts: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type != tokenize.STRING:
            parts.append(token.string)
            index += 1
            continue
        merged = token.string
        end = index + 1
        while (
            end + 1 < len(tokens)
            and tokens[end].type == tokenize.OP
            and tokens[end].string == "+"
            and tokens[end + 1].type == tokenize.STRING
        ):
            merged += tokens[end + 1].string
            end += 2
        try:
            value = ast.literal_eval(merged)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            value = None
        parts.append(value if isinstance(value, str) else merged)
        index = end
    return "".join(parts)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    pattern: str
    snippet: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "pattern": self.pattern,
            "snippet": self.snippet,
        }


def _redact(match: re.Match[str]) -> str:
    text = match.group(0)
    if len(text) <= 12:
        return "<redacted>"
    return f"{text[:4]}…{text[-4:]}"


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            probe = handle.read(BINARY_PROBE_BYTES)
    except OSError:
        return True
    return b"\x00" in probe


def list_files(root: Path, *, use_git: bool) -> list[Path]:
    """Return every scannable file under `root`.

    Inside a git checkout this prefers git's own ignore rules (`git ls-files
    -c -o --exclude-standard`); otherwise it falls back to a recursive walk.
    """
    if use_git:
        try:
            listing = subprocess.run(
                ["git", "ls-files", "-z", "-c", "-o", "--exclude-standard"],
                cwd=str(root),
                capture_output=True,
                check=True,
                text=False,
            )
        except (OSError, subprocess.CalledProcessError):
            use_git = False
        else:
            tracked = [
                root / part
                for part in listing.stdout.decode("utf-8", "replace").split("\0")
                if part
            ]
            if tracked:
                return tracked
            # Empty listing inside a real checkout means a truly empty repo;
            # fall through to the walker only outside a checkout.
            return []

    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIPPED_DIR_NAMES for part in relative.parts):
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        files.append(path)
    return files


def scan_paths(
    paths: list[Path],
    *,
    root: Path,
    ignored: frozenset[str] = frozenset(),
) -> list[Finding]:
    findings: list[Finding] = []
    skip = DEFAULT_IGNORED_PATHS | ignored
    for path in paths:
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            relative = Path(path.name)
        rel_text = relative.as_posix()
        if any(rel_text == item or rel_text.startswith(f"{item}/") for item in skip):
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        if _is_binary(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _STRING_CONCAT_HINT.search(line):
                line = _merge_string_literal_concat(line)
            for pattern_name, pattern in PATTERNS:
                for match in pattern.finditer(line):
                    findings.append(
                        Finding(
                            path=rel_text,
                            line=line_no,
                            pattern=pattern_name,
                            snippet=_redact(match),
                        )
                    )
    return findings


def build_report(
    findings: list[Finding], *, root: Path, scanned: int
) -> dict[str, object]:
    return {
        "gate": "secrets_scan",
        "ok": not findings,
        "git_sha": _git_sha(root),
        "scanned_files": scanned,
        "findings": [finding.to_dict() for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed credential scan over the repository (release gate)."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to scan (default: repo root).",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Force the recursive walker instead of git ls-files.",
    )
    parser.add_argument(
        "--ignore-path",
        action="append",
        default=[],
        help="Additional relative path to skip (repeatable).",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print failures.")
    parser.add_argument(
        "--json", action="store_true", help="Emit the structured report as JSON."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the structured report to PATH (fail-closed evidence).",
    )
    args = parser.parse_args(argv)

    root = args.path.resolve()
    files = list_files(root, use_git=not args.no_git)
    ignored = frozenset(args.ignore_path)
    findings = scan_paths(files, root=root, ignored=ignored)
    report = build_report(findings, root=root, scanned=len(files))

    if args.report is not None:
        report_path = args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if findings:
        if not args.quiet:
            print("[secrets-scan] FAILED")
        for finding in findings:
            print(
                f"- {finding.path}:{finding.line} [{finding.pattern}] {finding.snippet}"
            )
        return 1

    if not args.quiet and not args.json:
        print(f"[secrets-scan] OK ({len(files)} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
