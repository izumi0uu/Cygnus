from __future__ import annotations

from typing import Iterable

from cygnus.domain.audience import AudienceContext
from cygnus.domain.lifecycle import LifecycleState
from cygnus.domain.objects import (
    AnswerCard,
    EscalationRoute,
    KnowledgeObject,
    KnownIssuePage,
    PolicyRule,
    TroubleshootingFlow,
)
from cygnus.evidence.records import SupportEvidence
from cygnus.retrieval.contracts import KnowledgeObjectHit, keyword_score, slugify, tokenize
from cygnus.retrieval.source_trace import SourceTraceResolver


class KnowledgeObjectIndex:
    def __init__(
        self,
        objects: Iterable[KnowledgeObject],
        evidence: Iterable[SupportEvidence],
    ) -> None:
        self._objects = tuple(objects)
        self._trace_resolver = SourceTraceResolver(self._objects, evidence)

    def search(
        self,
        *,
        query: str,
        audience_context: AudienceContext | None = None,
        object_types: Iterable[str] | None = None,
        limit: int = 10,
        include_unpublished: bool = False,
    ) -> tuple[KnowledgeObjectHit, ...]:
        query_tokens = tokenize(query)
        allowed_types = {item.strip() for item in object_types or () if item.strip()}
        ranked: list[tuple[float, KnowledgeObjectHit]] = []

        for object_ in self._objects:
            if allowed_types and object_.object_type.value not in allowed_types:
                continue
            if not include_unpublished and object_.lifecycle_state is not LifecycleState.PUBLISHED:
                continue

            audience_match = _resolve_audience_match(object_, audience_context)
            if audience_match is None:
                continue

            score = keyword_score(query_tokens, *_searchable_fields(object_))
            if score <= 0:
                continue

            trace = self._trace_resolver.build_trace_for_object(object_)
            ranked.append(
                (
                    score,
                    KnowledgeObjectHit(
                        object_id=object_.object_id,
                        slug=slugify(object_.title),
                        object_type=object_.object_type.value,
                        title=object_.title,
                        audience_match=audience_match,
                        freshness=trace.freshness,
                        publication_status=object_.lifecycle_state.value,
                        snippet=_snippet_for(object_),
                        trace_ref=f"trace:{object_.object_id}",
                    ),
                )
            )

        ranked.sort(key=lambda item: (-item[0], item[1].title))
        return tuple(hit for _, hit in ranked[:limit])

    def read(self, id_or_slug: str) -> KnowledgeObject | None:
        return self._trace_resolver.find_object(id_or_slug)

    @property
    def trace_resolver(self) -> SourceTraceResolver:
        return self._trace_resolver



def _resolve_audience_match(
    object_: KnowledgeObject,
    audience_context: AudienceContext | None,
) -> str | None:
    if audience_context is None:
        return "partial"

    if not object_.supported_audiences:
        return "partial"

    matched_global = False
    for audience_filter in object_.supported_audiences:
        if not audience_filter.matches(audience_context):
            continue
        if audience_filter.is_global:
            matched_global = True
            continue
        return "exact"

    if matched_global:
        return "partial"
    return None



def _searchable_fields(object_: KnowledgeObject) -> tuple[str, ...]:
    fields = [object_.title, object_.summary, " ".join(object_.tags)]

    if isinstance(object_, AnswerCard):
        fields.extend(
            [
                object_.question,
                object_.canonical_answer,
                " ".join(object_.constraints),
                " ".join(variant.content for variant in object_.audience_variants),
                " ".join((variant.label or "") for variant in object_.audience_variants),
            ]
        )
    elif isinstance(object_, TroubleshootingFlow):
        fields.extend(
            [
                object_.problem_statement,
                " ".join(object_.prerequisites),
                " ".join(object_.steps),
                " ".join(object_.branching_conditions),
                " ".join(object_.stop_conditions),
            ]
        )
    elif isinstance(object_, PolicyRule):
        fields.extend(
            [
                object_.rule_domain,
                object_.rule_statement,
                " ".join(object_.effective_conditions),
                " ".join(object_.exceptions),
            ]
        )
    elif isinstance(object_, KnownIssuePage):
        fields.extend(
            [
                object_.issue_summary,
                object_.workaround,
                object_.issue_status,
                " ".join(object_.affected_products),
                " ".join(object_.affected_versions),
            ]
        )
    elif isinstance(object_, EscalationRoute):
        fields.extend(
            [
                " ".join(object_.trigger_conditions),
                object_.destination_team,
                " ".join(object_.required_context),
                " ".join(object_.blocked_domains),
                object_.severity_hint or "",
            ]
        )

    return tuple(fields)



def _snippet_for(object_: KnowledgeObject) -> str:
    if isinstance(object_, AnswerCard):
        return object_.canonical_answer
    if isinstance(object_, TroubleshootingFlow):
        return object_.steps[0]
    if isinstance(object_, PolicyRule):
        return object_.rule_statement
    if isinstance(object_, KnownIssuePage):
        return object_.workaround
    if isinstance(object_, EscalationRoute):
        return object_.destination_team
    return object_.summary
