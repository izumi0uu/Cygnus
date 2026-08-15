from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cygnus.domain.audience import AudienceContext, audience_context_allowed
from cygnus.domain.objects import AnswerCard, KnowledgeObject
from cygnus.evidence.freshness import rollup_freshness
from cygnus.evidence.records import FreshnessState, SupportEvidence
from cygnus.retrieval.contracts import (
    PersistedDeliveryRecord,
    PersistedObjectTruth,
    PublicationRecord,
    ReviewHistoryItem,
    SourceTrace,
    SourceTraceEvidenceRef,
    excerpt_ref_for,
    slugify,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceLink:
    evidence_id: str
    scope: str


def collect_evidence_links(
    object_: KnowledgeObject,
    *,
    audience_context: AudienceContext | None = None,
) -> tuple[EvidenceLink, ...]:
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
            if audience_context is not None and not audience_context_allowed(
                audience_context, (variant.audience_filter,)
            ):
                continue
            label = variant.label or f"variant-{index}"
            for evidence_id in variant.evidence_ids:
                add(evidence_id, f"variant:{slugify(label)}")

    return tuple(links)


class SourceTraceResolver:
    """Resolve exact object traces without a title/slug lookup escape hatch."""

    def __init__(
        self,
        objects: Iterable[KnowledgeObject],
        evidence: Iterable[SupportEvidence],
        persisted_truth_by_object: Mapping[str, PersistedObjectTruth] | None = None,
        delivery_records_by_object: Mapping[str, tuple[PersistedDeliveryRecord, ...]]
        | None = None,
    ) -> None:
        self._objects = tuple(objects)
        self._object_by_id = {item.object_id: item for item in self._objects}
        self._evidence_by_id = {item.evidence_id: item for item in evidence}
        self._truth_by_object = dict(persisted_truth_by_object or {})
        self._delivery_records_by_object = {
            object_id: tuple(records)
            for object_id, records in (delivery_records_by_object or {}).items()
        }

    def find_object(self, object_id: str) -> KnowledgeObject | None:
        """Return one object only by its immutable object ID."""
        return self._object_by_id.get(object_id)

    def get_trace(
        self,
        object_id: str,
        *,
        audience_context: AudienceContext | None = None,
        channel: str | None = None,
    ) -> SourceTrace | None:
        object_ = self._object_by_id.get(object_id)
        if object_ is None:
            return None
        if object_id in self._truth_by_object and (
            audience_context is None or channel is None
        ):
            return None
        return self.build_trace_for_object(
            object_, audience_context=audience_context, channel=channel
        )

    def build_trace_for_object(
        self,
        object_: KnowledgeObject,
        *,
        audience_context: AudienceContext | None = None,
        channel: str | None = None,
    ) -> SourceTrace:
        truth = self._truth_by_object.get(object_.object_id)
        evidence_refs: list[SourceTraceEvidenceRef] = []
        freshness_states: list[FreshnessState] = []
        blind_spots: list[str] = []
        records = self._delivery_records_by_object.get(object_.object_id, ())
        matching_records = tuple(
            record
            for record in records
            if channel is not None
            and record.channel == channel
            and audience_context is not None
            and record.audience_filter.matches(audience_context)
        )

        if truth is not None and object_.object_id != f"ko-page-{truth.page_id}":
            return SourceTrace(
                object_id=object_.object_id,
                version=truth.page_version,
                truth_token=truth.truth_token,
                freshness=FreshnessState.UNKNOWN,
                review_history_summary=truth.review_history_summary,
                blind_spots=("object_identity_mismatch",),
            )
        if truth is not None and (audience_context is None or channel is None):
            return SourceTrace(
                object_id=object_.object_id,
                version=truth.page_version,
                truth_token=truth.truth_token,
                freshness=FreshnessState.UNKNOWN,
                review_history_summary=truth.review_history_summary,
                blind_spots=("audience_context_and_channel_required",),
            )
        if truth is not None and not matching_records:
            return SourceTrace(
                object_id=object_.object_id,
                version=truth.page_version,
                truth_token=truth.truth_token,
                freshness=FreshnessState.UNKNOWN,
                review_history_summary=truth.review_history_summary,
                blind_spots=("channel_or_audience_not_bound",),
            )

        trace_records = matching_records
        publication_records: tuple[PublicationRecord, ...]
        if truth is not None:
            current_records = tuple(
                record
                for record in matching_records
                if record.page_id == truth.page_id
                and record.is_current_synced(
                    page_version=truth.page_version,
                    approval_version=truth.approval_version,
                    binding_version=record.binding_version,
                )
            )
            if not current_records:
                return SourceTrace(
                    object_id=object_.object_id,
                    version=truth.page_version,
                    truth_token=truth.truth_token,
                    freshness=FreshnessState.UNKNOWN,
                    review_history_summary=truth.review_history_summary,
                    blind_spots=("signed_delivery_not_current",),
                )

            publication_records = tuple(
                dict.fromkeys(
                    publication
                    for publication in truth.publication_records
                    if any(
                        record.matches_publication_record(publication)
                        for record in current_records
                    )
                )
            )
            trace_records = tuple(
                record
                for record in current_records
                if any(
                    record.matches_publication_record(publication)
                    for publication in publication_records
                )
            )
            if not trace_records:
                return SourceTrace(
                    object_id=object_.object_id,
                    version=truth.page_version,
                    truth_token=truth.truth_token,
                    freshness=FreshnessState.UNKNOWN,
                    review_history_summary=truth.review_history_summary,
                    blind_spots=("publication_delivery_trace_mismatch",),
                )
            if not truth.source_evidence_complete:
                return SourceTrace(
                    object_id=object_.object_id,
                    version=truth.page_version,
                    truth_token=truth.truth_token,
                    freshness=FreshnessState.UNKNOWN,
                    publication_records=publication_records,
                    review_history_summary=truth.review_history_summary,
                    blind_spots=("source_evidence_incomplete",),
                )
        else:
            publication_records = _publication_records_for(object_, version=1)

        links = collect_evidence_links(object_, audience_context=audience_context)
        if not links:
            blind_spots.append("object_has_no_evidence")

        for link in links:
            evidence = self._evidence_by_id.get(link.evidence_id)
            if trace_records and not any(
                link.evidence_id.endswith(f"-binding-{record.binding_key}")
                for record in trace_records
            ):
                continue
            if evidence is None:
                blind_spots.append(f"missing_evidence:{link.evidence_id}")
                continue
            if audience_context is not None and not audience_context_allowed(
                audience_context, (evidence.audience_filter,)
            ):
                # Same-source records may be present for other audience
                # bindings. Omit them without exposing their identity.
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
                    revision=evidence.revision,
                )
            )

        if links and not evidence_refs:
            blind_spots.append("object_has_no_readable_evidence")
        freshness = rollup_freshness(freshness_states)
        if any(ref.freshness is FreshnessState.STALE for ref in evidence_refs):
            blind_spots.append("stale_evidence_present")

        return SourceTrace(
            object_id=object_.object_id,
            version=truth.page_version if truth is not None else 1,
            truth_token=truth.truth_token if truth is not None else None,
            freshness=freshness,
            evidence_refs=tuple(evidence_refs),
            publication_records=publication_records,
            review_history_summary=(
                truth.review_history_summary
                if truth is not None
                else (
                    ReviewHistoryItem(
                        stage="lifecycle", status=object_.lifecycle_state.value
                    ),
                )
            ),
            blind_spots=tuple(blind_spots),
        )


def _publication_records_for(
    object_: KnowledgeObject, *, version: int = 1
) -> tuple[PublicationRecord, ...]:
    """Fixture-only fallback for explicit in-memory evaluation objects."""
    channels = getattr(object_, "publish_targets", ())
    return tuple(
        PublicationRecord(
            channel=channel,
            publication_state=object_.lifecycle_state.value,
            publication_ref=f"fixture-pub:{object_.object_id}:{channel}:v{version}",
            propagation_refs=(
                f"fixture-prop:{object_.object_id}:{channel}:v{version}",
            ),
            delivery_refs=(),
        )
        for channel in channels
    )
