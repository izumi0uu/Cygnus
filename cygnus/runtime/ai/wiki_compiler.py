"""
Wiki Compiler — turns a raw source document into wiki page operations via LLM.

The compiler reads the full source text plus a compact view of the existing
wiki (slug + summary index, plus the top-K most-relevant existing pages by
embedding similarity) and asks the LLM to emit a JSON list of operations:

    [
      {"op": "create", "slug": "...", "title": "...", "page_type": "...", "content_md": "...", "summary": "..."},
      {"op": "update", "slug": "...", "new_content_md": "...", "summary": "..."},
      {"op": "log",    "entry": "..."}
    ]

Operations are applied transactionally via wiki_service. Every created or
updated page is then re-embedded and the wikilink graph is refreshed. The
compiler is provider-agnostic: it goes through ProviderRegistry which resolves
the configured LLM and embedding providers from app_config at runtime.
"""

import json
import re
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.ai.registry import ProviderRegistry
from cygnus.runtime.database.models import Source, SourceImage, WikiPage
from cygnus.runtime.services import wiki_service

# Match `image://<uuid>` references inside markdown image markers.
_IMAGE_MARKER_RE = re.compile(r"!\[[^\]]*\]\(image://([0-9a-fA-F-]{36})\)")


# Slug must be a-z 0-9 and `/_-` only — kept narrow so they're URL-safe and stable.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_/-]*[a-z0-9]$")

MAX_DOCUMENT_CHARS = 200_000  # truncate very long sources before sending to LLM
MAX_INDEX_PAGES_LISTED = 200  # how many existing pages to enumerate in the prompt
TOP_K_RELEVANT = 8            # how many semantically-relevant pages to show in full


