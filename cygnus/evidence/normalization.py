from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence


@dataclass(frozen=True, slots=True, kw_only=True)
class RawEvidenceInput:
    source_type: EvidenceSourceType
    source_ref: str
    title: str
    content: str
    visibility: Visibility
    brand: str | None = None
    product_line: str | None = None
    plan: str | None = None
    region: str | None = None
    language: str | None = None
    product_version: str | None = None
    freshness_state: FreshnessState = FreshnessState.UNKNOWN
    updated_at: str | None = None



def normalize_evidence(evidence_id: str, raw: RawEvidenceInput) -> SupportEvidence:
    audience = AudienceFilter(
        visibility=raw.visibility,
        brands=(raw.brand,) if raw.brand else (),
        product_lines=(raw.product_line,) if raw.product_line else (),
        plans=(raw.plan,) if raw.plan else (),
        regions=(raw.region,) if raw.region else (),
        languages=(raw.language,) if raw.language else (),
        product_versions=(raw.product_version,) if raw.product_version else (),
    )
    return SupportEvidence(
        evidence_id=evidence_id,
        source_type=raw.source_type,
        source_ref=raw.source_ref,
        title=raw.title,
        content=raw.content,
        audience_filter=audience,
        product_lines=(raw.product_line,) if raw.product_line else (),
        plans=(raw.plan,) if raw.plan else (),
        regions=(raw.region,) if raw.region else (),
        languages=(raw.language,) if raw.language else (),
        product_versions=(raw.product_version,) if raw.product_version else (),
        freshness_state=raw.freshness_state,
        updated_at=raw.updated_at,
        tags=_derive_tags(raw),
    )



def _derive_tags(raw: RawEvidenceInput) -> tuple[str, ...]:
    tags: list[str] = [raw.source_type.value]
    for value in (raw.product_line, raw.plan, raw.region, raw.language, raw.product_version):
        if value:
            tags.append(value)
    return tuple(tags)



def normalize_payload(evidence_id: str, payload: dict[str, Any]) -> SupportEvidence:
    raw = RawEvidenceInput(
        source_type=EvidenceSourceType(payload["source_type"]),
        source_ref=payload["source_ref"],
        title=payload["title"],
        content=payload["content"],
        visibility=Visibility(payload["visibility"]),
        brand=payload.get("brand"),
        product_line=payload.get("product_line"),
        plan=payload.get("plan"),
        region=payload.get("region"),
        language=payload.get("language"),
        product_version=payload.get("product_version"),
        freshness_state=FreshnessState(payload.get("freshness_state", FreshnessState.UNKNOWN.value)),
        updated_at=payload.get("updated_at"),
    )
    return normalize_evidence(evidence_id, raw)
