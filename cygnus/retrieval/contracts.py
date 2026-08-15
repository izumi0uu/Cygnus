from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from cygnus.domain.audience import AudienceContext, AudienceFilter
from cygnus.evidence.records import (
    EVIDENCE_INJECTION_WARNING,
    EVIDENCE_TRUST_CLASSIFICATION,
    FreshnessState,
)
from cygnus.substrate.agent_protocol import (
    SESSION_CONTRACT_VERSION,
    negotiate_session_contract_version,
)

# Read envelopes are schema-versioned with the shared session contract so tool
# outputs always echo the negotiated contract version (CYG-139).
RETRIEVAL_ENVELOPE_VERSION = SESSION_CONTRACT_VERSION

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _require_uuid_string(value: str, *, label: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise ValueError(f"{label} must be a canonical UUID")


def slugify(value: str) -> str:
    tokens = _TOKEN_RE.findall(value.lower())
    return "-".join(tokens) or "untitled"


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(value.lower()))


def keyword_score(query_tokens: tuple[str, ...], *fields: str) -> float:
    if not query_tokens:
        return 0.0

    haystacks = [field.lower() for field in fields if field.strip()]
    if not haystacks:
        return 0.0

    matched = 0
    for token in query_tokens:
        if any(token in haystack for haystack in haystacks):
            matched += 1

    return matched / len(query_tokens)


def excerpt_ref_for(identifier: str, content: str, *, max_chars: int = 160) -> str:
    return f"{identifier}:0-{min(len(content), max_chars)}"


def freshness_rollup(states: Iterable[FreshnessState]) -> FreshnessState:
    """Return FRESH only when every referenced source is explicitly fresh."""
    collected = tuple(states)
    if any(state is FreshnessState.STALE for state in collected):
        return FreshnessState.STALE
    if not collected or any(state is FreshnessState.UNKNOWN for state in collected):
        return FreshnessState.UNKNOWN
    return FreshnessState.FRESH


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceVerdict:
    """Caller identity plus the audience filter applied to one governed read.

    Every governed read envelope carries an audience verdict so the applied
    role/scope/filter and its outcome are never omitted (CYG-139).
    """

    role: str | None
    scope: str | None
    match: str
    visibility: str | None = None
    brand: str | None = None
    product_line: str | None = None
    plan: str | None = None
    region: str | None = None
    language: str | None = None
    product_version: str | None = None
    required: bool = True
    matched_audience: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.match not in {"exact", "partial", "none"}:
            raise ValueError("audience verdict match must be exact, partial, or none")
        for label, value in (
            ("role", self.role),
            ("scope", self.scope),
            ("visibility", self.visibility),
            ("brand", self.brand),
            ("product_line", self.product_line),
            ("plan", self.plan),
            ("region", self.region),
            ("language", self.language),
            ("product_version", self.product_version),
        ):
            if value is not None and not str(value).strip():
                raise ValueError(
                    f"audience verdict {label} must not be blank when provided"
                )
        if self.matched_audience is not None:
            object.__setattr__(self, "matched_audience", dict(self.matched_audience))

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "role": self.role,
            "scope": self.scope,
            "match": self.match,
            "required": self.required,
            "visibility": self.visibility,
            "brand": self.brand,
            "product_line": self.product_line,
            "plan": self.plan,
            "region": self.region,
            "language": self.language,
            "product_version": self.product_version,
        }
        if self.matched_audience is not None:
            payload["matched_audience"] = dict(self.matched_audience)
        return payload


