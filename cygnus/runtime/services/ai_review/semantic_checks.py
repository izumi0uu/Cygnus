"""
L3 semantic — duplicate detection via embedding similarity.

Async — runs inside the arq worker. Embedding is computed once for the draft
content, then matched against the active wiki page embedding table.
"""

import uuid
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.services import wiki_service

# Pages above this cosine similarity are flagged as potential duplicates.
_DUP_THRESHOLD = 0.85
_DUP_LIMIT = 5


async def run(
    db: AsyncSession,
    content_md: str,
    self_page_id: Optional[uuid.UUID],
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    draft_kind: str = "edit",
) -> list[dict]:
    out: list[dict] = []

    # Intentional compatibility guard:
    # - Upstream baseline only runs semantic duplicate detection for `create`
    #   drafts.
    # - For `edit` drafts, the current search layer can exclude `self_page_id`
    #   but cannot suppress sibling/parent pages compiled from the same source.
    # - That makes "possible duplicate" warnings routine for ordinary edits and
    #   turns a useful create-time signal into a noisy review artifact.
    #
    # Keep the guard until semantic search can exclude related-page lineage or
    # same-source families for edit drafts. This preserves the reviewed
    # upstream behavior during P1 full-port import while documenting the exact
    # failure mode instead of treating it as an unexplained bypass.
    if draft_kind != "create":
        out.append({
            "id": "semantic.duplicate",
            "layer": "L3",
            "severity": "warn",
            "status": "skipped",
            "message": (
                "Duplicate detection is intentionally limited to new-page "
                "proposals until edit-draft searches can suppress related "
                "pages from the same source family"
            ),
            "matches": [],
        })
        return out

    try:
        from cygnus.runtime.ai.registry import ProviderRegistry
        registry = ProviderRegistry(db)
        embedder = await registry.get_embedding(task="document")
        embedding = await embedder.embed(content_md[:4000])
    except Exception as e:  # pragma: no cover — provider failure path
        logger.warning(f"AI L3 embedding failed: {e}")
        return [{
            "id": "semantic.duplicate",
            "layer": "L3",
            "severity": "warn",
            "status": "skipped",
            "message": f"Embedding lookup failed: {e}",
            "matches": [],
        }]

    pairs = await wiki_service.search_pages_semantic(
        db, query_embedding=embedding, top_k=_DUP_LIMIT + 1,
        scope_type=scope_type, scope_id=scope_id,
    )
    similar = []
    for page, sim in pairs:
        if self_page_id is not None and page.id == self_page_id:
            continue
        if sim >= _DUP_THRESHOLD:
            similar.append({"slug": page.slug, "title": page.title, "score": round(sim, 3)})

    out.append({
        "id": "semantic.duplicate",
        "layer": "L3",
        "severity": "warn",
        "status": "warn" if similar else "pass",
        "message": (
            f"{len(similar)} existing page(s) look similar — consider editing instead of creating"
            if similar else None
        ),
        "matches": similar[:_DUP_LIMIT],
    })
    return out
