from __future__ import annotations

from dataclasses import dataclass, field, replace

from fastapi import Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from cygnus.governance.audience_bindings import (
    audience_filter_from_binding,
    load_audience_conflict_provider_data,
)
from cygnus.governance.review_assignments import load_review_assignments
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
    resolve_object_type,
)
from cygnus.review.intake import (
    PressureIntakeRecord,
    compile_pressure_proposal_bundles,
)
from cygnus.review.briefing import OwnerState
from cygnus.review.service import ProposalBundle
from cygnus.review.source_blindness import (
    SourceFailureObservation,
    build_source_failure_observations,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    GovernanceAudienceBinding,
    GovernancePropagation,
    GovernancePublication,
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
    review_assignment_count: int = 0
    uncompiled_signal_count: int = 0
    uncompiled_signal_types: tuple[str, ...] = field(default_factory=tuple)
    audience_conflict_count: int = 0


async def _load_source_failure_impacts(
    db: AsyncSession,
    *,
    error_sources: tuple[Source, ...],
    linked_pages: tuple[WikiPage, ...],
    wiki_scope: ColumnElement[bool] | None,
) -> tuple[SourceFailureObservation, ...]:
    if not linked_pages:
        return build_source_failure_observations(error_sources, ())

    linked_page_ids = tuple(page.id for page in linked_pages)
    binding_statement = (
        select(GovernanceAudienceBinding)
        .join(WikiPage, WikiPage.id == GovernanceAudienceBinding.page_id)
        .where(
            GovernanceAudienceBinding.page_id.in_(linked_page_ids),
            GovernanceAudienceBinding.lifecycle_state == "active",
        )
    )
    if wiki_scope is not None:
        binding_statement = binding_statement.where(wiki_scope)
    binding_statement = binding_statement.order_by(
        GovernanceAudienceBinding.page_id,
        GovernanceAudienceBinding.object_ref,
        GovernanceAudienceBinding.channel,
        GovernanceAudienceBinding.binding_key,
    )
    audience_bindings = tuple(
        (await db.execute(binding_statement)).scalars().all()
    )

    governed_page_ids = tuple(
        page.id
        for page in linked_pages
        if resolve_object_type(page.knowledge_type_slugs) is not None
    )
    latest_publications: tuple[GovernancePublication, ...] = ()
    propagations: tuple[GovernancePropagation, ...] = ()
    if governed_page_ids:
        ranked_publications = (
            select(
                GovernancePublication.id.label("publication_id"),
                func.row_number()
                .over(
                    partition_by=GovernancePublication.page_id,
                    order_by=(
                        GovernancePublication.published_at.desc(),
                        GovernancePublication.id.desc(),
                    ),
                )
                .label("position"),
            )
            .where(GovernancePublication.page_id.in_(governed_page_ids))
            .subquery()
        )
        latest_publication_statement = (
            select(GovernancePublication)
            .join(
                ranked_publications,
                ranked_publications.c.publication_id == GovernancePublication.id,
            )
            .where(ranked_publications.c.position == 1)
            .order_by(GovernancePublication.page_id)
        )
        latest_publications = tuple(
            (await db.execute(latest_publication_statement)).scalars().all()
        )
        if latest_publications:
            publication_ids = tuple(
                publication.id for publication in latest_publications
            )
            propagation_statement = (
                select(GovernancePropagation)
                .where(GovernancePropagation.publication_id.in_(publication_ids))
                .order_by(
                    GovernancePropagation.publication_id,
                    GovernancePropagation.surface_id,
                )
            )
            propagations = tuple(
                (await db.execute(propagation_statement)).scalars().all()
            )

    return build_source_failure_observations(
        error_sources,
        linked_pages,
        audience_bindings=audience_bindings,
        publications=latest_publications,
        propagations=propagations,
    )


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
    assignment_by_signal_id = await load_review_assignments(
        db,
        tuple(signal.id for signal in governance_signals),
    )
    missing_assignment_refs = tuple(
        signal.signal_ref
        for signal in governance_signals
        if signal.id not in assignment_by_signal_id
    )
    if missing_assignment_refs:
        raise RuntimeError(
            "durable review assignments are missing for governance signals: "
            + ", ".join(missing_assignment_refs)
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
    review_bundle_list: list[ProposalBundle] = []
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
        assignment = assignment_by_signal_id[signal.id]
        base_pressure_record = governance_signal_to_pressure_record(
            signal,
            audience_filter=audience_override,
        )
        compiled_bundle = compile_pressure_proposal_bundles((base_pressure_record,))[0]
        pressure_record_list.append(
            replace(base_pressure_record, queue_owner=assignment.owner_ref)
        )
        review_bundle_list.append(
            replace(
                compiled_bundle,
                signal=replace(
                    compiled_bundle.signal,
                    queue_owner=assignment.owner_ref,
                ),
                owner_state=OwnerState(assignment.lifecycle_state),
                assignment_trace_ref=f"review-assignment:{assignment.id}",
                assignment_version=assignment.version,
            )
        )
        compiled_signals.append(signal)
    pressure_records = tuple(pressure_record_list)
    review_bundles = tuple(review_bundle_list)
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

    source_observations = await _load_source_failure_impacts(
        db,
        error_sources=error_sources,
        linked_pages=linked_pages,
        wiki_scope=wiki_scope,
    )
    return GovernanceReadSnapshot(
        knowledge=knowledge,
        source_observations=source_observations,
        visible_source_count=visible_source_count,
        review_bundles=review_bundles,
        pressure_records=pressure_records,
        governance_signals=governance_signals,
        review_assignment_count=len(assignment_by_signal_id),
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
