"""
Wiki Service — CRUD and wikilink graph for WikiPage.

Ownership:
- wiki-page materialization, revision persistence, and wikilink graph maintenance live here
- semantic retrieval and raw-source search live under ``cygnus.retrieval``
- this module owns runtime wiki state, not retrieval ranking truth

The wiki is the LLM-compiled knowledge layer. It replaces chunk-based RAG.
Each page is markdown that may contain `[[slug]]` wikilinks; after every
upsert, refresh_links() re-parses the content and rewrites the wiki_links
edge table so 1-2 hop graph queries (backlinks, neighborhood) stay fast in
PostgreSQL — no separate graph DB needed.

Scope support: every page belongs to a scope (global or workspace). Query
functions accept scope_type/scope_id to isolate results. Default is global.

Semantic retrieval lives under `cygnus.retrieval`; this module owns wiki
materialization, CRUD, and wikilink graph maintenance.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import and_, case, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import WikiLink, WikiPage, WikiPageRevision

# Reserved page slugs — these are regular WikiPage rows but treated specially.
INDEX_SLUG = "_index"
LOG_SLUG = "_log"
HOT_SLUG = "_hot"

# Recognized page types — used for filtering and prompt hints to the compiler.
PAGE_TYPES = {"entity", "concept", "source", "topic", "index", "log", "hot"}

# `[[slug]]` or `[[slug|display text]]` — captures the slug only.
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]*)?]]")

# Default page language when a caller does not specify one. Part of the
# canonical identity (scope_type, scope_id, language, normalized_path).
DEFAULT_PAGE_LANGUAGE = "en"


def normalize_page_path(slug: str) -> str:
    """Canonical identity path for a page slug.

    The DB-enforced identity is keyed on this value, so every write path must
    derive it the same way. The migration backfill uses the SQL equivalent
    ``lower(btrim(slug, E' \\t\\n\\r\\f\\v'))`` — keep both in sync.
    """
    return (slug or "").strip().lower()


def normalize_page_language(language: Optional[str]) -> str:
    """Normalize a page language to its canonical identity form."""
    normalized = (language or DEFAULT_PAGE_LANGUAGE).strip().lower()
    return normalized or DEFAULT_PAGE_LANGUAGE


class PageWriteConflict(Exception):
    """A version-guarded page write found the row at a different version."""

    def __init__(
        self,
        slug: str,
        scope_type: str,
        scope_id: Optional[uuid.UUID],
        expected_version: int,
        actual_version: int,
    ) -> None:
        self.slug = slug
        self.scope_type = scope_type
        self.scope_id = scope_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        scope_label = scope_type if scope_id is None else f"{scope_type}:{scope_id}"
        super().__init__(
            f"Page '{slug}' in {scope_label} is at version {actual_version}, "
            f"not expected version {expected_version}; refresh and retry"
        )


@dataclass(frozen=True)
class PageWriteOutcome:
    """Result of the canonical insert-or-lock-and-version-update write path.

    ``page`` is the materialized row (None when the identity did not exist and
    ``insert_if_missing=False``). ``inserted`` is True when the row was
    created. ``applied`` is False for an exact retry — a write whose payload
    is identical to the committed row — which never bumps the version or
    creates a revision.
    """

    page: Optional[WikiPage]
    inserted: bool = False
    applied: bool = False


# ---------------------------------------------------------------------------
# Scope filter helper
# ---------------------------------------------------------------------------


def _scope_filter(scope_type: str = "global", scope_id: Optional[uuid.UUID] = None):
    """Return SQLAlchemy WHERE clauses for exact scope filtering."""
    if scope_id:
        return and_(WikiPage.scope_type == scope_type, WikiPage.scope_id == scope_id)
    return and_(WikiPage.scope_type == scope_type, WikiPage.scope_id.is_(None))


def _scope_filter_with_dept(department_ids: Optional[list[uuid.UUID]] = None):
    """OR-filter: global pages + department pages visible to the given dept members.

    DEPRECATED for MCP read paths — does NOT include project-scoped pages,
    which made wiki pages of workspaces invisible to their own members. Use
    `_scope_filter_for_identity` instead.
    """
    if department_ids:
        return or_(
            and_(WikiPage.scope_type == "global", WikiPage.scope_id.is_(None)),
            and_(
                WikiPage.scope_type == "department",
                WikiPage.scope_id.in_(department_ids),
            ),
        )
    return _scope_filter("global")


def _scope_filter_for_identity(
    department_ids: Optional[list[uuid.UUID]] = None,
    project_ids: Optional[list[uuid.UUID]] = None,
):
    """OR-filter for the MCP read path: every wiki page the user can see.

    Includes:
      - All global pages.
      - Department pages of every department the user belongs to.
      - Project pages of every workspace the user is a member of.

    Without the project branch, members of a workspace cannot find their own
    workspace's wiki pages via search — they fall through to raw-source
    drill-down and assume the page doesn't exist.
    """
    clauses = [and_(WikiPage.scope_type == "global", WikiPage.scope_id.is_(None))]
    if department_ids:
        clauses.append(
            and_(
                WikiPage.scope_type == "department",
                WikiPage.scope_id.in_(department_ids),
            )
        )
    if project_ids:
        clauses.append(
            and_(WikiPage.scope_type == "project", WikiPage.scope_id.in_(project_ids))
        )
    return or_(*clauses)


def _inverse_scope_filter_for_identity(
    department_ids: Optional[list[uuid.UUID]] = None,
    project_ids: Optional[list[uuid.UUID]] = None,
):
    """Pages OUTSIDE the user's accessible scope — used by out-of-scope hints.

    Excludes global pages (everyone sees those) so the inverse is just:
      - Department pages of departments the user does NOT belong to.
      - Project pages of workspaces the user is NOT a member of.
    """
    project_clause = (
        and_(WikiPage.scope_type == "project", WikiPage.scope_id.notin_(project_ids))
        if project_ids
        else WikiPage.scope_type == "project"
    )
    dept_clause = (
        and_(
            WikiPage.scope_type == "department",
            WikiPage.scope_id.notin_(department_ids),
        )
        if department_ids
        else WikiPage.scope_type == "department"
    )
    return or_(dept_clause, project_clause)


# ---------------------------------------------------------------------------
# Wikilink parsing & graph maintenance
# ---------------------------------------------------------------------------


def extract_wikilinks(content_md: str) -> list[str]:
    """Return the list of slugs referenced by `[[slug]]` patterns, deduped."""
    if not content_md:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _WIKILINK_RE.finditer(content_md):
        slug = match.group(1).strip()
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


async def refresh_links(
    session: AsyncSession,
    from_page_id: uuid.UUID,
    from_slug: str,
    content_md: str,
) -> None:
    """
    Replace all outgoing edges from the page identified by `from_page_id` with
    wikilinks parsed from its current `content_md`. Self-links (matching the
    page's own slug) are dropped to keep the graph sane.
    """
    await session.execute(delete(WikiLink).where(WikiLink.from_page_id == from_page_id))
    targets = [s for s in extract_wikilinks(content_md) if s != from_slug]
    if not targets:
        return
    await session.execute(
        pg_insert(WikiLink)
        .values([{"from_page_id": from_page_id, "to_slug": t} for t in targets])
        .on_conflict_do_nothing()
    )


async def get_backlinks(
    session: AsyncSession,
    slug: str,
    scope_type: Optional[str] = None,
    scope_id: Optional[uuid.UUID] = None,
) -> list[str]:
    """Slugs of pages that link to `slug`.

    If scope filters are given, only return slugs of origin pages in the same
    scope OR in global scope (global referrers are visible from any scope).
    """
    stmt = (
        select(WikiPage.slug)
        .join(WikiLink, WikiLink.from_page_id == WikiPage.id)
        .where(WikiLink.to_slug == slug)
    )
    if scope_type is not None:
        stmt = stmt.where(
            or_(
                and_(WikiPage.scope_type == scope_type, WikiPage.scope_id == scope_id)
                if scope_id is not None
                else and_(
                    WikiPage.scope_type == scope_type, WikiPage.scope_id.is_(None)
                ),
                and_(WikiPage.scope_type == "global", WikiPage.scope_id.is_(None)),
            )
        )
    result = await session.execute(stmt.distinct())
    return [row[0] for row in result.all()]


async def get_outlinks(
    session: AsyncSession,
    slug: str,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> list[str]:
    """Slugs that the page (`slug`, scope) links to."""
    page = await get_page_by_slug(
        session, slug, scope_type=scope_type, scope_id=scope_id
    )
    if page is None:
        return []
    result = await session.execute(
        select(WikiLink.to_slug).where(WikiLink.from_page_id == page.id)
    )
    return [row[0] for row in result.all()]


async def get_neighborhood(
    session: AsyncSession,
    slug: str,
    depth: int = 1,
) -> dict[str, list[dict[str, str]]]:
    """
    Return nodes (slug, title, page_type) and edges within `depth` hops of `slug`.
    Uses an undirected recursive CTE — useful for Obsidian-style graph view.
    """
    depth = max(1, min(depth, 3))  # cap at 3 hops to keep queries cheap
    # Recursive CTE walking both directions over (origin_slug, target_slug)
    # tuples derived from wiki_links joined with wiki_pages on from_page_id.
    # WITH RECURSIVE is required because `walk` self-references inside its
    # own definition. Without the RECURSIVE keyword Postgres treats `walk` as
    # not-yet-defined when it parses the second arm of the UNION, raising
    # `relation "walk" does not exist`. The `edges` non-recursive CTE is
    # allowed in the same WITH clause as long as RECURSIVE is set once.
    cte_sql = text(
        """
        WITH RECURSIVE edges AS (
            SELECT wp.slug AS from_slug, wl.to_slug AS to_slug
            FROM wiki_links wl
            JOIN wiki_pages wp ON wp.id = wl.from_page_id
        ),
        walk(slug, dist) AS (
            SELECT CAST(:start AS varchar), 0
          UNION
            SELECT
              CASE WHEN e.from_slug = w.slug THEN e.to_slug ELSE e.from_slug END,
              w.dist + 1
            FROM walk w
            JOIN edges e
              ON e.from_slug = w.slug OR e.to_slug = w.slug
            WHERE w.dist < :depth
        )
        SELECT DISTINCT slug FROM walk
        """
    )
    rows = await session.execute(cte_sql, {"start": slug, "depth": depth})
    slugs = [r[0] for r in rows.all()]
    if not slugs:
        return {"nodes": [], "edges": []}

    pages_result = await session.execute(
        select(WikiPage.slug, WikiPage.title, WikiPage.page_type).where(
            WikiPage.slug.in_(slugs)
        )
    )
    nodes = [
        {"slug": r.slug, "title": r.title, "page_type": r.page_type}
        for r in pages_result.all()
    ]
    edges_result = await session.execute(
        select(WikiPage.slug.label("from_slug"), WikiLink.to_slug)
        .join(WikiLink, WikiLink.from_page_id == WikiPage.id)
        .where(and_(WikiPage.slug.in_(slugs), WikiLink.to_slug.in_(slugs)))
    )
    edges = [{"from": r.from_slug, "to": r.to_slug} for r in edges_result.all()]
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Page CRUD
# ---------------------------------------------------------------------------


async def get_page_by_slug(
    session: AsyncSession,
    slug: str,
    allowed_kt_slugs: Optional[list[str]] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    language: Optional[str] = None,
) -> Optional[WikiPage]:
    """
    Fetch a page by slug within a specific scope. If `allowed_kt_slugs` is
    given (RBAC), only return the page when it overlaps the allowed set or is
    a reserved slug.

    The canonical identity includes language and en/zh pages may legally
    coexist under one scope/path, so the lookup ALWAYS filters a normalized
    language: ``None`` resolves to the page default (``en``) for legacy
    non-source callers. Compiler/source paths MUST pass the source's explicit
    language tag so a zh source never reads/updates an en page (or vice
    versa) under the same scope/path.
    """
    stmt = select(WikiPage).where(
        WikiPage.slug == slug,
        WikiPage.language == normalize_page_language(language),
        _scope_filter(scope_type, scope_id),
    )
    result = await session.execute(stmt)
    page = result.scalars().first()
    if page is None:
        return None
    if allowed_kt_slugs is None or slug in (INDEX_SLUG, LOG_SLUG, HOT_SLUG):
        return page
    if not page.knowledge_type_slugs:
        return page
    if any(s in allowed_kt_slugs for s in page.knowledge_type_slugs):
        return page
    return None


async def get_page_by_slug_any_scope(
    session: AsyncSession,
    slug: str,
    language: Optional[str] = None,
) -> Optional[WikiPage]:
    """
    Fetch a page by slug across ALL scopes (no scope filtering).
    Used as a fallback when no explicit scope is specified, e.g. global graph view
    clicking on a workspace-scoped wiki page.

    The canonical identity includes language, so the fallback ALWAYS filters a
    normalized language: ``None`` resolves to the page default (``en``) so
    legacy callers keep pre-migration behavior and en/zh pages under one slug
    never resolve nondeterministically.
    """
    stmt = (
        select(WikiPage)
        .where(
            WikiPage.slug == slug,
            WikiPage.language == normalize_page_language(language),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_pages(
    session: AsyncSession,
    page_type: Optional[str] = None,
    knowledge_type_slug: Optional[str] = None,
    allowed_kt_slugs: Optional[list[str]] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    department_ids: Optional[list[uuid.UUID]] = None,
    project_ids: Optional[list[uuid.UUID]] = None,
    all_scopes: bool = False,
) -> list[WikiPage]:
    """List pages with filtering within a scope.

    Scope behaviour:
      - `all_scopes=True`: no scope filter at all (admin bypass).
      - `department_ids` (and optionally `project_ids`) given: union of global
        + every department the user belongs to + every workspace the user is
        a member of.
      - Otherwise: exact `scope_type`/`scope_id` (pipeline write path).
    """
    if all_scopes:
        scope_clause = None
    elif department_ids or project_ids:
        scope_clause = _scope_filter_for_identity(department_ids, project_ids)
    else:
        scope_clause = _scope_filter(scope_type, scope_id)
    stmt = (
        select(WikiPage)
        .where(WikiPage.slug.notin_([INDEX_SLUG, LOG_SLUG, HOT_SLUG]))
        .order_by(WikiPage.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if scope_clause is not None:
        stmt = stmt.where(scope_clause)
    if page_type:
        stmt = stmt.where(WikiPage.page_type == page_type)
    if knowledge_type_slug:
        stmt = stmt.where(WikiPage.knowledge_type_slugs.contains([knowledge_type_slug]))
    if allowed_kt_slugs:
        stmt = stmt.where(
            or_(
                WikiPage.knowledge_type_slugs.overlap(allowed_kt_slugs),
                func.cardinality(WikiPage.knowledge_type_slugs) == 0,
            )
        )
    if query:
        stmt = stmt.where(
            or_(
                WikiPage.title.ilike(f"%{query}%"),
                WikiPage.slug.ilike(f"%{query}%"),
                WikiPage.content_md.ilike(f"%{query}%"),
            )
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Canonical write path
# ---------------------------------------------------------------------------
#
# Every page write — compiler ops, direct edits, rollbacks, reserved pages —
# funnels through write_page(), the single transaction-safe
# insert-or-lock-and-version-update path keyed on the DB-enforced canonical
# identity (scope_type, scope_id, language, normalized_path). See the partial
# unique indexes uq_wiki_pages_canonical_identity_* in the WikiPage model.


async def _lock_page_by_identity(
    session: AsyncSession,
    *,
    slug: str,
    scope_type: str,
    scope_id: Optional[uuid.UUID],
    language: Optional[str],
) -> Optional[WikiPage]:
    """SELECT ... FOR UPDATE on the row owning the canonical identity.

    Serializes concurrent writers on the same (scope, language, path): the
    second writer blocks here until the first commits, then observes the
    committed row. ``populate_existing`` refreshes the ORM object even when a
    caller already holds a (possibly stale) copy in the identity map.
    """
    stmt = (
        select(WikiPage)
        .where(
            WikiPage.scope_type == scope_type,
            WikiPage.language == normalize_page_language(language),
            WikiPage.normalized_path == normalize_page_path(slug),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if scope_id is None:
        stmt = stmt.where(WikiPage.scope_id.is_(None))
    else:
        stmt = stmt.where(WikiPage.scope_id == scope_id)
    result = await session.execute(stmt)
    return result.scalars().first()


def _is_exact_retry(
    page: WikiPage,
    *,
    content_md: str,
    title: Optional[str],
    summary: Optional[str],
    status: Optional[str],
    knowledge_type_slugs: Optional[list[str]],
    source_ids: Optional[list[uuid.UUID]],
) -> bool:
    """True when the write payload is identical to the committed row.

    Only caller-provided fields are compared (None means "preserve" for the
    update branch), so re-delivering the exact same write is a no-op instead
    of a spurious version bump / revision.
    """
    if page.content_md != content_md:
        return False
    if title is not None and page.title != title:
        return False
    if summary is not None and (page.summary or "") != (summary or ""):
        return False
    if status is not None and page.status != status:
        return False
    if knowledge_type_slugs is not None and list(
        page.knowledge_type_slugs or []
    ) != list(knowledge_type_slugs):
        return False
    if source_ids is not None and list(page.source_ids or []) != list(source_ids):
        return False
    return True


async def write_page(
    session: AsyncSession,
    *,
    slug: str,
    title: Optional[str],
    content_md: str,
    summary: Optional[str] = None,
    knowledge_type_slugs: Optional[list[str]] = None,
    source_ids: Optional[list[uuid.UUID]] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    language: Optional[str] = None,
    status: Optional[str] = None,
    expected_version: Optional[int] = None,
    insert_if_missing: bool = True,
    change_type: str = "agent_compile",
    changed_by_id: Optional[uuid.UUID] = None,
    change_note: Optional[str] = None,
    draft_id: Optional[uuid.UUID] = None,
) -> PageWriteOutcome:
    """The single transaction-safe insert-or-lock-and-version-update path.

    Identity is the DB-enforced ``(scope_type, scope_id, language,
    normalized_path)`` triple. The flow:

    1. Try INSERT ... ON CONFLICT DO NOTHING keyed on that identity.
       Concurrent writers block on the unique index, so only one row can ever
       exist per identity.
    2. On conflict, SELECT ... FOR UPDATE the owning row — divergent writes
       serialize here instead of racing read-modify-write.
    3. Under the lock: an exact retry (byte-identical payload) is a no-op; any
       divergence bumps ``version``, writes ``content_md``, refreshes the
       wikilink graph, and appends a ``WikiPageRevision``.

    ``expected_version`` guards the update and raises :class:`PageWriteConflict`
    on mismatch. ``insert_if_missing=False`` runs the lock-and-version-update
    half only and returns ``page=None`` when the identity does not exist.
    ``slug`` is the display/link form; the identity is the normalized path, so
    a casing-only slug change locks the same row without renaming it.
    """
    slug = (slug or "").strip()
    if not slug:
        raise ValueError("slug is required to materialize a wiki page")
    if insert_if_missing and title is None:
        raise ValueError(f"title is required to create page '{slug}'")
    normalized_path = normalize_page_path(slug)
    language = normalize_page_language(language)

    async def _finalize_insert(inserted_id: uuid.UUID) -> WikiPage:
        page = await session.get(WikiPage, inserted_id)
        if page is None:  # pragma: no cover — the row was just inserted
            raise RuntimeError(f"inserted wiki page {inserted_id} disappeared")
        session.add(
            WikiPageRevision(
                page_id=page.id,
                version=1,
                content_md=content_md,
                change_type=change_type,
                draft_id=draft_id,
                changed_by_id=changed_by_id,
                change_note=change_note,
            )
        )
        return page

    page: Optional[WikiPage] = None
    if insert_if_missing:
        insert_stmt = pg_insert(WikiPage).values(
            slug=slug,
            title=title,
            status=status or "seed",
            content_md=content_md,
            summary=summary or "",
            knowledge_type_slugs=list(knowledge_type_slugs or []),
            source_ids=list(source_ids or []),
            scope_type=scope_type,
            scope_id=scope_id,
            language=language,
            normalized_path=normalized_path,
            version=1,
        )
        if scope_id is None:
            insert_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=["scope_type", "language", "normalized_path"],
                index_where=text("scope_id IS NULL"),
            )
        else:
            insert_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=[
                    "scope_type",
                    "scope_id",
                    "language",
                    "normalized_path",
                ],
                index_where=text("scope_id IS NOT NULL"),
            )
        returning_stmt = insert_stmt.returning(WikiPage.id)
        inserted_id = (await session.execute(returning_stmt)).scalar_one_or_none()
        if inserted_id is not None:
            page = await _finalize_insert(inserted_id)
            await refresh_links(session, page.id, slug, content_md)
            await session.flush()
            return PageWriteOutcome(page=page, inserted=True, applied=True)

        page = await _lock_page_by_identity(
            session,
            slug=slug,
            scope_type=scope_type,
            scope_id=scope_id,
            language=language,
        )
        if page is None:
            # The conflicted row was deleted concurrently; retry the insert once.
            inserted_id = (await session.execute(returning_stmt)).scalar_one_or_none()
            if inserted_id is not None:
                page = await _finalize_insert(inserted_id)
                await refresh_links(session, page.id, slug, content_md)
                await session.flush()
                return PageWriteOutcome(page=page, inserted=True, applied=True)
            raise RuntimeError(
                f"canonical identity {scope_type}/{scope_id}/{language}/{normalized_path} "
                "vanished during upsert"
            )
    else:
        page = await _lock_page_by_identity(
            session,
            slug=slug,
            scope_type=scope_type,
            scope_id=scope_id,
            language=language,
        )
        if page is None:
            return PageWriteOutcome(page=None, inserted=False, applied=False)

    if expected_version is not None and page.version != expected_version:
        raise PageWriteConflict(
            slug, scope_type, scope_id, expected_version, page.version or 0
        )

    if _is_exact_retry(
        page,
        content_md=content_md,
        title=title,
        summary=summary,
        status=status,
        knowledge_type_slugs=knowledge_type_slugs,
        source_ids=source_ids,
    ):
        return PageWriteOutcome(page=page, inserted=False, applied=False)

    page.content_md = content_md
    if title is not None:
        page.title = title
    if summary is not None:
        page.summary = summary
    if status is not None:
        page.status = status
    if knowledge_type_slugs is not None:
        page.knowledge_type_slugs = list(knowledge_type_slugs)
    if source_ids is not None:
        page.source_ids = list(source_ids)
    page.version = (page.version or 1) + 1
    await session.flush()
    await refresh_links(session, page.id, slug, content_md)
    session.add(
        WikiPageRevision(
            page_id=page.id,
            version=page.version,
            content_md=content_md,
            change_type=change_type,
            draft_id=draft_id,
            changed_by_id=changed_by_id,
            change_note=change_note,
        )
    )
    await session.flush()
    return PageWriteOutcome(page=page, inserted=False, applied=True)


# ---------------------------------------------------------------------------
# Compiler ops application
# ---------------------------------------------------------------------------


async def apply_create(
    session: AsyncSession,
    slug: str,
    title: str,
    page_type: str,
    content_md: str,
    summary: str,
    knowledge_type_slugs: list[str],
    source_ids: list[uuid.UUID],
    embedding: Optional[list[float]] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    status: str = "seed",
    language: Optional[str] = None,
) -> WikiPage:
    """Insert a new page in the given scope through the canonical write path.

    The canonical identity (scope_type, scope_id, language, normalized_path)
    is DB-enforced: if a concurrent writer already materialized the same
    identity, this locks that row and applies a versioned update instead of
    raising (an exact retry is a no-op). ``page_type`` and ``embedding`` are
    accepted for backward compatibility and ignored. ``language`` defaults to
    the page default (``en``) for backward compatibility; compiler writes pass
    the source's explicit language tag.
    """
    _ = page_type, embedding
    outcome = await write_page(
        session,
        slug=slug,
        title=title,
        content_md=content_md,
        summary=summary,
        knowledge_type_slugs=knowledge_type_slugs,
        source_ids=source_ids,
        scope_type=scope_type,
        scope_id=scope_id,
        language=language,
        status=status,
    )
    if outcome.page is None:  # pragma: no cover — write_page always returns a page here
        raise RuntimeError(f"apply_create failed to materialize page '{slug}'")
    return outcome.page


async def apply_update(
    session: AsyncSession,
    slug: str,
    new_content_md: str,
    summary: Optional[str] = None,
    title: Optional[str] = None,
    add_knowledge_type_slug: Optional[str] = None,
    add_source_id: Optional[uuid.UUID] = None,
    embedding: Optional[list[float]] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    language: Optional[str] = None,
) -> Optional[WikiPage]:
    """
    Update an existing page atomically within the given scope through the
    canonical write path:
      - Replace content_md with new_content_md.
      - Optionally update title/summary/lifecycle status.
      - Union add_knowledge_type_slug into knowledge_type_slugs.
      - Append add_source_id to source_ids if not present.
      - Bump version and append a revision; an exact retry (identical payload)
        is a no-op instead of a spurious version bump.
    Returns None if the page does not exist. ``language`` (default ``en``)
    selects the canonical identity the update applies to; compiler writes pass
    the source's explicit language so zh pages are never confused with en
    pages under the same scope/path.
    """
    _ = embedding  # backward-compat parameter, ignored (see write_page)
    existing = await get_page_by_slug(
        session, slug, scope_type=scope_type, scope_id=scope_id, language=language
    )
    kt_slugs: Optional[list[str]] = None
    source_uuids: Optional[list[uuid.UUID]] = None
    if existing is not None:
        kt_slugs = list(existing.knowledge_type_slugs or [])
        if add_knowledge_type_slug and add_knowledge_type_slug not in kt_slugs:
            kt_slugs.append(add_knowledge_type_slug)
        source_uuids = list(existing.source_ids or [])
        if add_source_id and add_source_id not in source_uuids:
            source_uuids.append(add_source_id)
    outcome = await write_page(
        session,
        slug=slug,
        title=title,
        content_md=new_content_md,
        summary=summary,
        knowledge_type_slugs=kt_slugs,
        source_ids=source_uuids,
        scope_type=scope_type,
        scope_id=scope_id,
        language=language,
        status=status,
        insert_if_missing=False,
    )
    return outcome.page


async def upsert_page(
    session: AsyncSession,
    slug: str,
    title: str,
    page_type: str,
    content_md: str,
    summary: str,
    knowledge_type_slugs: list[str],
    source_ids: list[uuid.UUID],
    embedding: Optional[list[float]] = None,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    language: Optional[str] = None,
) -> WikiPage:
    """Create-or-update by canonical identity within a scope.

    Delegates to the canonical write path; concurrent divergent writers
    serialize on the identity row lock.
    """
    _ = page_type, embedding
    outcome = await write_page(
        session,
        slug=slug,
        title=title,
        content_md=content_md,
        summary=summary,
        knowledge_type_slugs=knowledge_type_slugs,
        source_ids=source_ids,
        scope_type=scope_type,
        scope_id=scope_id,
        language=language,
        status=status,
    )
    if outcome.page is None:  # pragma: no cover — write_page always returns a page here
        raise RuntimeError(f"upsert_page failed to materialize page '{slug}'")
    return outcome.page


# ---------------------------------------------------------------------------
# Reserved pages: _index and _log
# ---------------------------------------------------------------------------


async def regenerate_index(
    session: AsyncSession,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> WikiPage:
    """
    Rebuild the `_index` page within the given scope.
    Grouped by page_type, alphabetical within group. Excludes reserved slugs.
    """
    stmt = (
        select(WikiPage.slug, WikiPage.title, WikiPage.page_type, WikiPage.summary)
        .where(
            WikiPage.slug.notin_([INDEX_SLUG, LOG_SLUG, HOT_SLUG]),
            _scope_filter(scope_type, scope_id),
        )
        .order_by(WikiPage.page_type, WikiPage.title)
    )
    rows = (await session.execute(stmt)).all()

    by_type: dict[str, list[tuple[str, str, str]]] = {}
    for r in rows:
        by_type.setdefault(r.page_type, []).append((r.slug, r.title, r.summary or ""))

    lines = ["# Wiki Index", ""]
    if not by_type:
        lines.append("_(empty — no pages yet)_")
    else:
        for ptype in sorted(by_type.keys()):
            lines.append(f"## {ptype.capitalize()}")
            lines.append("")
            for slug, title, summary in by_type[ptype]:
                summary_part = f" — {summary}" if summary else ""
                lines.append(f"- [[{slug}|{title}]]{summary_part}")
            lines.append("")

    new_md = "\n".join(lines).rstrip() + "\n"
    outcome = await write_page(
        session,
        slug=INDEX_SLUG,
        title="Wiki Index",
        content_md=new_md,
        summary="Catalog of all wiki pages",
        knowledge_type_slugs=[],
        source_ids=[],
        scope_type=scope_type,
        scope_id=scope_id,
        status=None,
    )
    if outcome.page is None:  # pragma: no cover — write_page always returns a page here
        raise RuntimeError(f"regenerate_index failed to materialize '{INDEX_SLUG}'")
    return outcome.page


async def append_log(
    session: AsyncSession,
    entry: str,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> WikiPage:
    """
    Append a timestamped line to the `_log` page within the given scope.

    The append is a single atomic INSERT ... ON CONFLICT DO UPDATE on the
    canonical identity, so concurrent appends serialize at the statement level
    and every line lands on the latest committed content (no read-modify-write
    races that drop lines). A fresh log page starts at version 1; each append
    bumps the version and records a revision.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    line = f"## [{ts}] {entry.strip()}"
    language = normalize_page_language(None)
    normalized_path = normalize_page_path(LOG_SLUG)
    suffix = f"\n\n{line}\n"
    if scope_id is None:
        conflict_index_elements: list[str] = [
            "scope_type",
            "language",
            "normalized_path",
        ]
        conflict_index_where = text("scope_id IS NULL")
    else:
        conflict_index_elements = [
            "scope_type",
            "scope_id",
            "language",
            "normalized_path",
        ]
        conflict_index_where = text("scope_id IS NOT NULL")
    stmt = (
        pg_insert(WikiPage)
        .values(
            slug=LOG_SLUG,
            title="Wiki Log",
            status="seed",
            content_md=f"# Wiki Log\n\n{line}\n",
            summary="Chronological activity log",
            knowledge_type_slugs=[],
            source_ids=[],
            scope_type=scope_type,
            scope_id=scope_id,
            language=language,
            normalized_path=normalized_path,
            version=1,
        )
        .on_conflict_do_update(
            index_elements=conflict_index_elements,
            index_where=conflict_index_where,
            set_={
                # Legacy log rows may carry an empty marker; reset before
                # appending, matching the historical behavior.
                "content_md": case(
                    (
                        WikiPage.content_md.contains("_(empty"),
                        f"# Wiki Log\n\n{line}\n",
                    ),
                    else_=WikiPage.content_md + suffix,
                ),
                "version": WikiPage.version + 1,
                "updated_at": func.now(),
            },
        )
        .returning(WikiPage.id)
    )
    page_id = (await session.execute(stmt)).scalar_one()
    page = await session.get(WikiPage, page_id)
    if page is None:  # pragma: no cover — the row was just written
        raise RuntimeError(f"append_log failed to load '{LOG_SLUG}' page {page_id}")
    await refresh_links(session, page.id, LOG_SLUG, page.content_md or "")
    session.add(
        WikiPageRevision(
            page_id=page.id,
            version=page.version,
            content_md=page.content_md or "",
            change_type="agent_compile",
        )
    )
    await session.flush()
    return page


# ---------------------------------------------------------------------------
# Page deletion — cascade cleanup
# ---------------------------------------------------------------------------


async def delete_page_cascade(
    session: AsyncSession,
    page: WikiPage,
) -> None:
    """
    Delete a wiki page and cascade-cleanup all references:
    1. Delete all outgoing links from this page
    2. Delete all incoming links pointing to this page
    3. Remove [[slug]] and [[slug|text]] wikilinks from pages that reference this one
    4. Delete the page itself

    Caller passes the already-resolved page so we never accidentally fall back
    to a different scope's copy of the same slug.
    """
    slug = page.slug
    del_scope_type = page.scope_type or "global"
    del_scope_id = page.scope_id

    # 1+2: Remove edges. Outgoing edges from this page cascade via FK. Incoming
    # edges (to this slug) are removed only from referrers in the same scope
    # OR from global referrers (which logically point at the deleted page if
    # it is global) — leave edges in other scopes intact because they target
    # *that* scope's same-slug page, not the one we're deleting.
    if del_scope_type == "global":
        # Deleting a global page invalidates ALL [[slug]] references because
        # those links resolve to global by default. Clear all incoming edges.
        await session.execute(delete(WikiLink).where(WikiLink.to_slug == slug))
    else:
        same_scope_pages = select(WikiPage.id).where(
            WikiPage.scope_type == del_scope_type,
            WikiPage.scope_id == del_scope_id,
        )
        await session.execute(
            delete(WikiLink).where(
                WikiLink.to_slug == slug,
                WikiLink.from_page_id.in_(same_scope_pages),
            )
        )

    # 3: Find pages that reference this slug in their content and clean up.
    # Scope the scrub the same way: only rewrite same-scope pages (and globals
    # when deleting a global page).
    ref_stmt = select(WikiPage).where(
        WikiPage.content_md.contains(f"[[{slug}]]")
        | WikiPage.content_md.contains(f"[[{slug}|")
    )
    if del_scope_type != "global":
        ref_stmt = ref_stmt.where(
            WikiPage.scope_type == del_scope_type,
            WikiPage.scope_id == del_scope_id,
        )
    referring_pages = (await session.execute(ref_stmt)).scalars().all()

    for ref_page in referring_pages:
        if ref_page.id == page.id:
            continue
        cleaned = ref_page.content_md or ""
        # Replace [[slug|display]] with just display text
        cleaned = re.sub(
            rf"\[\[{re.escape(slug)}\|([^\]]+)]]",
            r"\1",
            cleaned,
        )
        # Replace [[slug]] with slug text
        cleaned = cleaned.replace(f"[[{slug}]]", slug.split("/")[-1])
        ref_page.content_md = cleaned

    # 4: Delete the page itself
    await session.delete(page)

    await session.flush()
    logger.info(
        f"delete_page_cascade({slug}): deleted page + cleaned {len(referring_pages)} references"
    )


# ---------------------------------------------------------------------------
# Source removal — used when deleting a source
# ---------------------------------------------------------------------------


async def detach_source_from_wiki(
    session: AsyncSession,
    source_id: uuid.UUID,
) -> int:
    """
    Remove `source_id` from every WikiPage.source_ids.
    - Pages that have other contributing sources: keep, just remove this source_id.
    - Pages whose only source was this one: delete immediately.

    Returns the number of pages deleted.
    """
    stmt = select(WikiPage).where(WikiPage.source_ids.contains([source_id]))
    pages = list((await session.execute(stmt)).scalars().all())
    deleted_count = 0
    for page in pages:
        remaining = [sid for sid in (page.source_ids or []) if sid != source_id]
        if not remaining:
            await session.delete(page)
            deleted_count += 1
        else:
            page.source_ids = remaining
    await session.flush()
    if deleted_count:
        logger.info(
            f"detach_source_from_wiki({source_id}): deleted {deleted_count} single-source pages"
        )
    return deleted_count


async def direct_edit_page(
    session: AsyncSession,
    page: WikiPage,
    editor_id: uuid.UUID,
    content_md: str,
    change_note: Optional[str] = None,
) -> WikiPage:
    """
    Sync write by an editor/admin — no review step. Routes through the
    canonical write path: the identity row is locked, the version is bumped,
    and a revision is recorded. Saving the same content is an exact-retry
    no-op instead of a spurious version bump.
    """
    outcome = await write_page(
        session,
        slug=page.slug,
        title=page.title,
        content_md=content_md,
        summary=page.summary,
        knowledge_type_slugs=page.knowledge_type_slugs,
        source_ids=page.source_ids,
        scope_type=page.scope_type or "global",
        scope_id=page.scope_id,
        language=page.language,
        status=page.status,
        insert_if_missing=False,
        change_type="editor_edit",
        changed_by_id=editor_id,
        change_note=change_note,
    )
    if outcome.page is None:
        raise RuntimeError(f"wiki page '{page.slug}' disappeared before direct edit")
    return outcome.page


async def rollback_to_revision(
    session: AsyncSession,
    page: WikiPage,
    target_version: int,
    actor_id: uuid.UUID,
) -> WikiPage:
    """
    Restore a page to a previous revision snapshot through the canonical
    write path, recording a rollback revision. Rolling back to content that
    already matches is an exact-retry no-op.
    """
    revision = (
        await session.execute(
            select(WikiPageRevision).where(
                WikiPageRevision.page_id == page.id,
                WikiPageRevision.version == target_version,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise ValueError(f"Revision v{target_version} not found for page {page.slug}")

    outcome = await write_page(
        session,
        slug=page.slug,
        title=page.title,
        content_md=revision.content_md,
        summary=page.summary,
        knowledge_type_slugs=page.knowledge_type_slugs,
        source_ids=page.source_ids,
        scope_type=page.scope_type or "global",
        scope_id=page.scope_id,
        language=page.language,
        status=page.status,
        insert_if_missing=False,
        change_type="rollback",
        changed_by_id=actor_id,
        change_note=f"rollback to v{target_version}",
    )
    if outcome.page is None:
        raise ValueError(f"Wiki page {page.slug} not found")
    return outcome.page


async def regenerate_hot_cache(
    session: AsyncSession,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> WikiPage:
    """
    Generate or rebuild the dynamic hot cache page (`_hot`) for the given scope.
    It summarizes:
      - The 10 most recently updated pages.
      - A list of active 'seed' pages that need more knowledge.
      - Any detected and unresolved contradictions (pages containing `[!contradiction]`).
    It calls the active LLM to compile this into a dense, high-value briefing.
    """

    # 1. Fetch recent pages
    recent_stmt = (
        select(WikiPage.slug, WikiPage.title, WikiPage.status, WikiPage.updated_at)
        .where(
            WikiPage.slug.notin_([INDEX_SLUG, LOG_SLUG, HOT_SLUG]),
            _scope_filter(scope_type, scope_id),
        )
        .order_by(WikiPage.updated_at.desc())
        .limit(10)
    )
    recent_rows = (await session.execute(recent_stmt)).all()

    # 2. Fetch seed pages
    seed_stmt = (
        select(WikiPage.slug, WikiPage.title)
        .where(
            WikiPage.slug.notin_([INDEX_SLUG, LOG_SLUG, HOT_SLUG]),
            WikiPage.status == "seed",
            _scope_filter(scope_type, scope_id),
        )
        .order_by(WikiPage.title)
        .limit(20)
    )
    seed_rows = (await session.execute(seed_stmt)).all()

    # 3. Fetch contradiction pages
    contradiction_stmt = (
        select(WikiPage.slug, WikiPage.title, WikiPage.content_md)
        .where(
            WikiPage.slug.notin_([INDEX_SLUG, LOG_SLUG, HOT_SLUG]),
            WikiPage.content_md.contains("[!contradiction]"),
            _scope_filter(scope_type, scope_id),
        )
        .order_by(WikiPage.title)
    )
    contradiction_rows = (await session.execute(contradiction_stmt)).all()

    # 4. Format context natively (Zero LLM cost fallback)
    recent_prose = (
        "\n".join(
            f"- [[{r.slug}|{r.title}]] (Status: {r.status}, Updated: {r.updated_at.strftime('%Y-%m-%d %H:%M') if r.updated_at else 'N/A'})"
            for r in recent_rows
        )
        if recent_rows
        else "- No recent updates."
    )
    seed_prose = (
        "\n".join(f"- [[{r.slug}|{r.title}]]" for r in seed_rows)
        if seed_rows
        else "- No seed pages yet."
    )

    contradiction_items = []
    for r in contradiction_rows:
        match = re.search(
            r">\s*\[!contradiction]\s*(.*?)(?=\n[^>]|\n\n|$)",
            r.content_md,
            re.DOTALL | re.IGNORECASE,
        )
        callout_desc = (
            match.group(1).replace(">", "").strip()
            if match
            else "A knowledge contradiction was detected."
        )
        contradiction_items.append(f"- [[{r.slug}|{r.title}]]: {callout_desc}")
    contradiction_prose = (
        "\n".join(contradiction_items)
        if contradiction_items
        else "- No knowledge contradictions detected."
    )

    new_md = f"""# ⚡ Cygnus Hot Knowledge Briefing

*(Auto-generated status briefing for the knowledge system)*

## ⚠️ Active knowledge contradictions
{contradiction_prose}

## 🔄 Recently updated knowledge
{recent_prose}

## 🌱 Seed pages
{seed_prose}
"""

    outcome = await write_page(
        session,
        slug=HOT_SLUG,
        title="Hot Knowledge Briefing",
        content_md=new_md,
        summary="Auto-generated briefing of knowledge updates and contradictions to resolve",
        knowledge_type_slugs=[],
        source_ids=[],
        scope_type=scope_type,
        scope_id=scope_id,
        status="evergreen",
    )
    if outcome.page is None:  # pragma: no cover — write_page always returns a page here
        raise RuntimeError(f"regenerate_hot_cache failed to materialize '{HOT_SLUG}'")
    return outcome.page


async def lint_wiki(
    session: AsyncSession,
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> dict[str, object]:
    """
    Diagnose structural health issues in the wiki:
      - Dead links: wikilinks pointing to non-existent pages in this scope.
      - Orphan pages: pages with zero incoming backlinks.
      - Contradiction nodes: pages containing '[!contradiction]' callouts.
    """
    # 1. Fetch all pages in the current scope
    pages_stmt = select(
        WikiPage.slug, WikiPage.title, WikiPage.id, WikiPage.status
    ).where(_scope_filter(scope_type, scope_id))
    pages_rows = (await session.execute(pages_stmt)).all()
    all_slugs = {r.slug for r in pages_rows}
    slug_to_title = {r.slug: r.title for r in pages_rows}

    # 2. Fetch all links in this scope
    page_ids = [r.id for r in pages_rows]
    links_stmt = select(WikiLink.from_page_id, WikiLink.to_slug)
    if page_ids:
        links_stmt = links_stmt.where(WikiLink.from_page_id.in_(page_ids))
    links_rows = (await session.execute(links_stmt)).all()

    # 3. Find dead links
    dead_links = []
    id_to_slug = {r.id: r.slug for r in pages_rows}
    backlink_counts: dict[str, int] = {slug: 0 for slug in all_slugs}

    for from_page_id, to_slug in links_rows:
        from_slug = id_to_slug.get(from_page_id)
        if not from_slug:
            continue

        is_exist = to_slug in all_slugs

        if not is_exist:
            # Check global scope as fallback
            if scope_type != "global":
                global_exists = (
                    await session.execute(
                        select(WikiPage.id).where(
                            WikiPage.slug == to_slug,
                            WikiPage.scope_type == "global",
                            WikiPage.scope_id.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if global_exists:
                    is_exist = True

        if is_exist:
            if to_slug in backlink_counts:
                backlink_counts[to_slug] += 1
        else:
            if to_slug not in (INDEX_SLUG, LOG_SLUG, HOT_SLUG):
                dead_links.append(
                    {
                        "from_slug": from_slug,
                        "from_title": slug_to_title.get(from_slug, from_slug),
                        "to_slug": to_slug,
                    }
                )

    # 4. Find orphan pages (0 incoming backlinks, excluding reserved pages)
    orphans = []
    for r in pages_rows:
        if r.slug in (INDEX_SLUG, LOG_SLUG, HOT_SLUG):
            continue
        if backlink_counts.get(r.slug, 0) == 0:
            orphans.append({"slug": r.slug, "title": r.title, "status": r.status})

    # 5. Find pages carrying contradictions
    contradictions_stmt = select(WikiPage.slug, WikiPage.title).where(
        WikiPage.content_md.contains("[!contradiction]"),
        _scope_filter(scope_type, scope_id),
    )
    contradictions_rows = (await session.execute(contradictions_stmt)).all()
    contradiction_nodes = [
        {"slug": r.slug, "title": r.title} for r in contradictions_rows
    ]

    return {
        "dead_links": dead_links,
        "orphans": orphans,
        "contradictions": contradiction_nodes,
    }
