"""
Verbatim source indexing.

A preserve_verbatim Source skips the LLM wiki pipeline (MRP). Instead its raw
full_text is split into page-aligned chunks and embedded as-is into the
source_chunk_embeddings_<dim> tables, so it is discoverable in the same semantic
search pool as wiki pages — but never rewritten.

Chunking is page-based: every chunk carries the exact 1-based page_number it came
from (clean "trang N" citations) and char offsets into full_text so a clean
preview can be sliced back out. Long pages are sub-split into overlapping windows.
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_catalog import get_spec
from app.ai.registry import ProviderRegistry
from app.database.models import Source, get_source_chunk_embedding_model_for_dim
from app.services.embedding_storage import (
    chunk_content_hash,
    upsert_chunk_embedding,
)
from app.services.source_outline import PAGE_JOIN_SEPARATOR

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
