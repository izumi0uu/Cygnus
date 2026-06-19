"""
Phase 2 (REDUCE) of the MRP pipeline.

Steps:
  2.1  Collect all entities/concepts from chunk extracts
  2.2  Exact deduplication by normalized name
  2.3  Embedding-based deduplication (cosine similarity)
  2.4  LLM batch resolution for ambiguous entity pairs
  2.5  KB reconciliation: search existing wiki pages per entity
  2.6  LLM batch confirmation for MAYBE matches
  2.7  Planning call: 1 LLM call → Compilation Plan JSON
  2.8  Persist SourceCompilationPlan to DB
"""

import asyncio
import string
from typing import TYPE_CHECKING, Optional, Union

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import EmbeddingProvider, LLMProvider
from app.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from app.database.models import SourceCompilationPlan

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MERGE_THRESHOLD = 0.90      # cosine sim → auto-merge entities
AMBIGUOUS_LOW = 0.75        # cosine sim → send to LLM for disambiguation
KB_UPDATE_THRESHOLD = 0.85  # sim → UPDATE existing wiki page
KB_MAYBE_THRESHOLD = 0.60   # sim → MAYBE update (LLM confirms)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _normalize(name: str) -> str:
    return name.lower().strip().translate(_PUNCT_TABLE)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Step 2.1 — Collect entities and concepts from chunk extracts
# ---------------------------------------------------------------------------

