"""Substrate-backed knowledge provider for Cygnus governed retrieval.

Maps internalized substrate truth (wiki pages + ready sources) into typed
support knowledge objects and support evidence, so the governed
object/evidence plane reads DB-held truth instead of sample fixtures
(CYG-97, session-seam Slice 0).

Ownership:
- this module serves retrieval truth, not runtime entry wiring
- wiki-page state itself stays owned by the runtime wiki services; this
  module only projects it into the governed object/evidence contracts

Degraded-mapping rules (explicit, so nothing is silently fabricated):
- only wiki pages whose knowledge-type slugs name a support object type are
  projected into the object plane; every other page remains wiki-substrate
  truth reachable through the wiki/KB tool surface
- typed fields that markdown cannot supply are filled from title/summary/
  content excerpts and every projected object is tagged ``substrate-mapped``
- audience is internal-global until audience modeling lands in substrate
- freshness is the source's explicit attestation (UNKNOWN when missing or
  expired); it is never inferred from content or age
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict

from cygnus.domain.audience import AudienceContext, AudienceFilter, Visibility
from cygnus.domain.lifecycle import LifecycleState
from cygnus.domain.objects import (
    AnswerCard,
    EscalationRoute,
    governed_object_ref,
    KnowledgeObject,
    KnowledgeObjectType,
    KnownIssuePage,
    PolicyRule,
    TroubleshootingFlow,
)
from cygnus.evidence.freshness import resolve_source_freshness
from cygnus.evidence.records import EvidenceSourceType, SupportEvidence
from cygnus.retrieval.contracts import (
    PersistedDeliveryRecord,
    PersistedObjectTruth,
    PublicationRecord,
    ReviewHistoryItem,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from cygnus.runtime.database.models import (
        GovernanceAudienceBinding,
        Source,
        WikiPage,
    )

RESERVED_WIKI_SLUGS = ("_index", "_log", "_hot")

_OBJECT_TYPE_BY_SLUG: dict[str, KnowledgeObjectType] = {}
for _object_type in KnowledgeObjectType:
    _OBJECT_TYPE_BY_SLUG[_object_type.value] = _object_type
    _OBJECT_TYPE_BY_SLUG[_object_type.value.replace("_", "-")] = _object_type
_OBJECT_TYPE_BY_SLUG["known-issue"] = KnowledgeObjectType.KNOWN_ISSUE_PAGE

_EVIDENCE_TYPE_BY_SLUG: dict[str, EvidenceSourceType] = {}
for _evidence_type in EvidenceSourceType:
    _EVIDENCE_TYPE_BY_SLUG[_evidence_type.value] = _evidence_type
    _EVIDENCE_TYPE_BY_SLUG[_evidence_type.value.replace("_", "-")] = _evidence_type
_EVIDENCE_TYPE_BY_SLUG.update(
    {
        "sop": EvidenceSourceType.INTERNAL_SOP,
        "faq": EvidenceSourceType.HELP_CENTER,
        "help": EvidenceSourceType.HELP_CENTER,
        "ticket": EvidenceSourceType.RESOLVED_TICKET,
        "release-notes": EvidenceSourceType.RELEASE_NOTE,
        "incident": EvidenceSourceType.INCIDENT_UPDATE,
        "chat": EvidenceSourceType.CHAT_TRANSCRIPT,
    }
)

# Wiki maturity -> governed lifecycle. seed/developing content is not yet
# governed truth of record; mature/evergreen is what the wiki actually serves.
_LIFECYCLE_BY_WIKI_STATUS = {
    "seed": LifecycleState.DRAFT,
    "developing": LifecycleState.DRAFT,
    "mature": LifecycleState.PUBLISHED,
    "evergreen": LifecycleState.PUBLISHED,
}

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")

_INTERNAL_GLOBAL = AudienceFilter(visibility=Visibility.INTERNAL)

SUBSTRATE_MAPPED_TAG = "substrate-mapped"

_EXCERPT_LIMIT = 800


@dataclass(frozen=True, slots=True)
class SubstrateKnowledgeSnapshot:
    """Immutable request-scoped projection of governed database truth."""

    objects: tuple[KnowledgeObject, ...]
    evidence: tuple[SupportEvidence, ...]
    persisted_truth_by_object: Mapping[str, PersistedObjectTruth] = field(
        default_factory=dict
    )
    delivery_records_by_object: Mapping[str, tuple[PersistedDeliveryRecord, ...]] = (
        field(default_factory=dict)
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "persisted_truth_by_object",
            dict(self.persisted_truth_by_object),
        )
        object.__setattr__(
            self,
            "delivery_records_by_object",
            {
                object_id: tuple(records)
                for object_id, records in self.delivery_records_by_object.items()
            },
        )

    @staticmethod
    def _record_is_delivery_eligible(
        record: PersistedDeliveryRecord,
        truth: PersistedObjectTruth,
        *,
        channel: str,
        audience_context: AudienceContext,
    ) -> bool:
        return (
            record.channel == channel
            and record.page_id == truth.page_id
            and truth.source_evidence_complete
            and record.audience_filter.matches(audience_context)
            and record.is_current_synced(
                page_version=truth.page_version,
                approval_version=truth.approval_version,
                binding_version=record.binding_version,
            )
            and any(
                record.matches_publication_record(publication)
                for publication in truth.publication_records
            )
        )

    def delivery_verdict(
        self,
        object_id: str,
        *,
        channel: str,
        audience_context: AudienceContext,
    ) -> bool:
        """Whether one exact channel may expose current governed content.

        This is the single read-side signed-ack predicate. It deliberately
        returns false for fixture/unbound truth, missing context, held bindings,
        stale versions, pending deliveries, or any digest mismatch.
        """
        if audience_context is None or not channel.strip():
            return False
        truth = self.persisted_truth_by_object.get(object_id)
        if truth is None or object_id != f"ko-page-{truth.page_id}":
            return False
        return any(
            self._record_is_delivery_eligible(
                record,
                truth,
                channel=channel,
                audience_context=audience_context,
            )
            for record in self.delivery_records_by_object.get(object_id, ())
        )

    def evidence_delivery_verdict(
        self,
        evidence_id: str,
        *,
        channel: str,
        audience_context: AudienceContext,
    ) -> bool:
        """Whether one binding-scoped evidence record is safe for this channel."""
        if audience_context is None or not channel.strip() or not evidence_id.strip():
            return False
        for object_id, records in self.delivery_records_by_object.items():
            truth = self.persisted_truth_by_object.get(object_id)
            if truth is None or object_id != f"ko-page-{truth.page_id}":
                continue
            for record in records:
                if not evidence_id.endswith(f"-binding-{record.binding_key}"):
                    continue
                if self._record_is_delivery_eligible(
                    record,
                    truth,
                    channel=channel,
                    audience_context=audience_context,
                ):
                    return True
        return False


class _KnowledgeObjectBase(TypedDict):
    """Common typed fields shared by every projected knowledge object."""

    object_id: str
    title: str
    summary: str
    lifecycle_state: LifecycleState
    supported_audiences: tuple[AudienceFilter, ...]
    evidence_ids: tuple[str, ...]
    tags: tuple[str, ...]


def _excerpt(text: str | None, *, limit: int = _EXCERPT_LIMIT) -> str:
    return (text or "").strip()[:limit]


def _first_paragraph(content_md: str | None) -> str:
    for raw_block in (content_md or "").split("\n\n"):
        block = raw_block.strip()
        if not block or _HEADING_RE.match(block):
            continue
        return " ".join(line.strip() for line in block.splitlines())
    return ""


def _list_items(content_md: str | None) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _LIST_ITEM_RE.finditer(content_md or ""))


def _summary_for(page: "WikiPage") -> str:
    return (
        (page.summary or "").strip() or _first_paragraph(page.content_md) or page.title
    )


def resolve_object_type(
    knowledge_type_slugs: Iterable[str] | None,
) -> KnowledgeObjectType | None:
    """First knowledge-type slug that names a support object type, if any."""
    for slug in knowledge_type_slugs or ():
        object_type = _OBJECT_TYPE_BY_SLUG.get(slug.strip().lower())
        if object_type is not None:
            return object_type
    return None


def wiki_page_to_knowledge_object(
    page: "WikiPage",
    *,
    evidence_ids: tuple[str, ...] = (),
    supported_audiences: tuple[AudienceFilter, ...] = (_INTERNAL_GLOBAL,),
) -> KnowledgeObject | None:
    """Project one eligible wiki page into a typed support knowledge object.

    Reserved, source-backed, orphaned, and non-support pages stay wiki-substrate
    truth and are never exposed through the governed object plane.
    """
    if (
        page.orphaned
        or page.slug in RESERVED_WIKI_SLUGS
        or page.slug.startswith("source/")
    ):
        return None
    object_type = resolve_object_type(page.knowledge_type_slugs)
    if object_type is None:
        return None

    summary = _summary_for(page)
    steps = _list_items(page.content_md)
    tags = tuple(
        dict.fromkeys([*(page.knowledge_type_slugs or ()), SUBSTRATE_MAPPED_TAG])
    )
    base: _KnowledgeObjectBase = {
        "object_id": governed_object_ref(page.id),
        "title": page.title,
        "summary": summary,
        "lifecycle_state": _LIFECYCLE_BY_WIKI_STATUS.get(
            page.status or "seed", LifecycleState.DRAFT
        ),
        "supported_audiences": supported_audiences,
        "evidence_ids": evidence_ids,
        "tags": tags,
    }

    if object_type is KnowledgeObjectType.ANSWER_CARD:
        return AnswerCard(
            **base,
            question=page.title,
            canonical_answer=_excerpt(page.content_md) or summary,
        )
    if object_type is KnowledgeObjectType.TROUBLESHOOTING_FLOW:
        return TroubleshootingFlow(
            **base,
            problem_statement=summary,
            steps=steps or (f"See wiki page: {page.slug}",),
        )
    if object_type is KnowledgeObjectType.POLICY_RULE:
        return PolicyRule(
            **base,
            rule_domain=(page.knowledge_type_slugs or ("policy",))[0],
            rule_statement=summary,
            authority_source=f"wiki:{page.slug}",
        )
    if object_type is KnowledgeObjectType.KNOWN_ISSUE_PAGE:
        return KnownIssuePage(
            **base,
            issue_summary=summary,
            workaround=_excerpt(page.content_md) or summary,
            issue_status=page.status or "seed",
        )
    return EscalationRoute(
        **base,
        trigger_conditions=steps or (summary,),
        destination_team="unassigned",
    )


def source_to_support_evidence(
    source: "Source",
    *,
    knowledge_type_slug: str | None = None,
    evidence_id: str | None = None,
    audience_filter: AudienceFilter = _INTERNAL_GLOBAL,
) -> SupportEvidence:
    """Project one ready source document into one audience-scoped record."""
    slug = (knowledge_type_slug or "").strip().lower()
    tags = tuple(item for item in (slug, SUBSTRATE_MAPPED_TAG) if item)
    attested_at = getattr(source, "freshness_attested_at", None)
    source_language = getattr(source, "language", None)
    effective_audience = audience_filter
    if audience_filter is _INTERNAL_GLOBAL:
        effective_audience = AudienceFilter(
            visibility=Visibility.INTERNAL,
            languages=(source_language,) if source_language else (),
        )
    return SupportEvidence(
        evidence_id=evidence_id or f"ev-src-{source.id}",
        source_type=_EVIDENCE_TYPE_BY_SLUG.get(slug, EvidenceSourceType.INTERNAL_SOP),
        source_ref=source.url or source.file_name or f"source:{source.id}",
        title=(source.title or "").strip() or source.file_name or f"source:{source.id}",
        content=_excerpt(source.full_text) or (source.title or f"source:{source.id}"),
        audience_filter=effective_audience,
        tags=tags,
        freshness_state=resolve_source_freshness(source),
        updated_at=(
            attested_at.isoformat()
            if attested_at is not None
            else source.updated_at.isoformat()
            if source.updated_at
            else None
        ),
    )


def build_substrate_snapshot(
    pages: Iterable["WikiPage"],
    sources: Iterable["Source"],
    *,
    knowledge_type_slug_by_id: Mapping[Any, str] | None = None,
) -> SubstrateKnowledgeSnapshot:
    """Pure projection of wiki pages + ready sources into the governed plane."""
    slug_by_id = knowledge_type_slug_by_id or {}

    evidence: list[SupportEvidence] = []
    for source in sources:
        if source.status != "ready":
            continue
        evidence.append(
            source_to_support_evidence(
                source,
                knowledge_type_slug=slug_by_id.get(source.knowledge_type_id),
            )
        )
    known_evidence_ids = {item.evidence_id for item in evidence}

    objects: list[KnowledgeObject] = []
    for page in pages:
        evidence_ids = tuple(
            candidate
            for source_id in (page.source_ids or ())
            if (candidate := f"ev-src-{source_id}") in known_evidence_ids
        )
        object_ = wiki_page_to_knowledge_object(page, evidence_ids=evidence_ids)
        if object_ is not None and object_.lifecycle_state is LifecycleState.PUBLISHED:
            objects.append(object_)

    return SubstrateKnowledgeSnapshot(objects=tuple(objects), evidence=tuple(evidence))


def _audience_filter_from_binding(binding: Any) -> AudienceFilter:
    return AudienceFilter(
        visibility=Visibility(binding.visibility),
        brands=tuple(binding.brands or ()),
        product_lines=tuple(binding.product_lines or ()),
        plans=tuple(binding.plans or ()),
        regions=tuple(binding.regions or ()),
        languages=tuple(binding.languages or ()),
        product_versions=tuple(binding.product_versions or ()),
    )


def _latest_by_page(publications: Iterable[Any]) -> dict[Any, Any]:
    """Select latest publication before validating it; never fall back stale."""
    selected: dict[Any, Any] = {}
    for publication in publications:
        prior = selected.get(publication.page_id)
        if prior is None or (
            publication.published_at,
            str(publication.id),
        ) > (
            prior.published_at,
            str(prior.id),
        ):
            selected[publication.page_id] = publication
    return selected


def _approval_matches_current_publication(
    publication: Any,
    *,
    page: Any,
    approval_event: Any | None,
) -> bool:
    if approval_event is None or approval_event.event_type not in {
        "approved",
        "state_imported",
    }:
        return False
    payload = approval_event.payload or {}
    return (
        payload.get("page_id") == str(page.id)
        and payload.get("page_version") == page.version
        and payload.get("approval_digest") == publication.approval_digest
    )


def _binding_version_map(raw: object) -> dict[str, int]:
    values = raw if isinstance(raw, list) else ()
    result: dict[str, int] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        key, version = item.get("binding_key"), item.get("version")
        if isinstance(key, str) and isinstance(version, int) and version >= 1:
            result[key] = version
    return result


def _binding_is_referenced(binding: GovernanceAudienceBinding, raw: object) -> bool:
    """Match one persisted binding to the canonical publish-binding payload."""
    values = raw if isinstance(raw, list) else ()
    expected_audience = _audience_filter_from_binding(binding).to_dict()
    return any(
        isinstance(item, dict)
        and item.get("channel") == binding.channel
        and item.get("audience_filter") == expected_audience
        for item in values
    )


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _truth_token(
    *,
    page: Any,
    publication: Any,
    approval_version: int,
    bindings: Iterable[Any],
    records: Iterable[PersistedDeliveryRecord],
    source_ids: Iterable[Any],
    sources: Iterable[Any],
    source_evidence_complete: bool,
) -> str:
    payload = {
        "page_id": str(page.id),
        "page_version": page.version,
        "publication_id": str(publication.id),
        "approval_digest": publication.approval_digest,
        "approval_version": approval_version,
        "scope_digest": publication.scope_digest,
        "source_ids": sorted(str(source_id) for source_id in source_ids),
        "source_evidence_complete": source_evidence_complete,
        "bindings": sorted(
            (binding.binding_key, binding.version, binding.lifecycle_state)
            for binding in bindings
        ),
        "deliveries": sorted(
            (
                record.page_id,
                record.publication_id,
                record.propagation_id,
                record.delivery_id,
                record.channel,
                record.binding_key,
                record.binding_version,
                record.propagation_status,
                record.delivery_status,
                record.propagation_digest,
                record.desired_digest,
                record.acknowledged_digest,
                record.expected_page_version,
                record.acknowledged_version,
                record.expected_approval_version,
            )
            for record in records
        ),
        "sources": sorted(
            (
                str(source.id),
                source.status,
                resolve_source_freshness(source).value,
                _datetime_value(getattr(source, "freshness_attested_at", None)),
                _datetime_value(getattr(source, "freshness_expires_at", None)),
                source.updated_at.isoformat()
                if source.updated_at is not None
                else None,
            )
            for source in sources
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def load_substrate_snapshot(
    session: "AsyncSession",
    *,
    visible_pages: Iterable[Any] | None = None,
    visible_sources: Iterable[Any] | None = None,
    visible_knowledge_types: Iterable[Any] | None = None,
) -> SubstrateKnowledgeSnapshot:
    """Load current DB-backed governed truth, failing closed on every drift.

    Router dependencies pass permission-filtered substrate rows; direct callers
    without them load the whole database only for trusted maintenance paths.
    """
    from sqlalchemy import select

    from cygnus.runtime.database.models import (
        GovernanceAudienceBinding,
        GovernanceLedgerEvent,
        GovernancePropagation,
        GovernancePropagationDelivery,
        GovernancePublication,
        KnowledgeType,
        Source,
        WikiPage,
    )

    pages = (
        tuple(visible_pages)
        if visible_pages is not None
        else tuple((await session.execute(select(WikiPage))).scalars().all())
    )
    sources = (
        tuple(visible_sources)
        if visible_sources is not None
        else tuple((await session.execute(select(Source))).scalars().all())
    )
    knowledge_types = (
        tuple(visible_knowledge_types)
        if visible_knowledge_types is not None
        else tuple((await session.execute(select(KnowledgeType))).scalars().all())
    )
    publications = tuple(
        (await session.execute(select(GovernancePublication))).scalars().all()
    )
    bindings = tuple(
        (await session.execute(select(GovernanceAudienceBinding))).scalars().all()
    )
    propagations = tuple(
        (await session.execute(select(GovernancePropagation))).scalars().all()
    )
    deliveries = tuple(
        (await session.execute(select(GovernancePropagationDelivery))).scalars().all()
    )
    approval_events = tuple(
        (await session.execute(select(GovernanceLedgerEvent))).scalars().all()
    )

    source_by_id = {source.id: source for source in sources}
    slug_by_id = {item.id: item.slug for item in knowledge_types}
    latest_publication_by_page = _latest_by_page(publications)
    approval_by_id = {event.id: event for event in approval_events}
    bindings_by_page: dict[Any, list[Any]] = defaultdict(list)
    for binding in bindings:
        bindings_by_page[binding.page_id].append(binding)
    propagation_by_publication_channel = {
        (propagation.publication_id, propagation.surface_id): propagation
        for propagation in propagations
    }
    delivery_by_propagation = {
        delivery.propagation_id: delivery for delivery in deliveries
    }

    objects: list[KnowledgeObject] = []
    evidence: list[SupportEvidence] = []
    truth_by_object: dict[str, PersistedObjectTruth] = {}
    delivery_records_by_object: dict[str, tuple[PersistedDeliveryRecord, ...]] = {}

    for page in pages:
        publication = latest_publication_by_page.get(page.id)
        object_id = governed_object_ref(page.id)
        if publication is None:
            continue
        approval_event = approval_by_id.get(publication.approval_event_id)
        if approval_event is None:
            continue
        # The latest publication must itself be valid; selecting an older one
        # would resurrect withdrawn/superseded content.
        if (
            publication.page_id != page.id
            or publication.object_ref != object_id
            or publication.object_version != page.version
            or publication.effective_object_status not in {"mature", "evergreen"}
            or page.status not in {"mature", "evergreen"}
            or not _approval_matches_current_publication(
                publication,
                page=page,
                approval_event=approval_event,
            )
        ):
            continue

        active_bindings = tuple(
            binding
            for binding in bindings_by_page.get(page.id, ())
            if binding.object_ref == object_id and binding.lifecycle_state == "active"
        )
        if not active_bindings:
            continue

        records: list[PersistedDeliveryRecord] = []
        publication_records: list[PublicationRecord] = []
        for binding in active_bindings:
            propagation = propagation_by_publication_channel.get(
                (publication.id, binding.channel)
            )
            if propagation is None or not _binding_is_referenced(
                binding, propagation.binding_refs
            ):
                continue
            delivery = delivery_by_propagation.get(propagation.id)
            expected_versions = (
                _binding_version_map(delivery.expected_binding_versions)
                if delivery is not None
                else {}
            )
            if (
                delivery is None
                or delivery.publication_id != publication.id
                or delivery.surface_id != binding.channel
                or expected_versions.get(binding.binding_key) != binding.version
            ):
                continue
            records.append(
                PersistedDeliveryRecord(
                    page_id=str(page.id),
                    publication_id=str(publication.id),
                    propagation_id=str(propagation.id),
                    delivery_id=str(delivery.id),
                    channel=binding.channel,
                    binding_key=binding.binding_key,
                    binding_version=binding.version,
                    audience_filter=_audience_filter_from_binding(binding),
                    propagation_status=propagation.status,
                    delivery_status=delivery.status,
                    propagation_digest=propagation.desired_digest,
                    desired_digest=delivery.desired_digest,
                    acknowledged_digest=delivery.acknowledged_digest,
                    expected_page_version=delivery.expected_page_version,
                    expected_approval_version=delivery.expected_approval_version,
                    acknowledged_version=delivery.acknowledged_version,
                )
            )
            publication_records.append(
                PublicationRecord(
                    channel=binding.channel,
                    publication_state=propagation.status,
                    publication_ref=str(publication.id),
                    propagation_refs=(str(propagation.id),),
                    delivery_refs=(str(delivery.id),),
                )
            )
        if not records:
            continue

        page_source_ids = tuple(dict.fromkeys(page.source_ids or ()))
        page_sources = tuple(
            source_by_id[source_id]
            for source_id in page_source_ids
            if source_id in source_by_id
        )
        source_evidence_complete = (
            bool(page_source_ids)
            and len(page_sources) == len(page_source_ids)
            and all(source.status == "ready" for source in page_sources)
        )
        evidence_ids: list[str] = []
        page_evidence: list[SupportEvidence] = []
        for record in records:
            for source in page_sources:
                if source.status != "ready":
                    continue
                evidence_id = (
                    f"ev-page-{page.id}-src-{source.id}-binding-{record.binding_key}"
                )
                evidence_ids.append(evidence_id)
                page_evidence.append(
                    source_to_support_evidence(
                        source,
                        knowledge_type_slug=slug_by_id.get(source.knowledge_type_id),
                        evidence_id=evidence_id,
                        audience_filter=record.audience_filter,
                    )
                )
        object_ = wiki_page_to_knowledge_object(
            page,
            evidence_ids=tuple(evidence_ids),
            supported_audiences=tuple(
                dict.fromkeys(record.audience_filter for record in records)
            ),
        )
        if object_ is None:
            continue
        evidence.extend(page_evidence)
        truth = PersistedObjectTruth(
            page_id=str(page.id),
            approval_version=approval_event.sequence,
            page_version=page.version,
            source_evidence_complete=source_evidence_complete,
            truth_token=_truth_token(
                page=page,
                publication=publication,
                bindings=active_bindings,
                approval_version=approval_event.sequence,
                records=records,
                source_ids=page_source_ids,
                sources=page_sources,
                source_evidence_complete=source_evidence_complete,
            ),
            publication_records=tuple(publication_records),
            review_history_summary=(
                ReviewHistoryItem(stage="approval", status="approved"),
                ReviewHistoryItem(stage="publication", status="published"),
            ),
        )
        objects.append(object_)
        truth_by_object[object_id] = truth
        delivery_records_by_object[object_id] = tuple(records)

    return SubstrateKnowledgeSnapshot(
        objects=tuple(objects),
        evidence=tuple(evidence),
        persisted_truth_by_object=truth_by_object,
        delivery_records_by_object=delivery_records_by_object,
    )
