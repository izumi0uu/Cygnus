"""Compile source text into durable, reviewable Cygnus wiki drafts.

The compiler may read existing wiki pages to propose a synthesis, but it never
materialises or re-embeds a page itself. Every generated operation is staged as
one deterministic draft; a human review/approval and a separate governed
publication remain required before the content can enter retrieval.
"""

import json
import re
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.ai.registry import ProviderRegistry
from cygnus.runtime.database.models import Source, SourceImage, WikiPage
from cygnus.retrieval import semantic_search as wiki_search
from cygnus.runtime.services import wiki_service

# Match `image://<uuid>` references inside markdown image markers.
_IMAGE_MARKER_RE = re.compile(r"!\[[^\]]*\]\(image://([0-9a-fA-F-]{36})\)")


# Slug must be a-z 0-9 and `/_-` only — kept narrow so they're URL-safe and stable.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_/-]*[a-z0-9]$")

MAX_DOCUMENT_CHARS = 200_000  # truncate very long sources before sending to LLM
MAX_INDEX_PAGES_LISTED = 200  # how many existing pages to enumerate in the prompt
TOP_K_RELEVANT = 8  # how many semantically-relevant pages to show in full


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


class CompilationDraftError(RuntimeError):
    """Raised when a compiler response cannot be durably staged as drafts."""


async def compile_source_into_wiki(
    session: AsyncSession,
    source: Source,
    full_text: str,
    knowledge_type_slug: Optional[str],
    knowledge_type_name: Optional[str],
    knowledge_type_description: Optional[str],
) -> dict:
    """Compile a source into durable drafts within the caller transaction.

    The historical function name remains the internal ingestion seam, but its
    result is explicitly draft counts: generated knowledge does not update a
    ``WikiPage`` or become searchable on this path.
    """
    from cygnus.review.contributions import stage_compilation_wiki_draft
    from cygnus.substrate.source_language import resolve_source_language

    src_scope_type = source.scope_type or "global"
    src_scope_id = source.scope_id
    source_language = resolve_source_language(source)
    registry = ProviderRegistry(session)
    embedding_provider = await registry.get_embedding(task="document")
    llm = await registry.get_llm()

    truncated_text = full_text[:MAX_DOCUMENT_CHARS]
    if len(full_text) > MAX_DOCUMENT_CHARS:
        truncated_text += "\n\n[…document truncated for compilation…]"

    wiki_index_md = await _render_wiki_index(
        session, scope_type=src_scope_type, scope_id=src_scope_id
    )
    relevant_md = await _render_relevant_pages(
        session,
        embedding_provider,
        full_text,
        knowledge_type_slug,
        scope_type=src_scope_type,
        scope_id=src_scope_id,
    )
    prompt = PROMPT_TEMPLATE.format(
        kt_context=_format_kt_context(knowledge_type_name, knowledge_type_description),
        doc_title=source.title or source.file_name or str(source.id),
        wiki_index=wiki_index_md or "_(empty)_",
        relevant_pages=relevant_md or "_(none)_",
        document_text=truncated_text,
    )

    try:
        raw = await llm.generate(prompt=prompt, temperature=0.2)
    except Exception as exc:
        raise CompilationDraftError(
            f"wiki compiler LLM call failed for source {source.id}"
        ) from exc

    operations = _parse_operations(raw)
    if not operations:
        raise CompilationDraftError(
            f"wiki compiler produced no operations for source {source.id}"
        )
    allowed_image_ids = await _load_source_image_ids(session, source.id)
    _sanitize_image_markers(operations, allowed_image_ids, source_id=source.id)

    create_drafts = 0
    edit_drafts = 0
    replayed_drafts = 0
    log_entry = ""
    staged_operation_count = 0

    for op in operations:
        kind = op.get("op")
        if kind == "log":
            log_entry = str(op.get("entry") or "").strip()
            continue
        if kind not in {"create", "update"}:
            raise CompilationDraftError(f"unsupported compiler operation: {kind!r}")

        slug = _validate_slug(op.get("slug"))
        if not slug:
            raise CompilationDraftError("compiler operation has an invalid slug")
        content_key = "content_md" if kind == "create" else "new_content_md"
        content_md = str(op.get(content_key) or op.get("content_md") or "").strip()
        if not content_md:
            raise CompilationDraftError(
                f"compiler operation '{slug}' has no substantive content"
            )

        existing_page = await wiki_service.get_page_by_slug(
            session,
            slug,
            scope_type=src_scope_type,
            scope_id=src_scope_id,
            language=source_language,
        )
        if kind == "update" and existing_page is None:
            raise CompilationDraftError(
                f"compiler update target does not exist: '{slug}'"
            )

        title = str(
            op.get("title")
            or (
                existing_page.title
                if existing_page is not None
                else slug.split("/")[-1]
            )
        ).strip()
        summary = str(
            op.get("summary")
            or (existing_page.summary if existing_page is not None else "")
            or ""
        ).strip()
        page_type = str(
            op.get("page_type")
            or (existing_page.page_type if existing_page is not None else "concept")
        ).strip()

        draft, created = await stage_compilation_wiki_draft(
            session,
            source=source,
            page=existing_page,
            slug=slug,
            title=title,
            page_type=page_type,
            content_md=content_md,
            summary=summary,
            knowledge_type_slug=knowledge_type_slug,
            scope_type=src_scope_type,
            scope_id=src_scope_id,
            language=source_language,
            compiler="legacy",
        )
        _ = draft
        staged_operation_count += 1
        if not created:
            replayed_drafts += 1
        elif existing_page is None:
            create_drafts += 1
        else:
            edit_drafts += 1

    if not staged_operation_count:
        raise CompilationDraftError(
            f"wiki compiler produced no page drafts for source {source.id}"
        )

    final_log = log_entry or (
        f"compiled {source.title or source.file_name or source.id}: "
        f"+{create_drafts} create drafts, +{edit_drafts} edit drafts"
    )
    logger.info(
        f"Wiki compiler staged drafts for source {source.id}: "
        f"created={create_drafts} edits={edit_drafts} replayed={replayed_drafts}"
    )
    return {
        "drafts_created": create_drafts,
        "edit_drafts_created": edit_drafts,
        "drafts_replayed": replayed_drafts,
        "log_entry": final_log,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _load_source_image_ids(
    session: AsyncSession, source_id: uuid.UUID
) -> set[str]:
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
        f"- {r.slug} ({r.page_type}) — {r.summary or ''}".rstrip(" —") for r in rows
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
    hits = await wiki_search.search_pages_semantic(
        session,
        query_emb,
        top_k=TOP_K_RELEVANT,
        allowed_kt_slugs=allowed,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    if not hits:
        return ""

    parts: list[str] = []
    for page, sim in hits:
        body = page.content_md or ""
        if len(body) > 2000:
            body = body[:2000] + "\n\n[…page truncated…]"
        parts.append(f"### {page.slug} (similarity={sim:.2f})\n\n{body}")
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
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            logger.warning(
                f"Wiki compile: could not parse JSON: {e}; head={text[:200]!r}"
            )
            return []

    if isinstance(data, dict):
        ops = data.get("operations")
    elif isinstance(data, list):
        ops = data
    else:
        ops = None
    return [op for op in (ops or []) if isinstance(op, dict)]
