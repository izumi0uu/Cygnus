from __future__ import annotations

from typing import Any, Iterable

from cygnus.evidence.records import EvidenceSourceType, SupportEvidence
from cygnus.retrieval.contracts import EvidenceHit, excerpt_ref_for, keyword_score, tokenize


class EvidenceIndex:
    def __init__(self, evidence: Iterable[SupportEvidence]) -> None:
        self._evidence = tuple(evidence)

    def search(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> tuple[EvidenceHit, ...]:
        query_tokens = tokenize(query)
        filters = filters or {}
        ranked: list[tuple[float, EvidenceHit]] = []

        for evidence in self._evidence:
            if not _matches_filters(evidence, filters):
                continue

            score = keyword_score(
                query_tokens,
                evidence.title,
                evidence.content,
                evidence.source_ref,
                " ".join(evidence.tags),
            )
            if score <= 0:
                continue

            ranked.append(
                (
                    score,
                    EvidenceHit(
                        evidence_id=evidence.evidence_id,
                        title=evidence.title,
                        source_type=evidence.source_type.value,
                        source_ref=evidence.source_ref,
                        excerpt_ref=excerpt_ref_for(evidence.evidence_id, evidence.content),
                        freshness=evidence.freshness_state,
                        confidence=score,
                        snippet=evidence.content[:160],
                    ),
                )
            )

        ranked.sort(key=lambda item: (-item[0], item[1].title))
        return tuple(hit for _, hit in ranked[:limit])

    def all(self) -> tuple[SupportEvidence, ...]:
        return self._evidence



def _matches_filters(evidence: SupportEvidence, filters: dict[str, Any]) -> bool:
    source_type = filters.get("source_type")
    if source_type is not None and evidence.source_type is not EvidenceSourceType(source_type):
        return False

    filter_pairs = (
        ("product_line", evidence.product_lines),
        ("plan", evidence.plans),
        ("region", evidence.regions),
        ("language", evidence.languages),
        ("product_version", evidence.product_versions),
    )

    for filter_name, actual_values in filter_pairs:
        expected = filters.get(filter_name)
        if expected is None:
            continue
        if expected not in actual_values:
            return False

    return True