def collect_raw_items(chunk_extracts) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Flatten entities, concepts, and claims from all SourceChunkExtract rows.

    Returns (entities, concepts, claims) where each item carries its
    source chunk_index and absolute_offset fields.
    For R&D pivot, we merge entities into concepts (general pages) and return entities as [].
    """
    entities: list[dict] = []
    concepts: list[dict] = []
    claims: list[dict] = []

    for row in chunk_extracts:
        extract = row.extract_json or {}
        chunk_idx = row.chunk_index

        for e in extract.get("entities", []):
            concepts.append({
                "term": e.get("name", ""),
                "definition_excerpt": e.get("type", "other"),
                "absolute_offset": e.get("absolute_offset"),
                "_chunk_index": chunk_idx
            })

        for c in extract.get("concepts", []):
            concepts.append({**c, "_chunk_index": chunk_idx})

        for cl in extract.get("claims", []):
            claims.append({**cl, "_chunk_index": chunk_idx})

    return entities, concepts, claims


# ---------------------------------------------------------------------------
# Step 2.2 — Exact deduplication
# ---------------------------------------------------------------------------

def exact_dedup_entities(raw_entities: list[dict]) -> list[dict]:
    """Deprecated: General pages use exact_dedup_concepts. Returns [] for compatibility."""
    return []


def exact_dedup_concepts(raw_concepts: list[dict]) -> list[dict]:
    """Group concepts by normalized term."""
    groups: dict[str, list[dict]] = {}
    for c in raw_concepts:
        key = _normalize(c.get("term", ""))
        groups.setdefault(key, []).append(c)

    canonical: list[dict] = []
    for norm_term, group in groups.items():
        term_counts: dict[str, int] = {}
        for c in group:
            t = c.get("term", "")
            term_counts[t] = term_counts.get(t, 0) + 1
        best_term = max(term_counts, key=lambda x: term_counts[x])

        # Keep longest/best definition_excerpt
        best_def = max(
            (c.get("definition_excerpt", "") for c in group),
            key=len,
            default="",
        )
        offsets = [c.get("absolute_offset", 0) for c in group if c.get("absolute_offset") is not None]

        canonical.append({
            "term": best_term,
            "definition_excerpt": best_def,
            "mention_count": len(group),
            "absolute_offsets": offsets,
            "_norm": norm_term,
        })

    return canonical


# ---------------------------------------------------------------------------
# Step 2.3 — Embedding-based deduplication
# ---------------------------------------------------------------------------

async def embedding_dedup_entities(
    entities: list[dict],
    embedding_provider: EmbeddingProvider,
) -> Union[list[dict], tuple[dict[int, int], list[tuple[int, int]], list[list[float]], list[dict]]]:
    """Deprecated: General pages use embedding_dedup_concepts. Returns [] for compatibility."""
    return []


async def embedding_dedup_concepts(
    concepts: list[dict],
    embedding_provider: EmbeddingProvider,
) -> Union[list[dict], tuple[dict[int, int], list[tuple[int, int]], list[list[float]], list[dict]]]:
    """
    Merge concepts whose term embeddings are very similar (> MERGE_THRESHOLD).
    Returns a reduced list of canonical concepts.
    """
    if len(concepts) <= 1:
        return concepts

    names = [c["term"] for c in concepts]
    try:
        vectors = await embedding_provider.embed_batch(names)
    except Exception as exc:
        logger.warning(f"MRP REDUCE embedding dedup failed: {exc}. Skipping.")
        return concepts

    n = len(concepts)
    merged_into: dict[int, int] = {}  # index → canonical index

    def _root(i: int) -> int:
        while i in merged_into:
            i = merged_into[i]
        return i

    auto_merge_pairs: list[tuple[int, int]] = []
    ambiguous_pairs: list[tuple[int, int]] = []

    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine(vectors[i], vectors[j])
            if sim >= MERGE_THRESHOLD:
                auto_merge_pairs.append((i, j))
            elif sim >= AMBIGUOUS_LOW:
                ambiguous_pairs.append((i, j))

    # Apply auto-merges
    for i, j in auto_merge_pairs:
        ri, rj = _root(i), _root(j)
        if ri != rj:
            # Merge lower-mention into higher-mention
            if concepts[ri]["mention_count"] >= concepts[rj]["mention_count"]:
                merged_into[rj] = ri
            else:
                merged_into[ri] = rj

    # Collect ambiguous pairs not already merged
    still_ambiguous = [
        (i, j) for i, j in ambiguous_pairs if _root(i) != _root(j)
    ]

    return merged_into, still_ambiguous, vectors, concepts


async def resolve_ambiguous_entities(
    llm: LLMProvider,
    entities: list[dict],
    ambiguous_pairs: list[tuple[int, int]],
    merged_into: dict[int, int],
) -> dict[int, int]:
    """Deprecated: General pages use resolve_ambiguous_concepts. Returns merged_into for compatibility."""
    return merged_into


async def resolve_ambiguous_concepts(
    llm: LLMProvider,
    concepts: list[dict],
    ambiguous_pairs: list[tuple[int, int]],
    merged_into: dict[int, int],
) -> dict[int, int]:
    """
    Send ambiguous concept pairs to LLM for batch disambiguation.
    Returns updated merged_into dict.
    """
    if not ambiguous_pairs:
        return merged_into

    def _root(i):
        while i in merged_into:
            i = merged_into[i]
        return i

    lines = []
    for k, (i, j) in enumerate(ambiguous_pairs):
        lines.append(
            f"{k + 1}. \"{concepts[i]['term']}\" vs \"{concepts[j]['term']}\""
        )

    prompt = (
        "For each pair below, determine if they refer to the same real-world concept or term.\n"
        "Return a JSON array of exactly " + str(len(ambiguous_pairs)) + " booleans "
        "(true = same, false = different).\n"
        "Return ONLY the JSON array.\n\n" + "\n".join(lines)
    )

    try:
        raw = await asyncio.wait_for(
            llm.generate(prompt, system="You are a concept resolution assistant. Return only JSON.", temperature=0.0),
            timeout=60,
        )
        from app.utils.text import parse_json_loose
        decisions: list[bool] = parse_json_loose(raw)
        for k, (i, j) in enumerate(ambiguous_pairs):
            if k < len(decisions) and decisions[k]:
                ri, rj = _root(i), _root(j)
                if ri != rj:
                    if concepts[ri]["mention_count"] >= concepts[rj]["mention_count"]:
                        merged_into[rj] = ri
                    else:
                        merged_into[ri] = rj
    except Exception as exc:
        logger.warning(f"MRP REDUCE ambiguous concept resolution failed: {exc}. Skipping.")

    return merged_into


def _apply_merges(entities: list[dict], merged_into: dict[int, int]) -> list[dict]:
    """Deprecated: General pages use _apply_merges_concepts."""
    return []


def _apply_merges_concepts(concepts: list[dict], merged_into: dict[int, int]) -> list[dict]:
    """Apply merge map to produce final deduplicated concept list."""
    def _root(i):
        while i in merged_into:
            i = merged_into[i]
        return i

    roots = set(_root(i) for i in range(len(concepts)))
    result = []
    for ri in roots:
        canonical = dict(concepts[ri])
        # Merge all mention_counts and absolute_offsets
        for i, c in enumerate(concepts):
            if i != ri and _root(i) == ri:
                canonical["mention_count"] = canonical.get("mention_count", 0) + c.get("mention_count", 0)
                canonical["absolute_offsets"] = canonical.get("absolute_offsets", []) + c.get("absolute_offsets", [])
                if len(c.get("definition_excerpt", "")) > len(canonical.get("definition_excerpt", "")):
                    canonical["definition_excerpt"] = c["definition_excerpt"]
        result.append(canonical)
    return result


# ---------------------------------------------------------------------------
# Step 2.5 — KB reconciliation
# ---------------------------------------------------------------------------

async def reconcile_with_kb(
    session: AsyncSession,
    entities: list[dict],
    concepts: list[dict],
    embedding_provider: EmbeddingProvider,
    source,
    llm: Optional[LLMProvider] = None,
) -> dict[str, dict]:
    """
    For each canonical entity/concept, search existing wiki pages.
    Returns {item_name: {"action": "CREATE"|"UPDATE"|"MAYBE", "page_slug": str|None, "similarity": float}}
    """
    from app.ai.mrp.pipeline import _resolve_wiki_scopes
    from app.services import wiki_service
    wiki_scopes = await _resolve_wiki_scopes(session, source)

    all_items = [("entity", e["name"], e) for e in entities] + \
                [("concept", c["term"], c) for c in concepts]

    reconciliation: dict[str, dict] = {}

    if not all_items:
        return reconciliation

    # Batch-embed all query texts in a single API call, then search DB sequentially.
    # Sequential DB access avoids concurrent AsyncSession errors.
    query_texts = [
        (f"{name}: {item['definition_excerpt'][:200]}" if itype == "concept" and item.get("definition_excerpt") else name)[:4000]
        for itype, name, item in all_items
    ]
    try:
        vectors = await embedding_provider.embed_batch(query_texts)
    except Exception as exc:
        logger.warning(f"MRP REDUCE kb reconcile embed_batch failed: {exc}. All items → CREATE.")
        return {name: {"action": "CREATE", "page_slug": None, "similarity": 0.0} for _, name, _ in all_items}

    for (_, name, _), vec in zip(all_items, vectors):
        # Search across ALL scopes the source belongs to and keep the best hit.
        # Prevents creating duplicate pages when an entity exists in one of the
        # destination scopes but the search only checks another.
        best_hit: Optional[tuple] = None
        for scope_type, scope_id in wiki_scopes:
            try:
                hits = await wiki_service.search_pages_semantic(
                    session, vec, top_k=3, scope_type=scope_type, scope_id=scope_id,
                )
            except Exception as exc:
                logger.debug(f"MRP REDUCE kb reconcile failed for '{name}' scope={scope_type}: {exc}")
                continue
            if not hits:
                continue
            page, sim = hits[0]
            if best_hit is None or sim > best_hit[1]:
                best_hit = (page, sim)

        if best_hit is None:
            reconciliation[name] = {"action": "CREATE", "page_slug": None, "similarity": 0.0}
            continue

        top_page, top_sim = best_hit
        if top_sim >= KB_UPDATE_THRESHOLD:
            reconciliation[name] = {"action": "UPDATE", "page_slug": top_page.slug, "similarity": top_sim}
        elif top_sim >= KB_MAYBE_THRESHOLD:
            reconciliation[name] = {"action": "MAYBE", "page_slug": top_page.slug, "similarity": top_sim,
                                    "_page_title": top_page.title}
        else:
            reconciliation[name] = {"action": "CREATE", "page_slug": None, "similarity": top_sim}

    # Batch-resolve MAYBE items with LLM
    maybe_items = [(name, rec) for name, rec in reconciliation.items() if rec["action"] == "MAYBE"]
    if maybe_items:
        await _resolve_maybe_items(reconciliation, maybe_items, embedding_provider, llm=llm)

    return reconciliation


async def _resolve_maybe_items(
    reconciliation: dict,
    maybe_items: list[tuple[str, dict]],
    embedding_provider,
    llm: Optional[LLMProvider] = None,
):
    """Resolve MAYBE items via LLM; falls back to CREATE when LLM is unavailable."""
    if not maybe_items:
        return

    if llm is None:
        for name, _ in maybe_items:
            reconciliation[name]["action"] = "CREATE"
        return

    lines = []
    for k, (name, rec) in enumerate(maybe_items):
        page_title = rec.get("_page_title") or rec.get("page_slug", "")
        lines.append(
            f"{k + 1}. Entity: \"{name}\" — existing wiki page: \"{page_title}\" "
            f"(slug: {rec['page_slug']}, similarity: {rec['similarity']:.2f})"
        )

    prompt = (
        "For each pair below, decide whether the entity refers to the same real-world "
        "concept as the existing wiki page (true = UPDATE existing page, false = CREATE new page).\n"
        "Return a JSON array of exactly " + str(len(maybe_items)) + " booleans. "
        "Return ONLY the JSON array.\n\n" + "\n".join(lines)
    )
    try:
        raw = await asyncio.wait_for(
            llm.generate(
                prompt,
                system="You are a knowledge base assistant. Return only a JSON boolean array.",
                temperature=0.0,
            ),
            timeout=30,
        )
        from app.utils.text import parse_json_loose
        decisions: list[bool] = parse_json_loose(raw)
        for k, (name, rec) in enumerate(maybe_items):
            if k < len(decisions) and decisions[k]:
                reconciliation[name]["action"] = "UPDATE"
            else:
                reconciliation[name]["action"] = "CREATE"
    except Exception as exc:
        logger.warning(f"MRP REDUCE MAYBE LLM resolution failed: {exc}. Defaulting to CREATE.")
        for name, _ in maybe_items:
            reconciliation[name]["action"] = "CREATE"


# ---------------------------------------------------------------------------
# Step 2.7 — Planning call
# ---------------------------------------------------------------------------

PLANNING_SYSTEM = """\
You are a wiki compilation planner. Given extracted topics and their relationship
to an existing knowledge base, produce a compilation plan. Return ONLY valid JSON.
"""

PLANNING_PROMPT_TEMPLATE = """\
## Source document
Title: {source_title}
Knowledge type: {kt_context}
Strategy: {strategy}

