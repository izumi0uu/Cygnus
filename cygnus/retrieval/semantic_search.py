"""Semantic retrieval queries for Cygnus knowledge and raw source search.

Ownership:
- wiki-page semantic search and raw-source chunk semantic search live here
- this module serves retrieval truth, while runtime/wiki services own page materialization and graph maintenance
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.ai.embedding_catalog import get_spec
from cygnus.runtime.ai.registry import ProviderRegistry
from cygnus.retrieval.source_chunks import search_source_chunks_semantic
from cygnus.runtime.database.models import WikiPage, get_embedding_model_for_dim
from cygnus.runtime.services.wiki_service import (
    HOT_SLUG,
    INDEX_SLUG,
    LOG_SLUG,
    _inverse_scope_filter_for_identity,
    _scope_filter,
    _scope_filter_for_identity,
)

async def search_pages_semantic(
    session: AsyncSession,
    query_embedding: list[float],
    top_k: int = 10,
    allowed_kt_slugs: Optional[list[str]] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    spec_id: Optional[str] = None,
    department_ids: Optional[list[uuid.UUID]] = None,
    project_ids: Optional[list[uuid.UUID]] = None,
    inverse_scope: bool = False,
    all_scopes: bool = False,
) -> list[tuple[WikiPage, float]]:
    """
    Cosine-similarity search over wiki page embeddings within a scope.

    Embeddings live in per-dimension tables (`wiki_page_embeddings_<dim>`).
    The active embedding model spec determines which table to query and which
    `model_spec_id` rows to filter to. Pass `spec_id` explicitly to override —
    only used by tests and internal tooling.

    Scope behaviour:
      - If `department_ids` or `project_ids` is given: returns pages from
        global + user's departments + user's workspaces (MCP read path).
      - If `inverse_scope=True`: returns pages OUTSIDE that scope (other
        departments, workspaces the user isn't a member of). Used to surface
        "you don't have access" hints.
      - Otherwise uses exact scope_type/scope_id matching (pipeline write path).

    Returns (page, similarity) pairs sorted by similarity descending. Returns
    an empty list if no active embedding model is configured.
    """
    if spec_id is None:
        registry = ProviderRegistry(session)
        spec_id = await registry.get_active_embedding_spec_id()
    if not spec_id:
        return []

    spec = get_spec(spec_id)
    Emb = get_embedding_model_for_dim(spec.dimension)

    if all_scopes and not inverse_scope:
        scope_clause = None
    elif inverse_scope:
        scope_clause = _inverse_scope_filter_for_identity(department_ids, project_ids)
    elif department_ids or project_ids:
        scope_clause = _scope_filter_for_identity(department_ids, project_ids)
    else:
        scope_clause = _scope_filter(scope_type, scope_id)

    where_clauses = [
        Emb.model_spec_id == spec.id,
        WikiPage.slug.notin_([INDEX_SLUG, LOG_SLUG, HOT_SLUG]),
    ]
    if scope_clause is not None:
        where_clauses.append(scope_clause)

    stmt = (
        select(
            WikiPage,
            (1 - Emb.embedding.cosine_distance(query_embedding)).label("similarity"),
        )
        .join(Emb, Emb.page_id == WikiPage.id)
        .where(and_(*where_clauses))
        .order_by(Emb.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    if allowed_kt_slugs:
        stmt = stmt.where(
            or_(
                WikiPage.knowledge_type_slugs.overlap(allowed_kt_slugs),
                func.cardinality(WikiPage.knowledge_type_slugs) == 0,
            )
    )
    result = await session.execute(stmt)
    return [(row[0], float(row[1])) for row in result.all()]