PROMPT_TEMPLATE = """\
You are a knowledge-base compiler for an enterprise wiki. Your job is to read
a single new source document and decide how it should be integrated into the
existing wiki — what new pages to create, which existing pages to update, and
what to record in the log.

The wiki is a collection of interlinked markdown pages. Pages are stable,
permanent, and may be updated repeatedly as new sources arrive. They are NOT
per-document summaries — they're synthesis artifacts that compound over time.

# Mindset: COMPILE, do NOT summarize
You are not writing an executive summary. You are extracting structured knowledge
and rewriting it into reusable wiki pages. The output should contain MORE
information density than a summary — organized differently, but not condensed.

A summary loses specifics. A wiki page preserves them in a queryable structure.
If someone reads the wiki page two years from now, they should still be able to
find the actual numbers, regulations, procedures, names, and edge cases — not
just a high-level recap.

# What to KEEP from the source (do not lose these)
- Specific numbers: thresholds, dosages, timeframes, dimensions, distances, percentages.
- Named regulations, laws, articles, code references (e.g. "Article 5 of the Fire
  Prevention and Fighting Law 2001", "ISO 27001 §A.12.1", "Section 3.2 of the SOP").
- Equipment names, model numbers, product specs, serial ranges.
- Procedure steps in the order they appear, with the actual actions (not "follow
  the procedure" but "1. cut power 2. evacuate 3. call 114").
- Worked examples and exceptions — these are usually the highest-value content.
- Named parties, roles, contact paths, escalation chains.
- Definitions verbatim or near-verbatim if the source is authoritative.
- Cause-effect statements ("X causes Y because Z") — preserve all three parts.

# What to DROP
- Marketing language, mission statements, ceremonial filler.
- Source-specific framing: "This document explains...", "In Section 3 below...",
  "As mentioned earlier...". The wiki page stands alone, not anchored to the source.
- Repeated boilerplate, tables of contents, cover page metadata.
- Prose that just rephrases what was already said.

# Language rule
Write every page in the SAME LANGUAGE as the source document. If the document
is in Vietnamese, write Vietnamese. If English, write English. Never translate
the body content. (Slugs are still in Latin characters — see slug rules below.)

# Page types
- `entity`  — a specific named thing: a person, organization, system, product, place.
- `concept` — a process, policy, rule, methodology, regulation, equipment type, or
              any other reusable idea that deserves its own permanent reference page.
- `topic`   — a broader subject area that groups related entities and concepts.
- `source`  — a one-page summary of THIS document. Always create exactly one.

# Slug rules
- URL-safe, lowercase, hyphenated, prefixed by type:
  `entity/jane-doe`, `concept/expense-approval`, `topic/fire-safety`,
  `source/<short-doc-slug>`.
- Slugs must be in English/Latin characters regardless of document language
  (transliterate or translate key words). Example: for "Fire extinguisher" use
  `concept/fire-extinguisher`.
- Pick stable, generalizable slugs future sources will naturally update.

# Wikilinks
- Use `[[slug]]` or `[[slug|display text]]` to link between pages.
- Always link the first mention of any entity/concept to its dedicated page.
- Link to pages that don't exist yet — the next source might create them.

# Content quality — CRITICAL
Each page must be a proper encyclopedic article, NOT a flat bullet list copied
from the source. Follow this structure:

  ## Good page structure
  1. **Opening paragraph** — 2-4 sentences defining what this thing is and why it
     matters in context. No heading for this paragraph; it comes right after the
     H1 title.
  2. **Sections with H2 headings** — group related facts under clear headings.
     Each section starts with a sentence of prose before any sub-bullets.
  3. **Bold key terms** on first use. Link them to their wiki pages with [[ ]].
  4. **Examples or implications** where the source provides them.
  5. **See also** section at the end — wikilinks to closely related pages.

  ## What NOT to do
  - Do NOT dump the raw bullet points from the source document as the entire content.
  - Do NOT write a page that is just a title + 3 bullets. That is not a wiki page.
  - Do NOT omit the opening prose paragraph.
  - Do NOT write a page with no wikilinks — every page must link to at least 1 other.

  ## Minimum depth
  - `concept` and `topic` pages: at least 150 words of actual prose+structure.
  - `entity` pages: at least 80 words.
  - `source` pages: at least 100 words summarizing key facts and links to all
    entity/concept pages it touches.

  ## BAD example — what NOT to produce
  This is a summary, not a wiki page. It loses every critical detail from the source:
  ```
  # Fire safety responsibilities of a household

  Defines the responsibilities of the household head and family members.

  ## Responsibilities of the household head
  - Tell members to follow fire safety rules.
  - Inspect and mitigate fire and explosion risks.
  - Coordinate with authorities and other households.

  ## Responsibilities of individual members
  - Follow fire safety rules.
  - Understand firefighting basics.
  - Stay safe when using flames or heat sources.
  ```
  Why this is bad: it's just bullet headlines. No legal references, no specific
  numbers, no procedure steps, no equipment names. A person reading it later
  cannot answer any practical question.

  ## GOOD example — preserves substance from the source
  ```
  # Fire safety responsibilities of a household

  Every household has a legal duty within [[concept/fire-safety|fire safety work]] under
  Article 5 of [[entity/fire-prevention-and-fighting-law-2001|the Fire Prevention and
  Fighting Law 2001]] (as amended in 2013) and Decree 136/2020/ND-CP. Responsibility is
  split between the household head — the primary legal holder — and the members, forming
  the first line of defense before professional fire services are needed.

  ## Responsibilities of the household head

  The household head is primarily responsible for fire safety at home and must complete
  three groups of duties:

  ### 1. Educate and enforce compliance

  The household head must make sure every member old enough (10+) understands the basic
  fire safety rules. Recommended practices:
  - Hold at least one internal briefing each quarter.
  - Run [[concept/emergency-evacuation|evacuation]] drills every 6 months, especially for
    children and older adults.
  - Teach children the 114 emergency number, primary and secondary escape routes, and the
    low-crawl technique in smoke.

  ### 2. Inspect and mitigate fire and explosion risks

  The household head should inspect common hazards regularly (weekly is recommended):

  | Hazard source | Warning signs |
  |---|---|
  | [[concept/electrical-system|Electrical system]] | Unusual heat, overloaded outlets, devices tripping |
  | [[entity/lpg-cylinder|LPG cylinder]] | Smell of a leak, cracked hose, expired cylinder (3-5 years) |
  | Flammable materials | Gasoline/oil near heat sources, paper/fabric near the stove |

  If a hazard is found, resolve it within **24 hours** or isolate it until it is safe.

  ### 3. Coordinate with authorities

  When a fire occurs, the household head should follow this sequence:
  1. Call [[entity/fire-department|the fire department]] immediately at **114** and provide
     the exact address, number of floors, and whether anyone is trapped.
  2. Evacuate everyone to the agreed assembly point (recommended distance: at least 20 m
     from the house).
  3. Deploy a [[concept/portable-fire-extinguisher|portable fire extinguisher]] if the fire
     is still small — the "golden window" is usually the first 2 minutes.
  4. Share the fire location, burning materials, and any remaining occupants with arriving
     responders.

  ## Responsibilities of each member

  Every member (including children, depending on age) must:
  - Follow the household and neighborhood [[concept/fire-safety-rules|fire safety rules]].
  - Know how to use a standard ABC [[concept/portable-fire-extinguisher|portable fire extinguisher]]
    and a [[concept/fire-blanket|fire blanket]].
  - Check for safety when leaving any area with [[concept/flame-and-heat-source|flame or heat
    sources]]: turn off the stove, unplug the iron, and check the gas valve.

  ## See also

  - [[concept/fire-prevention-and-fighting]]
  - [[concept/home-fire-prevention]]
  - [[concept/fire-incident-response]]
  - [[entity/fire-prevention-and-fighting-law-2001]]
  ```
  Why this is good: it preserves the legal references, specific numbers (age 10+,
  every 6 months, 24 hours, 20 m, 2 minutes, 114), equipment specifics (ABC extinguisher,
  fire blanket), procedure ordering, edge cases (children and older adults), and links
  throughout.

# Image markers
The source text may contain image references in this exact form:
    ![caption](image://<uuid>)

Rules for handling them:
- PRESERVE these markers verbatim — do not rename, rewrite, or invent UUIDs.
- PLACE each marker in the wiki page where it's most contextually relevant
  (next to the section that discusses the same thing). You can move them
  between paragraphs or sections — that's the point.
- DROP a marker if no page meaningfully discusses it (decorative/irrelevant).
- A single marker should appear in AT MOST ONE wiki page (no duplication).
- Keep markers on their own line for readability.
- The caption inside `![ ]` may be edited for clarity, but the `(image://uuid)`
  part must stay byte-for-byte identical to what was in the source.

# Decision rules
- Prefer UPDATE over CREATE when the wiki already has a relevant page.
  Merge new facts into existing prose; don't just append.
- CREATE only when the entity/concept doesn't yet have its own page.
- Create one `source` page summarizing this document with links to all pages it touches.
- Touch as many pages as the document warrants:
  - Short document (1-5 pages): 5-10 ops.
  - Medium document (5-20 pages): 10-20 ops.
  - Long/technical document (20+ pages): 20-40 ops.
  - Err on granular — each distinct regulation, equipment type, procedure, or hazard
    category deserves its own `concept` page if covered in any depth.
- If an existing page is irrelevant to this document, DO NOT touch it.

# Output format
Return ONLY a single JSON object, no markdown fences, no commentary:

{{
  "operations": [
    {{"op": "create", "slug": "concept/...", "title": "...", "page_type": "concept",
      "content_md": "# ...\\n\\n<opening paragraph>\\n\\n## ...\\n\\n...", "summary": "one-line summary"}},
    {{"op": "update", "slug": "entity/...", "title": "...", "page_type": "entity",
      "new_content_md": "# ...\\n\\n...", "summary": "one-line summary"}},
    {{"op": "log", "entry": "ingested <doc title>: created N pages, updated M"}}
  ]
}}

Always include exactly one log op summarizing what you did.

# Document context
{kt_context}
Document title: {doc_title}

# Existing wiki — index of all pages (slug — summary)
{wiki_index}

# Existing wiki — relevant pages in full (consider updating these)
{relevant_pages}

# Document content (truncated if very long)
{document_text}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compile_source_into_wiki(
    session: AsyncSession,
    source: Source,
    full_text: str,
    knowledge_type_slug: Optional[str],
    knowledge_type_name: Optional[str],
    knowledge_type_description: Optional[str],
) -> dict:
    """
    Run the wiki compiler for one source. Persists changes via `session`
    (caller is responsible for the surrounding transaction/commit).

    Scope is inherited from the source: if the source has scope_type='project'
    and scope_id set, all created/updated wiki pages will be scoped to that
    workspace. Global sources produce global wiki pages.

    Returns: {"pages_created": int, "pages_updated": int, "log_entry": str}
    """
    # Resolve scope from source
    src_scope_type = source.scope_type or "global"
    src_scope_id = source.scope_id

    registry = ProviderRegistry(session)

    embedding_provider = await registry.get_embedding(task="document")
    llm = await registry.get_llm()

    truncated_text = full_text[:MAX_DOCUMENT_CHARS]
    if len(full_text) > MAX_DOCUMENT_CHARS:
        truncated_text += "\n\n[…document truncated for compilation…]"

    # 1. Build context: index listing + top-K relevant pages by source embedding.
    #    Context is scoped — compiler only sees pages in the same scope.
    wiki_index_md = await _render_wiki_index(session, scope_type=src_scope_type, scope_id=src_scope_id)
    relevant_md = await _render_relevant_pages(
        session, embedding_provider, full_text, knowledge_type_slug,
        scope_type=src_scope_type, scope_id=src_scope_id,
    )
    kt_context = _format_kt_context(knowledge_type_name, knowledge_type_description)

    prompt = PROMPT_TEMPLATE.format(
        kt_context=kt_context,
        doc_title=source.title or source.file_name or str(source.id),
        wiki_index=wiki_index_md or "_(empty)_",
        relevant_pages=relevant_md or "_(none)_",
        document_text=truncated_text,
    )

    # 2. Call LLM. Low temperature for structured output reliability.
    try:
        raw = await llm.generate(prompt=prompt, temperature=0.2)
    except Exception as e:
        logger.warning(f"Wiki compile LLM call failed for source {source.id}: {e}")
        return {"pages_created": 0, "pages_updated": 0, "log_entry": ""}

    operations = _parse_operations(raw)
    if not operations:
        logger.warning(f"Wiki compile produced no operations for source {source.id}")
        return {"pages_created": 0, "pages_updated": 0, "log_entry": ""}

    # 2b. Strip any hallucinated image:// UUIDs from content_md before persisting.
    allowed_image_ids = await _load_source_image_ids(session, source.id)
    _sanitize_image_markers(operations, allowed_image_ids, source_id=source.id)

    # 3. Apply operations — all within the source's scope.
    created = 0
    updated = 0
    log_entry = ""
    touched_slugs: list[str] = []

    for op in operations:
        kind = op.get("op")
        try:
            if kind == "create":
                slug = _validate_slug(op.get("slug"))
                if not slug:
                    continue
                    
                # Acquire advisory lock for this slug to prevent race conditions
                from sqlalchemy import func, select
                await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(slug))))

                if await wiki_service.get_page_by_slug(
                    session, slug, scope_type=src_scope_type, scope_id=src_scope_id
                ) is not None:
                    # Slug collision in same scope — fall through to update.
                    await _apply_update(
                        session, op, source, knowledge_type_slug,
                        scope_type=src_scope_type, scope_id=src_scope_id,
                    )
                    updated += 1
                else:
                    try:
                        # Use a savepoint so IntegrityError doesn't poison the session
                        async with session.begin_nested():
                            await wiki_service.apply_create(
                                session,
                                slug=slug,
                                title=str(op.get("title") or slug.split("/")[-1]),
                                page_type=str(op.get("page_type") or "concept"),
                                content_md=str(op.get("content_md") or ""),
                                summary=str(op.get("summary") or ""),
                                knowledge_type_slugs=[knowledge_type_slug] if knowledge_type_slug else [],
                                source_ids=[source.id],
                                scope_type=src_scope_type,
                                scope_id=src_scope_id,
                            )
                        created += 1
                    except IntegrityError:
                        # Race condition: another task created this slug concurrently.
                        # Fallback to update.
                        logger.info(f"Wiki compile: slug '{slug}' created concurrently, falling back to update")
                        await _apply_update(
                            session, op, source, knowledge_type_slug,
                            scope_type=src_scope_type, scope_id=src_scope_id,
                        )
                        updated += 1
                touched_slugs.append(slug)

            elif kind == "update":
                slug = _validate_slug(op.get("slug"))
                if not slug:
                    continue
                    
                # Acquire advisory lock for this slug
                from sqlalchemy import func, select
                await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(slug))))

                applied = await _apply_update(
                    session, op, source, knowledge_type_slug,
                    scope_type=src_scope_type, scope_id=src_scope_id,
                )
                if applied:
                    updated += 1
                    touched_slugs.append(slug)

            elif kind == "log":
                log_entry = str(op.get("entry") or "").strip()

            else:
                logger.debug(f"Skipping unknown wiki op: {op!r}")

        except Exception as e:
            logger.warning(f"Failed to apply wiki op {op!r}: {e}")
            continue

    # 4. Re-embed touched pages (batch).
    if touched_slugs:
        await _reembed_pages(session, embedding_provider, touched_slugs, scope_type=src_scope_type, scope_id=src_scope_id)

    # 5. Regenerate the catalog and append a log line (scoped).
    if created or updated:
        await wiki_service.regenerate_index(session, scope_type=src_scope_type, scope_id=src_scope_id)
    final_log = log_entry or (
        f"ingested {source.title or source.file_name or source.id}: "
        f"+{created} pages, ~{updated} updated"
    )
    await wiki_service.append_log(session, final_log)

    logger.info(
        f"Wiki compile done for source {source.id}: "
        f"created={created} updated={updated}"
    )
    return {"pages_created": created, "pages_updated": updated, "log_entry": final_log}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

async def _apply_update(
    session: AsyncSession,
    op: dict[str, Any],
    source: Source,
    knowledge_type_slug: Optional[str],
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> Optional[WikiPage]:
    """Translate a single 'update' op into a wiki_service.apply_update call."""
    slug = _validate_slug(op.get("slug"))
    if not slug:
        return None
    new_content = op.get("new_content_md") or op.get("content_md") or ""
    return await wiki_service.apply_update(
        session,
        slug=slug,
        new_content_md=str(new_content),
        summary=str(op["summary"]) if op.get("summary") is not None else None,
        title=str(op["title"]) if op.get("title") is not None else None,
        add_knowledge_type_slug=knowledge_type_slug,
        add_source_id=source.id,
        scope_type=scope_type,
        scope_id=scope_id,
    )


async def _load_source_image_ids(session: AsyncSession, source_id: uuid.UUID) -> set[str]:
    """Return the set of image UUIDs (lowercased str) belonging to this source."""
    result = await session.execute(
        select(SourceImage.id).where(SourceImage.source_id == source_id)
    )
    return {str(row[0]).lower() for row in result.all()}


def _sanitize_image_markers(
    operations: list[dict[str, Any]],
    allowed_ids: set[str],
    source_id: uuid.UUID,
) -> None:
    """Remove `image://<uuid>` markers whose UUID isn't in allowed_ids.

    LLMs occasionally hallucinate IDs or strip the alt text into something that
    breaks markdown — strip those rather than persisting a broken reference.
    Mutates the operations list in place. Markers with valid UUIDs are kept
    verbatim.
    """
    dropped = 0
    for op in operations:
        for key in ("content_md", "new_content_md"):
            content = op.get(key)
            if not isinstance(content, str) or "image://" not in content:
                continue

            def _replace(match: re.Match[str]) -> str:
                nonlocal dropped
                uuid_str = match.group(1).lower()
                if uuid_str in allowed_ids:
                    return match.group(0)
                dropped += 1
                return ""

            op[key] = _IMAGE_MARKER_RE.sub(_replace, content)

    if dropped:
        logger.warning(
            f"Wiki compile (source {source_id}): dropped {dropped} invalid "
            f"image markers from LLM output"
        )


def _validate_slug(slug: Any) -> Optional[str]:
    """Return a clean slug or None if invalid. Reserved slugs are rejected."""
    if not isinstance(slug, str):
        return None
    s = slug.strip().lower()
    if not s or s in (wiki_service.INDEX_SLUG, wiki_service.LOG_SLUG):
        return None
    if not _SLUG_RE.match(s):
        return None
    return s


def _format_kt_context(name: Optional[str], description: Optional[str]) -> str:
    if not name:
        return ""
    line = f'Document category: "{name}"'
    if description:
        line += f" — {description}"
    line += (
        "\nFavor entity/concept slugs and labels that fit this category. "
        "Reuse existing pages when the same entities appear under this category."
    )
    return line


async def _render_wiki_index(
    session: AsyncSession,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> str:
    """Render existing pages as `slug — summary` lines, capped. Scoped."""
    from cygnus.runtime.services.wiki_service import _scope_filter
    stmt = (
        select(WikiPage.slug, WikiPage.page_type, WikiPage.summary)
        .where(
            WikiPage.slug.notin_([wiki_service.INDEX_SLUG, wiki_service.LOG_SLUG]),
            _scope_filter(scope_type, scope_id),
        )
        .order_by(WikiPage.page_type, WikiPage.slug)
        .limit(MAX_INDEX_PAGES_LISTED)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return ""
    return "\n".join(
        f"- {r.slug} ({r.page_type}) — {r.summary or ''}".rstrip(" —")
        for r in rows
    )


async def _render_relevant_pages(
    session: AsyncSession,
    embedding_provider,
    full_text: str,
    knowledge_type_slug: Optional[str],
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> str:
    """Embed the source's leading text and pick top-K most-relevant existing pages. Scoped."""
    sample = full_text[:6000]
    if not sample.strip():
        return ""
    try:
        query_emb = await embedding_provider.embed(sample)
    except Exception as e:
        logger.debug(f"Wiki compile: failed to embed source for context lookup: {e}")
        return ""

    allowed = [knowledge_type_slug] if knowledge_type_slug else None
    hits = await wiki_service.search_pages_semantic(
        session, query_emb, top_k=TOP_K_RELEVANT, allowed_kt_slugs=allowed,
        scope_type=scope_type, scope_id=scope_id,
    )
    if not hits:
        return ""

    parts: list[str] = []
    for page, sim in hits:
        body = page.content_md or ""
        if len(body) > 2000:
            body = body[:2000] + "\n\n[…page truncated…]"
        parts.append(
            f"### {page.slug} (similarity={sim:.2f})\n\n{body}"
        )
    return "\n\n---\n\n".join(parts)


