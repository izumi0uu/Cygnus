"""
Helpers for writing/reading wiki page embeddings across the
per-dimension `wiki_page_embeddings_<dim>` tables.

Use these instead of touching the embedding tables directly so callers don't
have to care which dimension corresponds to the active model.
"""

import hashlib
import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_catalog import EmbeddingModelSpec, get_spec
from app.database.models import (
    EmbeddingJob,
    get_embedding_model_for_dim,
    get_source_chunk_embedding_model_for_dim,
)


def compute_content_hash(title: str, summary: str, content_md: str) -> str:
    """Stable hash of the text we feed into the embedding model."""
    blob = f"{title}\n\n{summary or ''}\n\n{content_md or ''}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def embedding_input_text(title: str, summary: str, content_md: str) -> str:
    """The exact text that gets embedded — kept in one place so hash matches."""
    return f"{title}\n\n{summary or ''}\n\n{content_md or ''}"[:8000]


async def upsert_page_embedding(
    session: AsyncSession,
    page_id: uuid.UUID,
    spec: EmbeddingModelSpec,
    vector: list[float],
    content_hash: str,
) -> None:
    """Upsert one (page, model_spec_id) row into wiki_page_embeddings_<dim>."""
    Model = get_embedding_model_for_dim(spec.dimension)
    stmt = pg_insert(Model).values(
        page_id=page_id,
        model_spec_id=spec.id,
        content_hash=content_hash,
        embedding=vector,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["page_id", "model_spec_id"],
        set_={
            "embedding": stmt.excluded.embedding,
            "content_hash": stmt.excluded.content_hash,
            "embedded_at": stmt.excluded.embedded_at,
        },
    )
    await session.execute(stmt)


async def get_existing_hash(
    session: AsyncSession, page_id: uuid.UUID, spec_id: str, dimension: int
) -> Optional[str]:
    Model = get_embedding_model_for_dim(dimension)
    row = (
        await session.execute(
            select(Model.content_hash).where(
                Model.page_id == page_id, Model.model_spec_id == spec_id
            )
        )
    ).scalar_one_or_none()
    return row


async def cleanup_stale_embeddings(
    session: AsyncSession, keep_spec_id: str
) -> int:
    """
    Delete rows in every wiki_page_embeddings_<dim> table whose model_spec_id
    is NOT `keep_spec_id`. Returns total deleted rows.

    Called after an atomic flip so the inactive model's vectors don't waste
    disk + index memory.
    """
    from app.database.models import (
        WikiPageEmbedding768,
        WikiPageEmbedding1024,
        WikiPageEmbedding1536,
        WikiPageEmbedding3072,
    )
    total = 0
    for Model in (
        WikiPageEmbedding768,
        WikiPageEmbedding1024,
        WikiPageEmbedding1536,
        WikiPageEmbedding3072,
    ):
        result = await session.execute(
            delete(Model).where(Model.model_spec_id != keep_spec_id)
        )
        total += result.rowcount or 0  # type: ignore[union-attr]
    return total


def get_spec_for_job(job: EmbeddingJob) -> EmbeddingModelSpec:
    return get_spec(job.model_spec_id)


async def cleanup_stale_source_chunk_embeddings(
    session: AsyncSession, keep_spec_id: str
) -> int:
    """Delete source chunk embedding rows whose model_spec_id != keep_spec_id,
    across every dimension table. Mirrors cleanup_stale_embeddings for the
    verbatim source pool; called after the atomic embedding-model flip."""
    from app.database.models import (
        SourceChunkEmbedding768,
        SourceChunkEmbedding1024,
        SourceChunkEmbedding1536,
        SourceChunkEmbedding3072,
    )
    total = 0
    for Model in (
        SourceChunkEmbedding768,
        SourceChunkEmbedding1024,
        SourceChunkEmbedding1536,
        SourceChunkEmbedding3072,
    ):
        result = await session.execute(
            delete(Model).where(Model.model_spec_id != keep_spec_id)
        )
        total += result.rowcount or 0  # type: ignore[union-attr]
    return total


# ---------------------------------------------------------------------------
# Verbatim source chunk embeddings
# ---------------------------------------------------------------------------

def chunk_content_hash(text: str) -> str:
    """Stable hash of the raw chunk text fed into the embedding model."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def upsert_chunk_embedding(
    session: AsyncSession,
    source_id: uuid.UUID,
    chunk_index: int,
    spec: EmbeddingModelSpec,
    vector: list[float],
    *,
    text: str,
    start_char: int,
    end_char: int,
    page_number: int,
    content_hash: str,
) -> None:
    """Upsert one (source, chunk_index, model_spec_id) row into
    source_chunk_embeddings_<dim>."""
    Model = get_source_chunk_embedding_model_for_dim(spec.dimension)
    stmt = pg_insert(Model).values(
        source_id=source_id,
        chunk_index=chunk_index,
        model_spec_id=spec.id,
        start_char=start_char,
        end_char=end_char,
        page_number=page_number,
        text=text,
        content_hash=content_hash,
        embedding=vector,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["source_id", "chunk_index", "model_spec_id"],
        set_={
            "embedding": stmt.excluded.embedding,
            "content_hash": stmt.excluded.content_hash,
            "text": stmt.excluded.text,
            "start_char": stmt.excluded.start_char,
            "end_char": stmt.excluded.end_char,
            "page_number": stmt.excluded.page_number,
            "embedded_at": stmt.excluded.embedded_at,
        },
    )
    await session.execute(stmt)


async def delete_source_chunk_embeddings(
    session: AsyncSession, source_id: uuid.UUID
) -> int:
    """Delete every chunk embedding row for a source across all dimension tables.

    Called before re-indexing a verbatim source (re-ingest) so stale chunks from
    a previous run don't linger.
    """
    from app.database.models import (
        SourceChunkEmbedding768,
        SourceChunkEmbedding1024,
        SourceChunkEmbedding1536,
        SourceChunkEmbedding3072,
    )
    total = 0
    for Model in (
        SourceChunkEmbedding768,
        SourceChunkEmbedding1024,
        SourceChunkEmbedding1536,
        SourceChunkEmbedding3072,
    ):
        result = await session.execute(
            delete(Model).where(Model.source_id == source_id)
        )
        total += result.rowcount or 0  # type: ignore[union-attr]
    return total
