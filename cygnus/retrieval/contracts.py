from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from cygnus.evidence.records import FreshnessState

_TOKEN_RE = re.compile(r"[a-z0-9]+")


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
    has_fresh = False
    for state in states:
        if state is FreshnessState.STALE:
            return FreshnessState.STALE
        if state is FreshnessState.FRESH:
            has_fresh = True
    return FreshnessState.FRESH if has_fresh else FreshnessState.UNKNOWN


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
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicationRecord:
    channel: str
    publication_state: str

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "publication_state": self.publication_state,
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
class SourceTrace:
    object_id: str
    version: int
    freshness: FreshnessState
    evidence_refs: tuple[SourceTraceEvidenceRef, ...] = field(default_factory=tuple)
    publication_records: tuple[PublicationRecord, ...] = field(default_factory=tuple)
    review_history_summary: tuple[ReviewHistoryItem, ...] = field(default_factory=tuple)
    blind_spots: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "version": self.version,
            "freshness": self.freshness.value,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "publication_records": [item.to_dict() for item in self.publication_records],
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
            "evidence_count": len(self.evidence_refs),
            "blind_spots": list(self.blind_spots),
        }
