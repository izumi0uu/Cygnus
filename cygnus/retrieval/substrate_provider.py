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
- freshness stays UNKNOWN until freshness signals are wired
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.lifecycle import LifecycleState
from cygnus.domain.objects import (
    AnswerCard,
    EscalationRoute,
    KnowledgeObject,
    KnowledgeObjectType,
    KnownIssuePage,
    PolicyRule,
    TroubleshootingFlow,
)
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from cygnus.runtime.database.models import Source, WikiPage

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
    """Immutable projection of substrate truth into the governed plane."""

    objects: tuple[KnowledgeObject, ...]
    evidence: tuple[SupportEvidence, ...]


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
    return (page.summary or "").strip() or _first_paragraph(page.content_md) or page.title


def resolve_object_type(knowledge_type_slugs: Iterable[str] | None) -> KnowledgeObjectType | None:
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
) -> KnowledgeObject | None:
    """Project one wiki page into a typed support knowledge object.

    Returns None when the page does not declare a support object type —
    such pages stay wiki-substrate truth and are not governed objects.
    """
    object_type = resolve_object_type(page.knowledge_type_slugs)
    if object_type is None:
        return None

    summary = _summary_for(page)
    steps = _list_items(page.content_md)
    tags = tuple(dict.fromkeys([*(page.knowledge_type_slugs or ()), SUBSTRATE_MAPPED_TAG]))
    base: dict[str, object] = {
        "object_id": f"ko-{page.slug}",
        "title": page.title,
        "summary": summary,
        "lifecycle_state": _LIFECYCLE_BY_WIKI_STATUS.get(page.status or "seed", LifecycleState.DRAFT),
        "supported_audiences": (_INTERNAL_GLOBAL,),
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
) -> SupportEvidence:
    """Project one ready source document into a support evidence record."""
    slug = (knowledge_type_slug or "").strip().lower()
    tags = tuple(item for item in (slug, SUBSTRATE_MAPPED_TAG) if item)
    return SupportEvidence(
        evidence_id=f"ev-src-{source.id}",
        source_type=_EVIDENCE_TYPE_BY_SLUG.get(slug, EvidenceSourceType.INTERNAL_SOP),
        source_ref=source.url or source.file_name or f"source:{source.id}",
        title=(source.title or "").strip() or source.file_name or f"source:{source.id}",
        content=_excerpt(source.full_text) or (source.title or f"source:{source.id}"),
        audience_filter=_INTERNAL_GLOBAL,
        tags=tags,
        freshness_state=FreshnessState.UNKNOWN,
        updated_at=source.updated_at.isoformat() if source.updated_at else None,
    )


def build_substrate_snapshot(
    pages: Iterable["WikiPage"],
    sources: Iterable["Source"],
    *,
    knowledge_type_slug_by_id: dict[object, str] | None = None,
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
        if page.orphaned or page.slug in RESERVED_WIKI_SLUGS or page.slug.startswith("source/"):
            continue
        evidence_ids = tuple(
            candidate
            for source_id in (page.source_ids or ())
            if (candidate := f"ev-src-{source_id}") in known_evidence_ids
        )
        object_ = wiki_page_to_knowledge_object(page, evidence_ids=evidence_ids)
        if object_ is not None:
            objects.append(object_)

    return SubstrateKnowledgeSnapshot(objects=tuple(objects), evidence=tuple(evidence))


async def load_substrate_snapshot(session: "AsyncSession") -> SubstrateKnowledgeSnapshot:
    """Load the governed object/evidence snapshot from substrate truth."""
    from sqlalchemy import select

    from cygnus.runtime.database.models import KnowledgeType, Source, WikiPage

    pages = (await session.execute(select(WikiPage))).scalars().all()
    sources = (await session.execute(select(Source).where(Source.status == "ready"))).scalars().all()
    knowledge_types = (await session.execute(select(KnowledgeType))).scalars().all()
    slug_by_id = {item.id: item.slug for item in knowledge_types}

    return build_substrate_snapshot(pages, sources, knowledge_type_slug_by_id=slug_by_id)
