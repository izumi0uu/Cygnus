from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.retrieval.substrate_provider import (
    SubstrateKnowledgeSnapshot,
    build_substrate_snapshot,
)
from cygnus.review.service import ProposalBundle
from cygnus.review.source_blindness import (
    SourceFailureObservation,
    build_source_failure_observations,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee, KnowledgeType, Source, WikiPage
from cygnus.runtime.services.auth_service import get_current_user
from cygnus.runtime.services.permission_engine import (
    build_document_scope_clause,
    build_wiki_scope_clause,
)


@dataclass(frozen=True, slots=True)
class GovernanceReadSnapshot:
    """Request-scoped governed read model for frontend governance surfaces."""

    knowledge: SubstrateKnowledgeSnapshot
    source_observations: tuple[SourceFailureObservation, ...]
    visible_source_count: int
    review_bundles: tuple[ProposalBundle, ...] = field(default_factory=tuple)


async def get_governance_read_snapshot(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GovernanceReadSnapshot:
    """Load only rows visible to the authenticated user's Wiki and Source scopes."""
    wiki_scope = build_wiki_scope_clause(current_user)
    document_scope = build_document_scope_clause(current_user)

    wiki_stmt = select(WikiPage).order_by(WikiPage.slug)
    if wiki_scope is not None:
        wiki_stmt = wiki_stmt.where(wiki_scope)
    visible_pages = tuple((await db.execute(wiki_stmt)).scalars().all())

    ready_source_stmt = select(Source).where(Source.status == "ready").order_by(Source.id)
    if document_scope is not None:
        ready_source_stmt = ready_source_stmt.where(document_scope)
    ready_sources = tuple((await db.execute(ready_source_stmt)).scalars().all())

    knowledge_type_ids = {
        source.knowledge_type_id
        for source in ready_sources
        if source.knowledge_type_id is not None
    }
    if knowledge_type_ids:
        knowledge_types = tuple(
            (
                await db.execute(
                    select(KnowledgeType).where(KnowledgeType.id.in_(knowledge_type_ids))
                )
            )
            .scalars()
            .all()
        )
    else:
        knowledge_types = ()
    knowledge_type_slug_by_id: dict[object, str] = {
        item.id: item.slug for item in knowledge_types
    }
    knowledge = build_substrate_snapshot(
        visible_pages,
        ready_sources,
        knowledge_type_slug_by_id=knowledge_type_slug_by_id,
    )

    source_count_stmt = select(func.count(Source.id))
    if document_scope is not None:
        source_count_stmt = source_count_stmt.where(document_scope)
    visible_source_count = int((await db.execute(source_count_stmt)).scalar_one())

    error_source_stmt = select(Source).where(Source.status == "error").order_by(Source.id)
    if document_scope is not None:
        error_source_stmt = error_source_stmt.where(document_scope)
    error_sources = tuple((await db.execute(error_source_stmt)).scalars().all())

    linked_pages: tuple[WikiPage, ...] = ()
    if error_sources:
        linked_page_stmt = select(WikiPage).where(
            or_(
                *(
                    WikiPage.source_ids.any(source.id)  # pyright: ignore[reportArgumentType]
                    for source in error_sources
                )
            )
        )
        if wiki_scope is not None:
            linked_page_stmt = linked_page_stmt.where(wiki_scope)
        linked_pages = tuple((await db.execute(linked_page_stmt)).scalars().all())

    return GovernanceReadSnapshot(
        knowledge=knowledge,
        source_observations=build_source_failure_observations(error_sources, linked_pages),
        visible_source_count=visible_source_count,
        review_bundles=(),
    )


async def get_governance_knowledge_snapshot(
    snapshot: GovernanceReadSnapshot = Depends(get_governance_read_snapshot),
) -> SubstrateKnowledgeSnapshot:
    """Expose the scoped knowledge plane to graph and traceability endpoints."""
    return snapshot.knowledge