def _parse_operations(raw: str) -> list[dict[str, Any]]:
    """
    Tolerantly extract the operations array from an LLM response. Handles
    optional ```json fences and trailing prose.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the largest JSON object in the response.
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"Wiki compile: could not parse JSON: {e}; head={text[:200]!r}")
            return []

    if isinstance(data, dict):
        ops = data.get("operations")
    elif isinstance(data, list):
        ops = data
    else:
        ops = None
    return [op for op in (ops or []) if isinstance(op, dict)]


async def _reembed_pages(
    session: AsyncSession,
    embedding_provider,
    slugs: list[str],
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> None:
    """Re-embed all pages in `slugs` within the given scope in one batch.

    Vectors are written to the per-dimension `wiki_page_embeddings_<dim>` table
    matching the active embedding model's spec (looked up via ProviderRegistry).
    """
    from cygnus.runtime.ai.registry import ProviderRegistry
    from cygnus.runtime.services.embedding_storage import (
        compute_content_hash,
        embedding_input_text,
        upsert_page_embedding,
    )
    from cygnus.runtime.services.wiki_service import _scope_filter

    unique = list(dict.fromkeys(slugs))
    if not unique:
        return
    rows = (await session.execute(
        select(WikiPage).where(
            WikiPage.slug.in_(unique),
            _scope_filter(scope_type, scope_id),
        )
    )).scalars().all()
    if not rows:
        return

    registry = ProviderRegistry(session)
    spec_id = await registry.get_active_embedding_spec_id()
    if not spec_id:
        logger.info("No active embedding model — skipping re-embed for compile.")
        return
    from cygnus.runtime.ai.embedding_catalog import get_spec
    spec = get_spec(spec_id)

    inputs = [
        embedding_input_text(p.title, p.summary or "", p.content_md or "")
        for p in rows
    ]
    try:
        vectors = await embedding_provider.embed_batch(inputs)
    except Exception as e:
        logger.warning(f"Wiki compile: re-embed failed for {len(rows)} pages: {e}")
        return

    for page, vec in zip(rows, vectors):
        await upsert_page_embedding(
            session,
            page_id=page.id,
            spec=spec,
            vector=list(vec),
            content_hash=compute_content_hash(
                page.title, page.summary or "", page.content_md or ""
            ),
        )
    await session.flush()