def audience_verdict_for(
    audience_context: AudienceContext | None,
    *,
    role: str | None,
    scope: str | None,
    match: str,
    required: bool = True,
) -> AudienceVerdict:
    """Build the audience verdict for an applied context and match outcome."""
    return AudienceVerdict(
        role=role,
        scope=scope,
        match=match,
        visibility=(
            audience_context.visibility.value if audience_context is not None else None
        ),
        brand=audience_context.brand if audience_context is not None else None,
        product_line=(
            audience_context.product_line if audience_context is not None else None
        ),
        plan=audience_context.plan if audience_context is not None else None,
        region=audience_context.region if audience_context is not None else None,
        language=audience_context.language if audience_context is not None else None,
        product_version=(
            audience_context.product_version if audience_context is not None else None
        ),
        required=required,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AnswerabilityVerdict:
    """Whether the read output may be treated as an answer, and why."""

    answerable: bool
    reason: str
    codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("answerability reason must not be blank")
        object.__setattr__(self, "codes", tuple(self.codes))

    def to_dict(self) -> dict[str, object]:
        return {
            "answerable": self.answerable,
            "reason": self.reason,
            "codes": list(self.codes),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedReadEnvelope:
    """Typed schema-versioned envelope returned by every governed read.

    The envelope always carries the negotiated contract version, an audience
    verdict, and an answerability verdict; tool payloads live in ``data``.
    """

    status: str
    summary: str
    audience: AudienceVerdict
    answerability: AnswerabilityVerdict | None
    data: Mapping[str, Any]
    trace_ref: str | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    contract_version: str = RETRIEVAL_ENVELOPE_VERSION

    def __post_init__(self) -> None:
        if not self.status.strip():
            raise ValueError("envelope status must not be blank")
        if not self.summary.strip():
            raise ValueError("envelope summary must not be blank")
        negotiated = negotiate_session_contract_version(self.contract_version)
        object.__setattr__(self, "contract_version", negotiated)
        object.__setattr__(self, "data", dict(self.data))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "errors", tuple(self.errors))

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "status": self.status,
            "summary": self.summary,
            "audience": self.audience.to_dict(),
            "answerability": (
                self.answerability.to_dict() if self.answerability is not None else None
            ),
            "data": dict(self.data),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
        if self.trace_ref is not None:
            payload["trace_ref"] = self.trace_ref
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeObjectHit:
    object_id: str
    slug: str
    object_type: str
    title: str
    audience_match: str
    freshness: FreshnessState
    publication_status: str
    snippet: str
    trace_ref: str

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "slug": self.slug,
            "object_type": self.object_type,
            "title": self.title,
            "audience_match": self.audience_match,
            "freshness": self.freshness.value,
            "publication_status": self.publication_status,
            "snippet": self.snippet,
            "trace_ref": self.trace_ref,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceHit:
    evidence_id: str
    title: str
    source_type: str
    source_ref: str
    excerpt_ref: str
    freshness: FreshnessState
    confidence: float
    snippet: str
    revision: str | None = None
    captured_at: str | None = None
    trust_classification: str = EVIDENCE_TRUST_CLASSIFICATION
    injection_warning: str = EVIDENCE_INJECTION_WARNING

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "excerpt_ref": self.excerpt_ref,
            "freshness": self.freshness.value,
            "confidence": round(self.confidence, 3),
            "snippet": self.snippet,
            "revision": self.revision,
            "captured_at": self.captured_at,
            "provenance": {
                "source_ref": self.source_ref,
                "source_type": self.source_type,
                "captured_at": self.captured_at,
                "revision": self.revision,
            },
            "trust": {
                "classification": self.trust_classification,
                "injection_warning": self.injection_warning,
            },
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceTraceEvidenceRef:
    evidence_id: str
    scope: str
    source_type: str
    source_ref: str
    title: str
    freshness: FreshnessState
    excerpt_ref: str
    updated_at: str | None = None
    revision: str | None = None
    trust_classification: str = EVIDENCE_TRUST_CLASSIFICATION
    injection_warning: str = EVIDENCE_INJECTION_WARNING

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "scope": self.scope,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "title": self.title,
            "freshness": self.freshness.value,
            "excerpt_ref": self.excerpt_ref,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "provenance": {
                "source_ref": self.source_ref,
                "source_type": self.source_type,
                "captured_at": self.updated_at,
                "revision": self.revision,
            },
            "trust": {
                "classification": self.trust_classification,
                "injection_warning": self.injection_warning,
            },
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicationRecord:
    channel: str
    publication_state: str
    publication_ref: str
    propagation_refs: tuple[str, ...]
    delivery_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise ValueError("publication channel must not be blank")
        if not self.publication_ref.strip():
            raise ValueError("publication_ref must not be blank")
        for label, refs in (
            ("propagation_refs", self.propagation_refs),
            ("delivery_refs", self.delivery_refs),
        ):
            if any(not ref.strip() for ref in refs):
                raise ValueError(f"{label} must not contain blank refs")
        object.__setattr__(self, "propagation_refs", tuple(self.propagation_refs))
        object.__setattr__(self, "delivery_refs", tuple(self.delivery_refs))

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "publication_state": self.publication_state,
            "publication_ref": self.publication_ref,
            "propagation_refs": list(self.propagation_refs),
            "delivery_refs": list(self.delivery_refs),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewHistoryItem:
    stage: str
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PersistedObjectTruth:
    """Current durable publication/binding truth for one immutable object ID."""

    page_id: str
    page_version: int
    approval_version: int
    source_evidence_complete: bool
    truth_token: str
    publication_records: tuple[PublicationRecord, ...]
    review_history_summary: tuple[ReviewHistoryItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.page_id.strip():
            raise ValueError("persisted object truth page_id must not be blank")
        _require_uuid_string(self.page_id, label="persisted object truth page_id")
        if self.page_version < 1 or self.approval_version < 1:
            raise ValueError("persisted object truth versions must be positive")
        if not self.truth_token.strip():
            raise ValueError("persisted object truth token must not be blank")
        if not isinstance(self.source_evidence_complete, bool):
            raise ValueError("persisted source evidence completeness must be boolean")
        object.__setattr__(self, "publication_records", tuple(self.publication_records))
        object.__setattr__(
            self, "review_history_summary", tuple(self.review_history_summary)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PersistedDeliveryRecord:
    """One immutable propagation receipt projected into request-scoped truth.
    The caller never infers eligibility from an individual field. The snapshot
    evaluates this record against the current page, approval, and binding
    versions before exposing content.
    """

    page_id: str
    publication_id: str
    propagation_id: str
    delivery_id: str
    channel: str
    binding_key: str
    binding_version: int
    audience_filter: AudienceFilter
    propagation_status: str
    delivery_status: str
    propagation_digest: str | None
    desired_digest: str
    acknowledged_digest: str | None
    expected_page_version: int
    expected_approval_version: int
    acknowledged_version: int | None

    def __post_init__(self) -> None:
        for label, value in (
            ("page_id", self.page_id),
            ("publication_id", self.publication_id),
            ("propagation_id", self.propagation_id),
            ("delivery_id", self.delivery_id),
            ("channel", self.channel),
            ("binding_key", self.binding_key),
            ("desired_digest", self.desired_digest),
        ):
            if not value.strip():
                raise ValueError(f"persisted delivery {label} must not be blank")
        _require_uuid_string(self.page_id, label="persisted delivery page_id")
        if (
            self.binding_version < 1
            or self.expected_page_version < 1
            or self.expected_approval_version < 1
        ):
            raise ValueError("persisted delivery versions must be positive")

    def is_current_synced(
        self,
        *,
        page_version: int,
        approval_version: int,
        binding_version: int,
    ) -> bool:
        """True only for an exact signed ack of current page/binding truth."""
        return (
            self.propagation_status == "synced"
            and self.delivery_status == "synced"
            and self.propagation_digest == self.desired_digest
            and self.acknowledged_digest == self.desired_digest
            and self.expected_page_version == page_version
            and self.expected_approval_version == approval_version
            and self.acknowledged_version == page_version
            and self.binding_version == binding_version
        )

    def matches_publication_record(self, record: PublicationRecord) -> bool:
        """Whether a trace record names this exact durable delivery chain."""
        return (
            record.channel == self.channel
            and record.publication_state == self.propagation_status
            and record.publication_ref == self.publication_id
            and self.propagation_id in record.propagation_refs
            and self.delivery_id in record.delivery_refs
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceTrace:
    object_id: str
    version: int
    freshness: FreshnessState
    truth_token: str | None = None
    evidence_refs: tuple[SourceTraceEvidenceRef, ...] = field(default_factory=tuple)
    publication_records: tuple[PublicationRecord, ...] = field(default_factory=tuple)
    review_history_summary: tuple[ReviewHistoryItem, ...] = field(default_factory=tuple)
    blind_spots: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "version": self.version,
            "truth_token": self.truth_token,
            "freshness": self.freshness.value,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "publication_records": [
                item.to_dict() for item in self.publication_records
            ],
            "review_history_summary": [
                item.to_dict() for item in self.review_history_summary
            ],
            "blind_spots": list(self.blind_spots),
        }

    def summary(self) -> dict[str, object]:
        return {
            "trace_ref": f"trace:{self.object_id}",
            "version": self.version,
            "freshness": self.freshness.value,
            "truth_token": self.truth_token,
            "evidence_count": len(self.evidence_refs),
            "blind_spots": list(self.blind_spots),
        }
