"""Canonical Source language tag contract shared by API, compiler, and retrieval.

The language tag on a ``Source`` is EXPLICIT user input, persisted in
normalized (trimmed, lowercase) form. It is never auto-detected from document
content and never silently overwritten. This module is the single place that
defines the supported set and validates/normalizes source language input; the
API create/update contracts, the MRP compiler, and retrieval projections all
use it so a tag accepted anywhere means the same tag everywhere.

The permissive page normalizer in ``wiki_service.normalize_page_language``
remains the canonical *page identity* normalizer (it falls back to ``en`` for
reserved/catalog pages that have no source). This module owns the *source*
contract: strict, supported-set validation.
"""

from __future__ import annotations

from typing import Optional

#: Product locales Cygnus actually serves. Extend here (plus the
#: ``sources.language`` migration check, if one is ever added) when a new
#: locale ships; nothing else needs to change.
SUPPORTED_SOURCE_LANGUAGES: frozenset[str] = frozenset({"en", "zh"})

#: Language existing sources are migrated to (20260812_08_source_language) and
#: the value non-source write paths fall back to. Mirrors
#: ``wiki_service.DEFAULT_PAGE_LANGUAGE``.
DEFAULT_SOURCE_LANGUAGE = "en"

#: Matches the String(10) columns on ``sources.language`` / ``wiki_pages.language``.
_LANGUAGE_LENGTH_LIMIT = 10

#: Human-readable option list for error messages.
_LANGUAGE_OPTIONS_TEXT = ", ".join(sorted(SUPPORTED_SOURCE_LANGUAGES))


class SourceLanguageError(ValueError):
    """Raised when a source language tag is missing, malformed, or unsupported.

    Callers (HTTP routes, pipeline entry points) surface this as a 400-style
    rejection BEFORE any lasting mutation.
    """


def normalize_source_language(language: Optional[str]) -> str:
    """Normalize and validate one source language tag.

    - ``None`` / blank / non-string → :class:`SourceLanguageError`
    - trims and lowercases (``" ZH "`` → ``"zh"``)
    - rejects anything longer than the column limit
    - rejects any tag outside :data:`SUPPORTED_SOURCE_LANGUAGES`

    Returns the canonical tag, guaranteed to be a supported member.
    """
    if language is None:
        raise SourceLanguageError(
            f"language is required and must be one of: {_LANGUAGE_OPTIONS_TEXT}"
        )
    if not isinstance(language, str):
        raise SourceLanguageError(f"language must be one of: {_LANGUAGE_OPTIONS_TEXT}")
    normalized = language.strip().lower()
    if not normalized:
        raise SourceLanguageError(
            f"language is required and must be one of: {_LANGUAGE_OPTIONS_TEXT}"
        )
    if len(normalized) > _LANGUAGE_LENGTH_LIMIT:
        raise SourceLanguageError(
            f"language {normalized!r} is too long "
            f"(max {_LANGUAGE_LENGTH_LIMIT} characters)"
        )
    if normalized not in SUPPORTED_SOURCE_LANGUAGES:
        raise SourceLanguageError(
            f"language {normalized!r} is not supported; must be one of: "
            f"{_LANGUAGE_OPTIONS_TEXT}"
        )
    return normalized


def resolve_source_language(source: object) -> str:
    """Resolve the persisted language tag from a Source-like object.

    Returns the normalized, supported tag that pipeline phases must write
    canonical pages under. The tag is read straight from the persisted source
    — never auto-detected from document content. A missing/blank attribute
    (legacy callers, test doubles, pre-migration objects) falls back to
    :data:`DEFAULT_SOURCE_LANGUAGE`; a present-but-invalid tag raises
    :class:`SourceLanguageError` so a corrupt value can never silently write
    pages under the wrong canonical identity.
    """
    raw = getattr(source, "language", None)
    if not raw:
        return DEFAULT_SOURCE_LANGUAGE
    return normalize_source_language(raw)
