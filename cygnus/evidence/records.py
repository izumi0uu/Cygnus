from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter


class EvidenceSourceType(str, Enum):
    HELP_CENTER = "help_center"
    INTERNAL_SOP = "internal_sop"
    RESOLVED_TICKET = "resolved_ticket"
    RELEASE_NOTE = "release_note"
    INCIDENT_UPDATE = "incident_update"
    CHAT_TRANSCRIPT = "chat_transcript"


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"



def _normalize(values: Iterable[str] | None, *, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    out: list[str] = []
    for raw in values:
        value = raw.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        out.append(value)
    return tuple(out)


@dataclass(frozen=True, slots=True, kw_only=True)
class SupportEvidence:
    evidence_id: str
    source_type: EvidenceSourceType
    source_ref: str
    title: str
    content: str
    audience_filter: AudienceFilter
    product_lines: tuple[str, ...] = field(default_factory=tuple)
    plans: tuple[str, ...] = field(default_factory=tuple)
    regions: tuple[str, ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    product_versions: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    freshness_state: FreshnessState = FreshnessState.UNKNOWN
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be blank")
        if not self.source_ref.strip():
            raise ValueError("source_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.content.strip():
            raise ValueError("content must not be blank")
        object.__setattr__(self, "product_lines", _normalize(self.product_lines, label="product line"))
        object.__setattr__(self, "plans", _normalize(self.plans, label="plan"))
        object.__setattr__(self, "regions", _normalize(self.regions, label="region"))
        object.__setattr__(self, "languages", _normalize(self.languages, label="language"))
        object.__setattr__(self, "product_versions", _normalize(self.product_versions, label="product version"))
        object.__setattr__(self, "tags", _normalize(self.tags, label="tag"))
        if self.updated_at is not None and not self.updated_at.strip():
            raise ValueError("updated_at must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type.value,
            "source_ref": self.source_ref,
            "title": self.title,
            "content": self.content,
            "audience_filter": self.audience_filter.to_dict(),
            "product_lines": list(self.product_lines),
            "plans": list(self.plans),
            "regions": list(self.regions),
            "languages": list(self.languages),
            "product_versions": list(self.product_versions),
            "tags": list(self.tags),
            "freshness_state": self.freshness_state.value,
            "updated_at": self.updated_at,
        }