## Extracted topics (with mention counts)
{concepts_summary}

## KB reconciliation results
{kb_reconciliation}

{user_note_section}
Produce a JSON compilation plan:

{{
  "pages": [
    {{
      "action": "CREATE",
      "slug": "example-name",
      "title": "Example Page Title",
      "page_type": "concept",
      "entity_names": ["topic name covered by this page"],
      "related_kb_pages": ["existing-slug-1"],
      "priority": 1
    }}
  ],
  "estimated_page_count": 5,
  "compilation_notes": "any important notes for the compiler"
}}

Rules:
- action must be "CREATE" or "UPDATE"
- For UPDATE, slug must be an existing wiki page slug (from KB reconciliation above)
- For CREATE general wiki pages (page_type="concept"), slug must be the flat, lowercase, hyphenated topic name (e.g. "pgvector", "mcp-server"). Do NOT prepend concept/ or any other category prefix.
- Group closely related small topics onto the same page if they belong together (max 3-4 per page).
- priority 1 = highest importance (process first)
- entity_names must match the terms in the topics list above
- Target approximately {target_page_count} total pages (feel free to create more if the document is dense and contains many distinct topics).
- Return ONLY the JSON object
"""


async def run_planning_call(
    llm: LLMProvider,
    source,
    strategy: str,
    canonical_entities: list[dict],
    canonical_concepts: list[dict],
    reconciliation: dict[str, dict],
    kt_name: Optional[str],
    kt_desc: Optional[str],
    user_note: Optional[str] = None,
) -> dict:
    """Single LLM call to produce the Compilation Plan JSON."""
    # Calculate target based on the actual number of extracted concepts rather than just document length
    total_extracted_items = len(canonical_concepts)
    
    if strategy == "single_pass":
        target_pages = max(3, min(30, total_extracted_items // 2))
    elif strategy == "standard":
        target_pages = max(8, min(80, total_extracted_items // 3))
    else:
        target_pages = max(15, min(200, total_extracted_items // 3))

    kt_context = kt_name or "(no specific knowledge type)"
    if kt_desc:
        kt_context += f" — {kt_desc}"

    def _fmt_concept(c: dict) -> str:
        kb = reconciliation.get(c["term"], {})
        kb_info = f"→ {kb['action']} {kb.get('page_slug', '')}" if kb else "→ CREATE"
        return f"  - {c['term']} ({c['mention_count']} mentions) {kb_info}"

    # Sort by mention count descending to ensure the planner sees the most important items
    sorted_concepts = sorted(canonical_concepts, key=lambda x: x.get("mention_count", 0), reverse=True)
    concepts_summary = "\n".join(_fmt_concept(c) for c in sorted_concepts[:300]) or "  (none)"

    kb_lines = []
    for name, rec in reconciliation.items():
        if rec["action"] == "UPDATE":
            kb_lines.append(f"  - UPDATE: {name} → {rec['page_slug']} (sim={rec['similarity']:.2f})")
    kb_reconciliation = "\n".join(kb_lines) if kb_lines else "  (all items are new)"

    user_note_section = ""
    if user_note and user_note.strip():
        user_note_section = (
            "\n## Human reviewer feedback\n"
            f"{user_note.strip()}\n"
            "Please incorporate this feedback when producing the plan.\n"
        )

    prompt = PLANNING_PROMPT_TEMPLATE.format(
        source_title=source.title or source.file_name or str(source.id),
        kt_context=kt_context,
        strategy=strategy,
        concepts_summary=concepts_summary,
        kb_reconciliation=kb_reconciliation,
        user_note_section=user_note_section,
        target_page_count=target_pages,
    )

    raw = await asyncio.wait_for(
        llm.generate(prompt, system=PLANNING_SYSTEM, temperature=0.1),
        timeout=120,
    )

    from app.utils.text import parse_json_loose
    return parse_json_loose(raw)


# ---------------------------------------------------------------------------
# Phase 2 orchestrator
# ---------------------------------------------------------------------------

async def run_reduce_phase(
    session: AsyncSession,
    source,
    chunk_extracts: list,
    llm: LLMProvider,
    embedding_provider: Optional[EmbeddingProvider],
    kt_name: Optional[str],
    kt_desc: Optional[str],
    tracker: ProgressTracker,
) -> "SourceCompilationPlan":
    """
    Run full Phase 2 (REDUCE).

    Returns a SourceCompilationPlan ORM object with status='pending_review'.
    Uses INSERT ... ON CONFLICT DO UPDATE so re-runs safely overwrite old plans.
    """
    from app.database.models import Source, SourceCompilationPlan

    await tracker.update(66, "Collecting extractions...")

    # 2.1 Collect raw items
    raw_entities, raw_concepts, raw_claims = collect_raw_items(chunk_extracts)
    logger.info(f"MRP REDUCE: {len(raw_entities)} raw entities, {len(raw_concepts)} concepts, {len(raw_claims)} claims")

    # 2.2 Exact dedup (canonical_entities is empty)
    canonical_entities = exact_dedup_entities(raw_entities)
    canonical_concepts = exact_dedup_concepts(raw_concepts)
    logger.info(f"MRP REDUCE after exact-dedup: {len(canonical_concepts)} concepts")

    await tracker.update(68, "Deduplicating concepts...")

    # 2.3 Embedding-based dedup for concepts
    if len(canonical_concepts) > 1 and embedding_provider is not None:
        try:
            result = await embedding_dedup_concepts(canonical_concepts, embedding_provider)
            if isinstance(result, tuple):
                merged_into, ambiguous_pairs, vectors, canonical_concepts = result
                # 2.4 LLM resolution for ambiguous pairs
                merged_into = await resolve_ambiguous_concepts(llm, canonical_concepts, ambiguous_pairs, merged_into)
                canonical_concepts = _apply_merges_concepts(canonical_concepts, merged_into)
                logger.info(f"MRP REDUCE after embedding-dedup: {len(canonical_concepts)} concepts")
        except Exception as exc:
            logger.warning(f"MRP REDUCE embedding dedup error: {exc}. Continuing with exact-dedup result.")

    await tracker.update(72, "Reconciling with knowledge base...")

    # 2.5 KB reconciliation
    reconciliation: dict[str, dict] = {}
    if embedding_provider is not None:
        try:
            reconciliation = await reconcile_with_kb(
                session, canonical_entities, canonical_concepts, embedding_provider, source, llm=llm,
            )
        except Exception as exc:
            logger.warning(f"MRP REDUCE KB reconciliation failed: {exc}. All items will be CREATE.")

    await tracker.update(76, "Generating compilation plan...")

    # 2.7 Planning call
    strategy = source.pipeline_strategy or "standard"
    plan_dict = await run_planning_call(
        llm=llm,
        source=source,
        strategy=strategy,
        canonical_entities=canonical_entities,
        canonical_concepts=canonical_concepts,
        reconciliation=reconciliation,
        kt_name=kt_name,
        kt_desc=kt_desc,
    )

    # Attach claim evidence to plan (so REFINE can access claims per entity)
    plan_dict["_claims"] = raw_claims
    plan_dict["_entities"] = canonical_entities
    plan_dict["_concepts"] = canonical_concepts

    # 2.8 Persist plan (upsert: safe to re-run)

    existing = (await session.execute(
        select(SourceCompilationPlan).where(SourceCompilationPlan.source_id == source.id)
    )).scalar_one_or_none()

    if existing:
        existing.plan_json = plan_dict
        existing.status = "pending_review"
        existing.reviewed_by = None
        existing.review_note = None
        existing.reviewed_at = None
        plan_row = existing
    else:
        plan_row = SourceCompilationPlan(
            source_id=source.id,
            plan_json=plan_dict,
            status="pending_review",
        )
        session.add(plan_row)

    src = await session.get(Source, source.id)
    if src:
        src.pipeline_phase = "plan_review"

    await session.commit()
    logger.info(f"MRP REDUCE complete: plan with {len(plan_dict.get('pages', []))} pages for source={source.id}")

    return plan_row
