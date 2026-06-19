"""
L1 regex checks — PII + credentials.

Permissive: this runs sync at submit-time but NEVER blocks the submission.
Findings are recorded on the draft so the human reviewer sees a clear flag.
Contributors can suppress a flag with an inline allow-list marker:

    <!-- pii-allow: contact-email -->
    Email team: compliance@example.com

The marker scopes to the next ~2 non-blank lines so a single comment cannot
silently cover a whole document.
"""

import re
from dataclasses import dataclass
from typing import Iterable, Optional

# (id, human label, regex, severity).
# Severity 'fail' means we'd block in strict mode; in permissive mode it
# still just becomes a 'warn' or 'fail' in the results JSON and the human
# reviewer decides.
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("pii.email", "Email address", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("pii.phone_vn", "Vietnamese phone number", r"\b(?:0|\+84)\d{9,10}\b"),
    ("pii.cccd_vn", "12-digit national ID", r"(?<!\d)\d{12}(?!\d)"),
    ("secret.api_key_sk", "API key (sk-...)", r"\bsk-[A-Za-z0-9]{20,}\b"),
    ("secret.anthropic", "Anthropic key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    ("secret.aws_access", "AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("secret.github_pat", "GitHub PAT", r"\bghp_[A-Za-z0-9]{36}\b"),
    ("secret.google_api", "Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("secret.jwt", "JWT", r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    ("secret.private_key", "Private key block",
     r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

# Allow-list marker: `<!-- pii-allow: <reason> -->` on its own line.
# The marker covers regex matches on the SAME or NEXT line that isn't blank.
_ALLOW_RE = re.compile(r"<!--\s*pii-allow:\s*([^\s>][^>]*?)\s*-->")


@dataclass
class _AllowRegion:
    start_line: int
    end_line: int       # inclusive
    reason: str


def _collect_allow_regions(lines: list[str]) -> list[_AllowRegion]:
    """A marker covers the next non-blank line after itself (and itself)."""
    regions: list[_AllowRegion] = []
    for i, line in enumerate(lines):
        m = _ALLOW_RE.search(line)
        if not m:
            continue
        reason = m.group(1).strip()
        # Find the next non-blank line within 2 lookahead.
        end = i
        seen_content = 0
        for j in range(i + 1, min(len(lines), i + 4)):
            if lines[j].strip() and not _ALLOW_RE.search(lines[j]):
                end = j
                seen_content += 1
                if seen_content >= 1:
                    break
        regions.append(_AllowRegion(start_line=i, end_line=end, reason=reason))
    return regions


def _is_allowed(line_idx: int, regions: Iterable[_AllowRegion]) -> Optional[str]:
    for r in regions:
        if r.start_line <= line_idx <= r.end_line:
            return r.reason
    return None


def run(content_md: str) -> list[dict]:
    """Return one CheckResult dict per pattern. Order is stable for diffing."""
    out: list[dict] = []
    if not content_md:
        return out
    lines = content_md.splitlines()
    regions = _collect_allow_regions(lines)

    for check_id, label, pattern in _PATTERNS:
        regex = re.compile(pattern)
        raw_matches: list[dict] = []
        allowed_count = 0
        for line_idx, line in enumerate(lines):
            for m in regex.finditer(line):
                allow_reason = _is_allowed(line_idx, regions)
                if allow_reason is not None:
                    allowed_count += 1
                    continue
                raw_matches.append({
                    "line": line_idx + 1,
                    "snippet": _redact(m.group(0)),
                })

        if not raw_matches:
            status = "pass"
            message = (
                f"{allowed_count} suppressed by pii-allow marker" if allowed_count else None
            )
        else:
            status = "fail" if check_id.startswith("secret.") else "warn"
            message = f"{len(raw_matches)} {label.lower()} match(es) found in content"

        out.append({
            "id": check_id,
            "layer": "L1",
            "severity": "block" if check_id.startswith("secret.") else "warn",
            "status": status,
            "message": message,
            "matches": raw_matches[:10],  # cap so JSONB stays small
            "suppressed": allowed_count,
        })
    return out


def _redact(s: str) -> str:
    """Don't write full secrets back into ai_check_results JSONB."""
    if len(s) <= 8:
        return "***"
    return s[:4] + "…" + s[-2:]
