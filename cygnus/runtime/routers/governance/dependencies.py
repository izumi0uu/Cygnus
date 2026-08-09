from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from cygnus.governance.audience_bindings import (
    audience_filter_from_binding,
    load_audience_conflict_provider_data,
)
from cygnus.governance.signals import (
    governance_signal_to_pressure_record,
    list_governance_signals,
)

from cygnus.publish import (
    durable_publication_result,
    latest_publication_for_object,
    list_publication_propagations,
)
from cygnus.retrieval.substrate_provider import (
    SubstrateKnowledgeSnapshot,
    build_substrate_snapshot,
)
from cygnus.review.intake import (
    PressureIntakeRecord,
    compile_pressure_proposal_bundles,
)
from cygnus.review.service import ProposalBundle
from cygnus.review.source_blindness import (
    SourceFailureObservation,
    build_source_failure_observations,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    GovernanceAudienceBinding,
    GovernanceSignal,
    KnowledgeType,
    Source,
    WikiPage,
)
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
    pressure_records: tuple[PressureIntakeRecord, ...] = field(default_factory=tuple)
    governance_signals: tuple[GovernanceSignal, ...] = field(default_factory=tuple)
    uncompiled_signal_count: int = 0
    uncompiled_signal_types: tuple[str, ...] = field(default_factory=tuple)
    audience_conflict_count: int = 0


async def load_governance_knowledge_snapshot(
    current_user: Employee,
    db: AsyncSession,
) -> SubstrateKnowledgeSnapshot:
    """Load only permission-filtered object and evidence truth."""
    wiki_scope = build_wiki_scope_clause(current_user)
    document_scope = build_document_scope_clause(current_user)

    wiki_stmt = select(WikiPage).order_by(WikiPage.slug)
    if wiki_scope is not None:
        wiki_stmt = wiki_stmt.where(wiki_scope)
    visible_pages = tuple((await db.execute(wiki_stmt)).scalars().all())

    ready_source_stmt = (
        select(Source).where(Source.status == "ready").order_by(Source.id)
    )
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
                    select(KnowledgeType).where(
                        KnowledgeType.id.in_(knowledge_type_ids)
                    )
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
    return build_substrate_snapshot(
        visible_pages,
        ready_sources,
        knowledge_type_slug_by_id=knowledge_type_slug_by_id,
    )


async def get_governance_read_snapshot(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GovernanceReadSnapshot:
    """Load only rows visible to the authenticated user's governed scopes."""
    wiki_scope = build_wiki_scope_clause(current_user)
    document_scope = build_document_scope_clause(current_user)
    knowledge = await load_governance_knowledge_snapshot(current_user, db)

    source_count_stmt = select(func.count(Source.id))
    if document_scope is not None:
        source_count_stmt = source_count_stmt.where(document_scope)
    visible_source_count = int((await db.execute(source_count_stmt)).scalar_one())

    error_source_stmt = (
        select(Source).where(Source.status == "error").order_by(Source.id)
    )
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

    governance_signals = await list_governance_signals(
        db,
        current_user=current_user,
    )
    binding_refs = tuple(
        signal.audience_binding_ref
        for signal in governance_signals
        if signal.audience_filter is None and signal.audience_binding_ref is not None
    )
    binding_by_key = {}
    if binding_refs:
        binding_statement = (
            select(GovernanceAudienceBinding)
            .join(
                WikiPage,
                WikiPage.id == GovernanceAudienceBinding.page_id,
            )
            .where(GovernanceAudienceBinding.binding_key.in_(binding_refs))
        )
        if wiki_scope is not None:
            binding_statement = binding_statement.where(wiki_scope)
        binding_rows = tuple((await db.execute(binding_statement)).scalars().all())
        binding_by_key = {row.binding_key: row for row in binding_rows}

    pressure_record_list: list[PressureIntakeRecord] = []
    compiled_signals: list[GovernanceSignal] = []
    for signal in governance_signals:
        audience_override = None
        if signal.audience_filter is None:
            binding = binding_by_key.get(signal.audience_binding_ref or "")
            if (
                binding is None
                or binding.page_id != signal.page_id
                or binding.object_ref != signal.object_ref
            ):
                continue
            audience_override = audience_filter_from_binding(binding)
        pressure_record_list.append(
            governance_signal_to_pressure_record(
                signal,
                audience_filter=audience_override,
            )
        )
        compiled_signals.append(signal)
    pressure_records = tuple(pressure_record_list)
    review_bundles = compile_pressure_proposal_bundles(pressure_records)
    compiled_signal_ids = {signal.id for signal in compiled_signals}
    uncompiled_signal_types = tuple(
        dict.fromkeys(
            signal.signal_type
            for signal in governance_signals
            if signal.id not in compiled_signal_ids
        )
    )
    audience_conflicts = await load_audience_conflict_provider_data(
        db,
        page_scope_clause=wiki_scope,
    )

    return GovernanceReadSnapshot(
        knowledge=knowledge,
        source_observations=build_source_failure_observations(
            error_sources, linked_pages
        ),
        visible_source_count=visible_source_count,
        review_bundles=review_bundles,
        pressure_records=pressure_records,
        governance_signals=governance_signals,
        uncompiled_signal_count=len(governance_signals) - len(compiled_signals),
        uncompiled_signal_types=uncompiled_signal_types,
        audience_conflict_count=len(audience_conflicts.conflicts),
    )


async def get_durable_publish_projection(
    object_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | None:
    """Load restart-durable publish truth for one knowledge object."""
    publication = await latest_publication_for_object(db, object_id)
    if publication is None:
        return None
    propagations = await list_publication_propagations(db, publication.id)
    return durable_publication_result(
        publication,
        propagations=propagations,
        replayed=False,
    )


async def get_governance_knowledge_snapshot(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubstrateKnowledgeSnapshot:
    """Expose the scoped knowledge plane without compiling unrelated governance state."""
    return await load_governance_knowledge_snapshot(current_user, db)
