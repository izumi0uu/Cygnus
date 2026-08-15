"""Sanitization helpers for observability surfaces.

Every value that reaches a metric label, log line, or alert annotation must
pass through here. Guarantees:
- bounded length (labels and annotation strings)
- no raw payloads: only scalar/identifier-shaped values are kept
- no secret-shaped values: common secret key names are dropped entirely
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Keys and value prefixes that commonly carry credentials.  These checks are
# deliberately conservative: a value that looks secret-shaped is replaced as
# a whole rather than partially logged.  Observability must fail closed when a
# provider accidentally includes a credential in an exception or label.
_SECRET_KEY_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "pepper",
    "private_key",
    "privatekey",
    "credential",
)
_SECRET_VALUE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|pepper|credential)\s*[:=]\s*[^\s,;]+",
        r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
        r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]{8,})?\b",
        r"-----BEGIN [^-]+ PRIVATE KEY-----",
    )
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

# Label values may contain alphanumerics plus a conservative punctuation set.
_ALLOWED_LABEL_CHARS = re.compile(r"[^A-Za-z0-9_\-.:/]+")

# Strict snake_case identifier shape (lowercase start, then [a-z0-9_],
# max 64 chars).  Identifier labels (MCP tool/operation names) only emit this
# bounded vocabulary; arbitrary user/query text collapses to ``unknown``.
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _SECRET_KEY_HINTS)


def _redact_sensitive_text(
    text: str, *, replacement: str = "<redacted>"
) -> tuple[str, bool]:
    """Redact credential-shaped content and email addresses from text.

    The boolean tells callers whether a credential was found.  Credential
    matches replace the complete value-bearing string; emails are replaced in
    place so a useful, non-sensitive exception class/reason can remain.
    """
    if any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS):
        return replacement, True
    redacted = _EMAIL_RE.sub(replacement, text)
    return redacted, redacted != text


def sanitize_identifier_label(value: Any) -> str:
    """Return ``value`` only when it is a plain, non-sensitive identifier."""
    if value is None:
        return "unknown"
    text = str(value)
    redacted, sensitive = _redact_sensitive_text(text)
    if sensitive or redacted != text or not _IDENTIFIER_RE.match(text):
        return "unknown"
    return text


def sanitize_label_value(value: Any, *, max_length: int = 64) -> str:
    """Normalize an arbitrary value into a bounded, secret-free label."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = _CONTROL_CHARS.sub("", str(value)).strip()
    redacted, sensitive = _redact_sensitive_text(text, replacement="redacted")
    if sensitive:
        return "redacted"
    text = redacted
    text = _ALLOWED_LABEL_CHARS.sub("_", text)
    text = text.strip("_")
    if not text:
        return "unknown"
    if len(text) > max_length:
        text = text[: max_length - 3].rstrip("_") + "..."
    return text


def sanitize_annotation(value: Any, *, max_length: int = 256) -> str:
    """Normalize a human-readable annotation without leaking secrets or PII."""
    if value is None:
        return ""
    text = _CONTROL_CHARS.sub(" ", str(value)).strip()
    text, _ = _redact_sensitive_text(text)
    if len(text) > max_length:
        text = text[: max_length - 3].rstrip() + "..."
    return text


def sanitize_exception_message(message: str, *, max_length: int = 512) -> str:
    """Strip controls, redact credentials/PII, and truncate an exception."""
    if not message:
        return ""
    text = _CONTROL_CHARS.sub(" ", message).strip()
    text, _ = _redact_sensitive_text(text)
    if len(text) > max_length:
        text = text[: max_length - 3].rstrip() + "..."
    return text


def sanitize_error(exc: BaseException, *, max_length: int = 512) -> str:
    """Return a sanitized, bounded ``Type: message`` exception string."""
    exc_type = type(exc).__name__
    message = sanitize_exception_message(str(exc), max_length=max_length)
    if not message:
        return exc_type
    return f"{exc_type}: {message}"


def safe_metadata_key(key: str) -> Optional[str]:
    """Return the key if safe to persist in audit/span metadata, else None."""
    if not key or _is_secret_key(key):
        return None
    return sanitize_label_value(key, max_length=64)
