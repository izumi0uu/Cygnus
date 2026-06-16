from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.domain.objects import AnswerCard, KnowledgeObject
from cygnus.evidence.records import FreshnessState, SupportEvidence
from cygnus.retrieval.contracts import (
    PublicationRecord,
    ReviewHistoryItem,
    SourceTrace,
    SourceTraceEvidenceRef,
    excerpt_ref_for,
    freshness_rollup,
    slugify,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceLink:
    evidence_id: str
    scope: str



def collect_evidence_links(object_: KnowledgeObject) -> tuple[EvidenceLink, ...]:
    links: list[EvidenceLink] = []
    seen: set[tuple[str, str]] = set()

    def add(evidence_id: str, scope: str) -> None:
        key = (evidence_id, scope)
        if key in seen:
            return
        seen.add(key)
        links.append(EvidenceLink(evidence_id=evidence_id, scope=scope))

    for evidence_id in object_.evidence_ids:
        add(evidence_id, "base")

    if isinstance(object_, AnswerCard):
        for index, variant in enumerate(object_.audience_variants, start=1):
            label = variant.label or f"variant-{index}"
            for evidence_id in variant.evidence_ids:
                add(evidence_id, f"variant:{slugify(label)}")

    return tuple(links)


class SourceTraceResolver:
    def __init__(
        self,
        objects: Iterable[KnowledgeObject],
        evidence: Iterable[SupportEvidence],
    ) -> None:
        self._objects = tuple(objects)
        self._object_by_id = {item.object_id: item for item in self._objects}
        self._object_by_slug = {slugify(item.title): item for item in self._objects}
        self._evidence_by_id = {item.evidence_id: item for item in evidence}

    def find_object(self, id_or_slug: str) -> KnowledgeObject | None:
        return self._object_by_id.get(id_or_slug) or self._object_by_slug.get(id_or_slug)

    def get_trace(self, object_id: str) -> SourceTrace | None:
        object_ = self._object_by_id.get(object_id)
        if object_ is None:
            return None
        return self.build_trace_for_object(object_)

    def build_trace_for_object(self, object_: KnowledgeObject) -> SourceTrace:
        evidence_refs: list[SourceTraceEvidenceRef] = []
        freshness_states: list[FreshnessState] = []
        blind_spots: list[str] = []

        links = collect_evidence_links(object_)
        if not links:
            blind_spots.append("object_has_no_evidence")

        for link in links:
            evidence = self._evidence_by_id.get(link.evidence_id)
            if evidence is None:
                blind_spots.append(f"missing_evidence:{link.evidence_id}")
                continue

            freshness_states.append(evidence.freshness_state)
            evidence_refs.append(
                SourceTraceEvidenceRef(
                    evidence_id=evidence.evidence_id,
                    scope=link.scope,
                    source_type=evidence.source_type.value,
                    source_ref=evidence.source_ref,
                    title=evidence.title,
                    freshness=evidence.freshness_state,
                    excerpt_ref=excerpt_ref_for(evidence.evidence_id, evidence.content),
                    updated_at=evidence.updated_at,
                )
            )

        freshness = freshness_rollup(freshness_states)
        if any(ref.freshness is FreshnessState.STALE for ref in evidence_refs):
            blind_spots.append("stale_evidence_present")

        return SourceTrace(
            object_id=object_.object_id,
            version=1,
            freshness=freshness,
            evidence_refs=tuple(evidence_refs),
            publication_records=_publication_records_for(object_),
            review_history_summary=(
                ReviewHistoryItem(stage="lifecycle", status=object_.lifecycle_state.value),
            ),
            blind_spots=tuple(blind_spots),
        )



def _publication_records_for(object_: KnowledgeObject) -> tuple[PublicationRecord, ...]:
    channels = getattr(object_, "publish_targets", ())
    return tuple(
        PublicationRecord(
            channel=channel,
            publication_state=object_.lifecycle_state.value,
        )
        for channel in channels
    )
