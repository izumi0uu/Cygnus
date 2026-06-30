"""Raw source chunk retrieval and verbatim indexing for Cygnus.

Ownership:
- verbatim raw-source chunking, semantic indexing, and chunk retrieval live here
- this module serves retrieval truth for preserve_verbatim sources, not runtime service wiring
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.ai.embedding_catalog import get_spec
from cygnus.runtime.ai.registry import ProviderRegistry
from cygnus.runtime.database.models import Source, get_source_chunk_embedding_model_for_dim
from cygnus.runtime.services.embedding_storage import (
    chunk_content_hash,
    upsert_chunk_embedding,
)
from cygnus.substrate.source_outline import PAGE_JOIN_SEPARATOR

# Retrieval-sized chunks (much smaller than the MAP chunker's 20k) for precision.
CHUNK_TARGET_CHARS = 2_000
CHUNK_OVERLAP_CHARS = 200
MIN_CHUNK_CHARS = 50


@dataclass
class VerbatimChunk:
    index: int
    page_number: int  # 1-based
    start_char: int   # absolute offset in full_text
    end_char: int
    text: str


def _page_bounds(full_text: str, page_offsets: list[int]) -> list[tuple[int, int, int]]:
    """Return [(page_number, start_char, end_char), ...] for each page (1-based)."""
    if not page_offsets:
        return [(1, 0, len(full_text))] if full_text else []
    total = len(page_offsets)
    out: list[tuple[int, int, int]] = []
    for idx in range(total):
        start = page_offsets[idx]
        if idx + 1 < total:
            end = page_offsets[idx + 1] - len(PAGE_JOIN_SEPARATOR)
        else:
            end = len(full_text)
        out.append((idx + 1, start, max(start, end)))
    return out


def build_verbatim_chunks(full_text: str, page_offsets: list[int]) -> list[VerbatimChunk]:
    """Split full_text into page-aligned, retrieval-sized chunks.

    Each chunk belongs to exactly one page. Pages longer than CHUNK_TARGET_CHARS
    are sub-split into overlapping windows. `text` is the clean slice of full_text
    (no synthetic separators), and start/end are absolute offsets.
    """
    chunks: list[VerbatimChunk] = []
    idx = 0
    for page_number, p_start, p_end in _page_bounds(full_text, page_offsets):
        pos = p_start
        while pos < p_end:
            end = min(pos + CHUNK_TARGET_CHARS, p_end)
            text = full_text[pos:end]
            if len(text.strip()) >= MIN_CHUNK_CHARS:
                chunks.append(VerbatimChunk(
                    index=idx,
                    page_number=page_number,
                    start_char=pos,
                    end_char=end,
                    text=text,
                ))
                idx += 1
            if end >= p_end:
                break
            pos = end - CHUNK_OVERLAP_CHARS  # overlap window
            if pos <= p_start and end < p_end:
                pos = end  # degenerate guard (tiny target vs overlap)
    return chunks


async def index_verbatim_source(
    session: AsyncSession,
    source: Source,
    spec_id: Optional[str] = None,
) -> int:
    """Chunk + embed a verbatim source's full_text into source_chunk_embeddings_<dim>.

    Returns the number of chunks indexed. Returns 0 (and logs) if no embedding
    model is configured — the source still becomes searchable via the keyword
    `search_source_content` tool; embeddings get backfilled on the next re-embed.

    Args:
        spec_id: Embed against this specific spec instead of the system's active
            one. Used by the re-embed migration job (which embeds with the NEW
            model while the active spec still points at the OLD one).
    """
    full_text = source.full_text or ""
    if not full_text.strip():
        logger.warning(f"index_verbatim_source: source {source.id} has no full_text")
        return 0

    registry = ProviderRegistry(session)
    if spec_id is None:
        spec_id = await registry.get_active_embedding_spec_id()
    if not spec_id:
        logger.warning(
            f"index_verbatim_source: no active embedding model configured — "
            f"source {source.id} stored verbatim but not semantically indexed "
            f"(keyword search still works; run re-embed after configuring a model)"
        )
        return 0

    spec = get_spec(spec_id)
    provider = await registry.get_embedding(task="document", spec_id=spec_id)

    chunks = build_verbatim_chunks(full_text, source.page_offsets or [])
    if not chunks:
        return 0

    # Clear prior rows for THIS source in THIS spec only, so a re-ingest with a
    # shorter doc doesn't leave orphaned high-index chunks. Other specs' rows are
    # left intact (the re-embed migration relies on the old spec staying live
    # until the atomic flip; stale specs are pruned by cleanup afterwards).
    Model = get_source_chunk_embedding_model_for_dim(spec.dimension)
    await session.execute(
        delete(Model).where(
            Model.source_id == source.id, Model.model_spec_id == spec.id
        )
    )

    vectors = await provider.embed_batch([c.text for c in chunks])
    for chunk, vector in zip(chunks, vectors):
        await upsert_chunk_embedding(
            session,
            source_id=source.id,
            chunk_index=chunk.index,
            spec=spec,
            vector=vector,
            text=chunk.text,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            page_number=chunk.page_number,
            content_hash=chunk_content_hash(chunk.text),
        )
    await session.commit()
    logger.info(f"index_verbatim_source: indexed {len(chunks)} chunks for source {source.id}")
    return len(chunks)


async def search_source_chunks_semantic(
    session: AsyncSession,
    query_embedding: list[float],
    top_k: int = 10,
    allowed_source_ids: Optional[set[str]] = None,
    spec_id: Optional[str] = None,
):
    """
    Cosine-similarity search over verbatim source chunk embeddings.

    Mirrors `search_pages_semantic` but over `source_chunk_embeddings_<dim>`
    (raw, never-rewritten slices of preserve_verbatim sources). Lets high-fidelity
    docs (decrees, gazettes) be retrieved in the same semantic pool as wiki pages.

    RBAC: pass `allowed_source_ids` (the set returned by the MCP layer's
    `_get_allowed_source_ids`). None means open access; an empty set means no
    access (returns nothing).

    Returns (Source, chunk_row, similarity) tuples sorted by similarity desc.
    Returns [] if no active embedding model is configured.
    """
    import uuid as _uuid

    from cygnus.runtime.ai.embedding_catalog import get_spec
    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.database.models import (
        Source,
        get_source_chunk_embedding_model_for_dim,
    )

    if allowed_source_ids is not None and len(allowed_source_ids) == 0:
        return []

    if spec_id is None:
        registry = ProviderRegistry(session)
        spec_id = await registry.get_active_embedding_spec_id()
    if not spec_id:
        return []

    spec = get_spec(spec_id)
    Emb = get_source_chunk_embedding_model_for_dim(spec.dimension)

    where_clauses = [
        Emb.model_spec_id == spec.id,
        Source.preserve_verbatim.is_(True),
        Source.status == "ready",
    ]
    if allowed_source_ids is not None:
        where_clauses.append(
            Source.id.in_([_uuid.UUID(s) for s in allowed_source_ids])
        )

    stmt = (
        select(
            Source,
            Emb,
            (1 - Emb.embedding.cosine_distance(query_embedding)).label("similarity"),
        )
        .join(Source, Source.id == Emb.source_id)
        .where(and_(*where_clauses))
        .order_by(Emb.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1], float(row[2])) for row in result.all()]
