"""
Contribution lifecycle governance for knowledge contributions.

Wraps the two existing artifact types (wiki drafts, skill contributions) behind
a single state machine so transitions emit audit + notifications consistently.
Schema stays separate; this is a governance lifecycle wrapper, not a table merge.

State machine (both artifact types):

        ┌────────────────────────────────────────┐
        │                                        │
        ▼                                        │
    [pending] ─approve──> [approved] (terminal)  │
        │                                        │
        ├─reject────────> [rejected] (terminal)  │
        │                                        │
        ├─request_changes─> [needs_revision] ────┘ (resubmit)
        │                            │
        │                            └─withdraw─> [withdrawn] (terminal)
        │
        └─withdraw─────> [withdrawn] (terminal)

Wiki draft lifecycle plus skill contribution submit / approve / reject
transitions now live here as review-owned governance behavior. Runtime services
still own wiki page CRUD / search and skill package materialization, but the
state-machine ownership for governed knowledge changes belongs here.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.approval_guards import approval_digest
from cygnus.governance.ledger import (
    GovernanceEventType,
    GovernanceLedgerConflict,
    append_draft_event,
    lock_draft_aggregate,
    lock_governance_command,
    record_created_draft,
    record_draft_proposal,
    record_draft_review_request,
    record_draft_update,
    transition_key,
)
from cygnus.runtime.database.models import (
    Employee,
    Skill,
    SkillContribution,
    SkillContributionStatus,
    GovernanceLedgerEvent,
    Source,
    SourceDepartment,
    WikiDraftRound,
    WikiPage,
    WikiPageDraft,
    WikiPageRevision,
)
from cygnus.runtime.services import notification_service, wiki_service
from cygnus.runtime.services.audit_service import log_audit
from cygnus.runtime.services.notification_service import NotificationType
from cygnus.review.pre_review.dispatch import stage_ai_pre_review


# ---------------------------------------------------------------------------
# Wiki draft workflow owned by review governance
# ---------------------------------------------------------------------------


class DraftConflictError(Exception):
    """Raised when a draft's base_version is older than the current page version."""

    def __init__(self, current_version: int, base_version: int):
        self.current_version = current_version
        self.base_version = base_version
        super().__init__(
            f"Draft is based on v{base_version} but the page has advanced to "
            f"v{current_version}. Re-base the draft against the latest content."
        )


class DraftVersionConflict(Exception):
    """Raised when a session draft write races a newer draft content version."""

    def __init__(self, expected_version: int, actual_version: int):
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            "Draft version conflict: "
            f"expected {expected_version}, current {actual_version}."
        )


def build_initial_draft_content(title: str, summary: str) -> str:
    """Build the bounded initial body shared by governed create-draft paths."""
    content = f"# {title}\n\n{summary}"
    if len(content) > 50_000:
        raise ValueError(
            "title and summary together exceed the 50,000 character draft limit"
        )
    return content


async def create_wiki_draft(
    session: AsyncSession,
    page_id: Optional[uuid.UUID],
    author_id: Optional[uuid.UUID],
    content_md: str,
    note: Optional[str] = None,
    source: str = "web_ui",
    source_metadata: Optional[dict[str, Any]] = None,
    base_version: Optional[int] = None,
    draft_kind: str = "edit",
    suggested_metadata: Optional[dict[str, Any]] = None,
    submit_for_review: bool = True,
    draft_id: Optional[uuid.UUID] = None,
) -> WikiPageDraft:
    """Persist a draft, optionally submitting it to the existing review queue.

    Legacy runtime callers retain the historical create-and-submit behavior.
    Session-facing adapters can persist a real ``draft`` first, then invoke
    :func:`submit_wiki_draft` when the author explicitly requests review.

    ``author_id`` is nullable because compiler-originated content has source
    provenance but no human author. A human reviewer/admin must still submit,
    approve, and publish that staged draft through the normal state machine.
    """
    draft = WikiPageDraft(
        id=draft_id or uuid.uuid4(),
        page_id=page_id,
        author_id=author_id,
        content_md=content_md,
        note=note,
        status="pending" if submit_for_review else "draft",
        source=source,
        source_metadata=source_metadata,
        base_version=base_version,
        draft_kind=draft_kind,
        suggested_metadata=suggested_metadata,
    )
    session.add(draft)
    await session.flush()
    if submit_for_review:
        _ = await record_created_draft(session, draft)
        await stage_ai_pre_review(session, draft)
    else:
        _ = await record_draft_proposal(session, draft)
    return draft


class CompilationDraftConflict(Exception):
    """Raised when a compiler retry would change an existing durable draft."""


class CompilationDraftContextConflict(Exception):
    """Raised when source truth changed after a compiler draft was staged."""


def _compiler_draft_identity(
    *,
    source_id: uuid.UUID,
    generation: int,
    scope_type: str,
    scope_id: uuid.UUID | None,
    language: str,
    slug: str,
    page_id: uuid.UUID | None,
) -> str:
    """Return the stable identity for one source-generation compilation unit."""
    return ":".join(
        (
            "compiler-draft",
            str(source_id),
            str(generation),
            scope_type,
            str(scope_id) if scope_id is not None else "global",
            language,
            slug,
            str(page_id) if page_id is not None else "create",
        )
    )


def _compiler_source_ids(page: WikiPage | None, source_id: uuid.UUID) -> list[str]:
    """Union current page provenance with the exact compiling source once."""
    source_ids = [str(item) for item in (page.source_ids or ())] if page else []
    if str(source_id) not in source_ids:
        source_ids.append(str(source_id))
    return source_ids


async def _resolved_source_scope_targets(
    session: AsyncSession,
    source: Source,
) -> tuple[str, ...]:
    """Canonical scope fan-out used to fence compiler drafts at approval."""
    scope_type = (source.scope_type or "global").strip()
    if scope_type in {"department", "project"}:
        if source.scope_id is None:
            return ()
        return (f"{scope_type}:{source.scope_id}",)
    if scope_type != "global" or source.scope_id is not None:
        return ()
    department_ids = tuple(
        (
            await session.execute(
                select(SourceDepartment.department_id)
                .where(SourceDepartment.source_id == source.id)
                .order_by(SourceDepartment.department_id)
            )
        )
        .scalars()
        .all()
    )
    return (
        tuple(f"department:{department_id}" for department_id in department_ids)
        if department_ids
        else ("global",)
    )


async def stage_compilation_wiki_draft(
    session: AsyncSession,
    *,
    source: Any,
    page: WikiPage | None,
    slug: str,
    title: str,
    page_type: str,
    content_md: str,
    summary: str,
    knowledge_type_slug: str | None,
    scope_type: str,
    scope_id: uuid.UUID | None,
    language: str,
    compiler: str,
) -> tuple[WikiPageDraft, bool]:
    """Stage one compiler result as an idempotent, human-reviewable draft.

    A compiler generation is allowed to produce exactly one durable draft for
    each source/scope/language/slug target. A retry returning the same bytes is
    an exact replay; changed bytes or a different base version are rejected
    rather than silently creating a second generated proposal.
    """
    normalized_slug = slug.strip().lower()
    if not normalized_slug:
        raise ValueError("compiler draft slug must not be blank")
    normalized_language = language.strip().lower()
    if not normalized_language:
        raise ValueError("compiler draft language must not be blank")
    body = content_md.strip()
    if not body:
        raise ValueError("compiler draft content must not be blank")

    page_id = page.id if page is not None else None
    base_version = page.version if page is not None else None
    generation = int(getattr(source, "dispatch_generation", 0) or 0)
    identity = _compiler_draft_identity(
        source_id=source.id,
        generation=generation,
        scope_type=scope_type,
        scope_id=scope_id,
        language=normalized_language,
        slug=normalized_slug,
        page_id=page_id,
    )
    draft_id = uuid.uuid5(uuid.NAMESPACE_URL, f"cygnus:{identity}")
    source_ids = _compiler_source_ids(page, source.id)
    proposed_metadata = {
        "title": title.strip(),
        "summary": summary.strip(),
        "knowledge_type_slugs": [knowledge_type_slug]
        if knowledge_type_slug
        else list(page.knowledge_type_slugs or ())
        if page is not None
        else [],
        "language": normalized_language,
    }
    resolved_scope_targets = await _resolved_source_scope_targets(session, source)
    source_metadata = {
        "origin": "compiler",
        "compiler": compiler,
        "compilation_identity": identity,
        "compiler_source_id": str(source.id),
        "compiler_dispatch_generation": generation,
        "compiler_scope_type": scope_type,
        "compiler_scope_id": str(scope_id) if scope_id is not None else None,
        "compiler_language": normalized_language,
        "source_ids": source_ids,
        "compiler_resolved_scope_targets": list(resolved_scope_targets),
        "proposed_metadata": proposed_metadata,
    }
    suggested_metadata = {
        "slug": normalized_slug,
        "title": proposed_metadata["title"],
        "summary": proposed_metadata["summary"],
        "page_type": page_type.strip() or "concept",
        "knowledge_type_slugs": proposed_metadata["knowledge_type_slugs"],
        "scope_type": scope_type,
        "scope_id": str(scope_id) if scope_id is not None else None,
        "language": normalized_language,
    }

    await lock_governance_command(session, identity)
    existing = await session.get(WikiPageDraft, draft_id)
    if existing is not None:
        exact_replay = (
            existing.page_id == page_id
            and existing.draft_kind == ("edit" if page is not None else "create")
            and existing.base_version == base_version
            and existing.content_md == body
            and existing.source_metadata == source_metadata
            and existing.suggested_metadata == suggested_metadata
        )
        if not exact_replay:
            raise CompilationDraftConflict(
                "compiler retry conflicts with the existing durable draft "
                f"for {identity}"
            )
        return existing, False

    draft = await create_wiki_draft(
        session,
        page_id=page_id,
        author_id=getattr(source, "contributed_by_employee_id", None),
        content_md=body,
        source="compiler",
        source_metadata=source_metadata,
        base_version=base_version,
        draft_kind="edit" if page is not None else "create",
        suggested_metadata=suggested_metadata,
        submit_for_review=False,
        draft_id=draft_id,
    )
    return draft, True


def _compiler_metadata_uuid(metadata: dict[str, Any], key: str) -> uuid.UUID:
    raw = metadata.get(key)
    if not isinstance(raw, str):
        raise CompilationDraftContextConflict(
            f"compiler draft is missing {key}; it cannot be approved"
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise CompilationDraftContextConflict(
            f"compiler draft has an invalid {key}; it cannot be approved"
        ) from exc


async def validate_compiler_draft_context(
    session: AsyncSession,
    draft: WikiPageDraft,
    *,
    page: WikiPage | None,
) -> None:
    """Fence compiler drafts against source generation, scope, and language drift."""
    metadata = draft.source_metadata or {}
    if metadata.get("origin") != "compiler":
        return

    source_id = _compiler_metadata_uuid(metadata, "compiler_source_id")
    expected_generation = metadata.get("compiler_dispatch_generation")
    expected_scope_type = metadata.get("compiler_scope_type")
    expected_scope_id_raw = metadata.get("compiler_scope_id")
    expected_language = metadata.get("compiler_language")
    if (
        not isinstance(expected_generation, int)
        or not isinstance(expected_scope_type, str)
        or not isinstance(expected_language, str)
        or not expected_scope_type.strip()
        or not expected_language.strip()
    ):
        raise CompilationDraftContextConflict(
            "compiler draft lacks its immutable source generation/scope/language fence"
        )
    if expected_scope_id_raw is None:
        expected_scope_id = None
    elif isinstance(expected_scope_id_raw, str):
        try:
            expected_scope_id = uuid.UUID(expected_scope_id_raw)
        except ValueError as exc:
            raise CompilationDraftContextConflict(
                "compiler draft has an invalid compiler_scope_id"
            ) from exc
    else:
        raise CompilationDraftContextConflict(
            "compiler draft has an invalid compiler_scope_id"
        )
    expected_scope_targets = metadata.get("compiler_resolved_scope_targets")
    if not isinstance(expected_scope_targets, list) or not all(
        isinstance(value, str) and value for value in expected_scope_targets
    ):
        raise CompilationDraftContextConflict(
            "compiler draft lacks its immutable resolved scope-target fence"
        )

    source = await session.get(Source, source_id)
    if source is None:
        raise CompilationDraftContextConflict(
            "compiler source no longer exists; stage a new draft from current truth"
        )
    if source.dispatch_generation != expected_generation:
        raise CompilationDraftContextConflict(
            "compiler source generation changed; this draft was fenced by re-ingest"
        )
    if (source.language or "").strip().lower() != expected_language.strip().lower():
        raise CompilationDraftContextConflict(
            "compiler source language changed; this draft cannot recreate prior-language content"
        )
    if tuple(expected_scope_targets) != await _resolved_source_scope_targets(
        session, source
    ):
        raise CompilationDraftContextConflict(
            "compiler source scope targets changed; this draft cannot recreate prior audience truth"
        )

    source_scope_type = (source.scope_type or "global").strip()
    if source_scope_type in {"department", "project"} and (
        source_scope_type != expected_scope_type or source.scope_id != expected_scope_id
    ):
        raise CompilationDraftContextConflict(
            "compiler source scope changed; this draft cannot recreate prior-scope content"
        )
    if page is not None and (
        (page.scope_type or "global") != expected_scope_type
        or page.scope_id != expected_scope_id
        or (page.language or "").strip().lower() != expected_language.strip().lower()
    ):
        raise CompilationDraftContextConflict(
            "compiler target page no longer has the staged scope/language identity"
        )


async def invalidate_stale_compiler_drafts(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    current_generation: int,
    reason: str,
) -> tuple[uuid.UUID, ...]:
    """Withdraw pre-reingest compiler drafts for a source in this transaction.

    Call this immediately after advancing ``Source.dispatch_generation`` and
    before committing the scope/language change. Old compiler drafts cannot be
    resubmitted or approved; their source bytes and intended visibility are no
    longer current truth.
    """
    if current_generation < 1:
        raise ValueError("current_generation must be positive")
    rows = (
        (
            await session.execute(
                select(WikiPageDraft)
                .where(
                    WikiPageDraft.source_metadata["origin"].astext == "compiler",
                    WikiPageDraft.source_metadata["compiler_source_id"].astext
                    == str(source_id),
                    WikiPageDraft.status.in_(("draft", "pending", "needs_revision")),
                )
                .order_by(WikiPageDraft.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    invalidated: list[uuid.UUID] = []
    for draft in rows:
        metadata = draft.source_metadata or {}
        generation = metadata.get("compiler_dispatch_generation")
        if not isinstance(generation, int) or generation >= current_generation:
            continue
        previous_state = draft.status
        draft.status = "withdrawn"
        draft.reviewer_note = reason.strip()[:2000]
        await session.flush()
        await append_draft_event(
            session,
            draft_id=draft.id,
            event_type=GovernanceEventType.WITHDRAWN,
            from_state=("in_review" if previous_state == "pending" else previous_state),
            to_state="withdrawn",
            actor_id=None,
            idempotency_key=f"compiler-source-fence:{draft.id}:{current_generation}",
            reason=reason.strip()[:2000],
            payload={
                "compiler_source_id": str(source_id),
                "previous_generation": generation,
                "current_generation": current_generation,
            },
            lock=False,
        )
        invalidated.append(draft.id)
    return tuple(invalidated)


def _draft_source_ids(draft: WikiPageDraft) -> list[uuid.UUID]:
    """Read adapter-persisted source links without inventing source truth."""
    metadata = draft.source_metadata or {}
    raw_source_ids = metadata.get("source_ids")
    if raw_source_ids is None:
        return []
    if not isinstance(raw_source_ids, list):
        raise ValueError("draft source_ids must be a list")

    source_ids: list[uuid.UUID] = []
    for raw_source_id in raw_source_ids:
        if isinstance(raw_source_id, uuid.UUID):
            source_id = raw_source_id
        elif isinstance(raw_source_id, str):
            try:
                source_id = uuid.UUID(raw_source_id)
            except ValueError as exc:
                raise ValueError("draft source_ids must contain UUIDs") from exc
        else:
            raise ValueError("draft source_ids must contain UUIDs")
        if source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


async def update_wiki_draft(
    db: AsyncSession,
    draft: WikiPageDraft,
    author: Employee,
    *,
    expected_version: int,
    content_md: str | None = None,
    suggested_metadata: dict[str, Any] | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> tuple[GovernanceLedgerEvent | None, bool]:
    """Apply one version-checked draft edit without placing it in review."""
    if expected_version < 1:
        raise ValueError("expected_version must be positive")

    await lock_draft_aggregate(db, draft.id)
    await db.refresh(draft)
    if draft.author_id != author.id and author.role != "admin":
        raise InvalidTransition("Only the original author can update this draft.")
    _assert_status(wiki_draft_adapter, draft, ("draft", "needs_revision"))
    if draft.version != expected_version:
        raise DraftVersionConflict(expected_version, draft.version)

    changed = (
        (content_md is not None and content_md != draft.content_md)
        or (
            suggested_metadata is not None
            and suggested_metadata != draft.suggested_metadata
        )
        or source_metadata is not None
        and source_metadata != draft.source_metadata
    )
    if not changed:
        return None, True

    previous_state = draft.status
    previous_version = draft.version
    if previous_state == "needs_revision":
        db.add(
            WikiDraftRound(
                draft_id=draft.id,
                round_no=draft.revision_round or 0,
                content_md=draft.content_md,
                author_note=draft.note,
                reviewer_return_note=draft.last_returned_note,
                ai_check_results=draft.ai_check_results,
                submitted_at=datetime.now(timezone.utc),
            )
        )
        wiki_draft_adapter.bump_revision_round(draft)
        draft.last_returned_note = None
        draft.ai_check_status = "pending"
        draft.ai_check_results = None
        draft.ai_checked_at = None
        wiki_draft_adapter.set_status(draft, "draft")
    if content_md is not None:
        draft.content_md = content_md
    if suggested_metadata is not None:
        draft.suggested_metadata = suggested_metadata
    if source_metadata is not None:
        draft.source_metadata = source_metadata
    draft.version += 1
    await db.flush()
    event = await record_draft_update(
        db,
        draft,
        previous_draft_version=previous_version,
        from_state=previous_state,
        to_state="draft",
        actor_id=author.id,
        action="draft_update",
        lock=False,
    )
    await log_audit(
        db,
        author,
        "update",
        wiki_draft_adapter.artifact_type,
        str(draft.id),
        reason=f"draft_version={draft.version}",
    )
    return event, False


async def submit_wiki_draft(
    db: AsyncSession,
    draft: WikiPageDraft,
    author: Employee,
    *,
    expected_version: int,
    review_type: str,
    notes: str | None,
) -> tuple[GovernanceLedgerEvent, bool]:
    """Move one authored staged draft into review with an idempotent ledger event."""
    if expected_version < 1:
        raise ValueError("expected_version must be positive")

    await lock_draft_aggregate(db, draft.id)
    await db.refresh(draft)
    if draft.page_id is not None:
        draft.page = await db.get(WikiPage, draft.page_id)
    if draft.author_id != author.id and author.role != "admin":
        raise InvalidTransition("Only the original author can request review.")
    if draft.version != expected_version:
        raise DraftVersionConflict(expected_version, draft.version)

    try:
        if draft.status == "pending":
            event = await record_draft_review_request(
                db,
                draft,
                actor_id=author.id,
                reason=notes,
                review_type=review_type,
                expected_version=expected_version,
                lock=False,
            )
            # A repeated request may recover a committed draft whose prior
            # request ended before its post-commit dispatcher ran.
            await stage_ai_pre_review(db, draft)
            return event, True

        _assert_status(wiki_draft_adapter, draft, ("draft",))
        metadata = dict(draft.source_metadata or {})
        metadata["review_type"] = review_type
        draft.source_metadata = metadata
        if notes is not None:
            draft.note = notes
        wiki_draft_adapter.set_status(draft, "pending")
        await db.flush()
        event = await record_draft_review_request(
            db,
            draft,
            actor_id=author.id,
            reason=notes,
            review_type=review_type,
            expected_version=expected_version,
            lock=False,
        )
    except GovernanceLedgerConflict as exc:
        raise InvalidTransition(str(exc)) from exc

    await log_audit(
        db,
        author,
        "submit",
        wiki_draft_adapter.artifact_type,
        str(draft.id),
        reason=f"review_type={review_type}",
    )
    # notify_submitted stages committed-only Wiki pre-review and reviewer fan-out.
    await notify_submitted(db, wiki_draft_adapter, draft, author)
    return event, False


class CreateDraftSlugConflict(Exception):
    """Raised when approving a create-draft whose slug already exists in scope."""

    def __init__(self, slug: str, scope_type: str, scope_id: Optional[uuid.UUID]):
        self.slug = slug
        self.scope_type = scope_type
        self.scope_id = scope_id
        scope_label = scope_type if scope_id is None else f"{scope_type}:{scope_id}"
        super().__init__(
            f"Slug '{slug}' already exists in {scope_label}. "
            "Override final_slug, or have the contributor edit the existing page instead."
        )


def _compiler_proposed_metadata(draft: WikiPageDraft) -> dict[str, Any]:
    """Return compiler-proposed page metadata only when it has the expected shape."""
    metadata = draft.source_metadata or {}
    proposed = metadata.get("proposed_metadata")
    return dict(proposed) if isinstance(proposed, dict) else {}


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata_slug_list(metadata: dict[str, Any]) -> list[str] | None:
    value = metadata.get("knowledge_type_slugs")
    if not isinstance(value, list):
        return None
    return list(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


async def approve_wiki_draft(
    session: AsyncSession,
    draft: WikiPageDraft,
    reviewer_id: uuid.UUID,
    reviewer_note: Optional[str] = None,
    edited_content_md: Optional[str] = None,
    allow_conflict: bool = False,
    metadata_overrides: Optional[dict] = None,
) -> WikiPage:
    """
    Approve a pending draft. Writes the final content to wiki_pages.content_md,
    creates a revision, and marks the draft approved.
    If edited_content_md is provided, that is used instead of the original draft content.

    For draft_kind='create' the page is materialised from
    `draft.suggested_metadata` (or the reviewer-supplied `metadata_overrides`)
    using `apply_create`. The reviewer may override slug / title / page_type /
    knowledge_type_slugs before commit.

    Raises DraftConflictError when an edit draft was authored against an older
    page version than the current one, unless `allow_conflict=True` or
    `edited_content_md` is supplied. Raises CreateDraftSlugConflict when a
    create draft's chosen slug already exists in the target scope.
    """
    final_content = edited_content_md.strip() if edited_content_md else draft.content_md
    proposed_metadata = _compiler_proposed_metadata(draft)
    if draft.status != "pending":
        raise InvalidTransition(
            "A draft must be explicitly submitted for review before approval."
        )

    # Serialise concurrent approves on the same page. Without this, two
    # reviewers clicking Approve on different pending drafts of the same
    # page within the same second can both read page.version=N, both set
    # N+1, and both INSERT a WikiPageRevision(version=N+1) — leaving a
    # duplicate revision row and a non-deterministic last-writer-wins for
    # the page content. Lock by slug (when known) so we don't block the
    # entire page table.
    target_slug: Optional[str] = None
    existing_page: Optional[WikiPage] = None
    if draft.draft_kind == "create":
        target_slug = (draft.suggested_metadata or {}).get("slug")
    else:
        existing_page = (
            await session.get(WikiPage, draft.page_id) if draft.page_id else None
        )
        target_slug = existing_page.slug if existing_page else None
    if target_slug:
        _ = await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(target_slug)))
        )
        # The page row was loaded BEFORE the lock; another reviewer may have
        # bumped its version while we waited. Refresh from DB so version /
        # content_md reflect the committed state inside the critical section.
        if existing_page is not None:
            await session.refresh(existing_page)

    if draft.draft_kind == "create":
        meta = dict(draft.suggested_metadata or {})
        overrides = metadata_overrides or {}
        slug = (overrides.get("final_slug") or meta.get("slug") or "").strip()
        title = (overrides.get("final_title") or meta.get("title") or "").strip()
        page_type = (
            overrides.get("final_page_type") or meta.get("page_type") or "concept"
        )
        kt_raw = (
            overrides.get("final_knowledge_type_slugs")
            if overrides.get("final_knowledge_type_slugs") is not None
            else meta.get("knowledge_type_slugs") or []
        )
        # Reviewer/draft metadata is external input: keep only string slugs so
        # the downstream apply_create list[str] contract stays intact.
        kt_slugs = (
            [s for s in kt_raw if isinstance(s, str)]
            if isinstance(kt_raw, list)
            else []
        )
        summary = _metadata_string(meta, "summary") or ""
        language = _metadata_string(meta, "language") or "en"
        scope_type = meta.get("scope_type") or "global"
        scope_id_raw = meta.get("scope_id")
        try:
            scope_id = (
                uuid.UUID(scope_id_raw)
                if isinstance(scope_id_raw, str)
                else scope_id_raw
            )
        except (ValueError, TypeError):
            scope_id = None
        if scope_id is not None and not isinstance(scope_id, uuid.UUID):
            # Hand-crafted metadata with a non-string non-UUID (e.g. int)
            # shouldn't propagate downstream. Treat as missing scope.
            scope_id = None
        await validate_compiler_draft_context(session, draft, page=None)

        if not slug or slug in (
            wiki_service.INDEX_SLUG,
            wiki_service.LOG_SLUG,
            wiki_service.HOT_SLUG,
        ):
            raise ValueError(f"Invalid slug for new page: '{slug}'")
        if not title:
            raise ValueError("Title is required to materialise a new page")

        existing = await wiki_service.get_page_by_slug(
            session,
            slug,
            scope_type=scope_type,
            scope_id=scope_id,
            language=language,
        )
        if existing is not None:
            raise CreateDraftSlugConflict(slug, scope_type, scope_id)

        page = await wiki_service.apply_create(
            session,
            slug=slug,
            title=title,
            page_type=page_type,
            content_md=final_content,
            summary=summary,
            knowledge_type_slugs=kt_slugs,
            source_ids=_draft_source_ids(draft),
            scope_type=scope_type,
            scope_id=scope_id,
            language=language,
        )
        # apply_create already stages version 1; enrich that same revision
        # instead of violating the unique (page_id, version) invariant.
        await session.flush()
        revision = await session.scalar(
            select(WikiPageRevision).where(
                WikiPageRevision.page_id == page.id,
                WikiPageRevision.version == page.version,
            )
        )
        if revision is None:
            raise RuntimeError("apply_create did not persist its initial revision")
        revision.change_type = "draft_approved_create"
        revision.draft_id = draft.id
        revision.changed_by_id = reviewer_id
        revision.change_note = reviewer_note
        # Backfill draft.page_id so subsequent UI reads can join cleanly.
        draft.page_id = page.id
    else:
        loaded_page = (
            await session.get(WikiPage, draft.page_id) if draft.page_id else None
        )
        if loaded_page is None:
            raise ValueError(f"Wiki page {draft.page_id} not found")
        page = loaded_page
        await validate_compiler_draft_context(session, draft, page=page)

        if (
            not allow_conflict
            and edited_content_md is None
            and draft.base_version is not None
            and page.version is not None
            and draft.base_version < page.version
        ):
            raise DraftConflictError(page.version, draft.base_version)

        proposed_title = _metadata_string(proposed_metadata, "title") or page.title
        proposed_summary = _metadata_string(proposed_metadata, "summary")
        proposed_knowledge_types = _metadata_slug_list(proposed_metadata)
        proposed_source_ids = _draft_source_ids(draft)
        source_ids = list(
            dict.fromkeys([*(page.source_ids or ()), *proposed_source_ids])
        )
        knowledge_type_slugs = (
            list(
                dict.fromkeys(
                    [*(page.knowledge_type_slugs or ()), *proposed_knowledge_types]
                )
            )
            if proposed_knowledge_types is not None
            else page.knowledge_type_slugs
        )
        outcome = await wiki_service.write_page(
            session,
            slug=page.slug,
            title=proposed_title,
            content_md=final_content,
            summary=proposed_summary if proposed_summary is not None else page.summary,
            knowledge_type_slugs=knowledge_type_slugs,
            source_ids=source_ids,
            scope_type=page.scope_type or "global",
            scope_id=page.scope_id,
            language=page.language,
            status=page.status,
            insert_if_missing=False,
            change_type="draft_approved",
            changed_by_id=reviewer_id,
            change_note=reviewer_note,
            draft_id=draft.id,
        )
        if outcome.page is None:
            raise ValueError(f"Wiki page {draft.page_id} not found")
        page = outcome.page

    reviewed_at = datetime.now(timezone.utc)
    draft.status = "approved"
    draft.reviewed_by_id = reviewer_id
    draft.reviewed_at = reviewed_at
    draft.reviewer_note = reviewer_note
    await session.flush()
    canonical_digest = approval_digest(
        draft=draft,
        page=page,
        final_content=final_content,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        reviewer_note=reviewer_note,
    )
    _ = await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.APPROVED,
        from_state="in_review",
        to_state="approved",
        actor_id=reviewer_id,
        idempotency_key=transition_key(draft.id, GovernanceEventType.APPROVED),
        reason=reviewer_note,
        payload={
            "page_id": str(page.id),
            "page_version": page.version,
            "revision_round": draft.revision_round,
            "approval_digest": canonical_digest,
        },
    )
    return page


async def reject_wiki_draft(
    session: AsyncSession,
    draft: WikiPageDraft,
    reviewer_id: uuid.UUID,
    reviewer_note: str,
) -> WikiPageDraft:
    """Reject a pending draft with a required reason."""
    draft.status = "rejected"
    draft.reviewed_by_id = reviewer_id
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewer_note = reviewer_note
    await session.flush()
    _ = await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.REJECTED,
        from_state="in_review",
        to_state="rejected",
        actor_id=reviewer_id,
        idempotency_key=transition_key(draft.id, GovernanceEventType.REJECTED),
        reason=reviewer_note,
        payload={"revision_round": draft.revision_round},
    )
    return draft


class InvalidTransition(Exception):
    """Raised when an attempted state transition is not allowed."""


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class ContributionAdapter(Protocol):
    artifact_type: str  # "wiki_draft" | "skill_contribution"

    def status(self, obj) -> str: ...
    def set_status(self, obj, status: str) -> None: ...
    def author_id(self, obj) -> Optional[uuid.UUID]: ...
    def display_name(self, obj) -> str: ...
    def revision_round(self, obj) -> int: ...
    def bump_revision_round(self, obj) -> None: ...
    def set_returned_note(self, obj, note: Optional[str]) -> None: ...
    async def reviewers(self, db: AsyncSession, obj) -> list[uuid.UUID]: ...

    # Notification type strings for the artifact type
    types: "_TypeBundle"


class _TypeBundle:
    """Notification type strings per event for one artifact."""

    def __init__(
        self,
        submitted: str,
        resubmitted: str,
        approved: str,
        rejected: str,
        changes_requested: str,
        withdrawn: str,
    ):
        self.submitted = submitted
        self.resubmitted = resubmitted
        self.approved = approved
        self.rejected = rejected
        self.changes_requested = changes_requested
        self.withdrawn = withdrawn


# ---------------------------------------------------------------------------
# WikiPageDraft adapter
# ---------------------------------------------------------------------------


class WikiDraftAdapter:
    artifact_type = "wiki_draft"
    types = _TypeBundle(
        submitted=NotificationType.WIKI_DRAFT_SUBMITTED,
        resubmitted=NotificationType.WIKI_DRAFT_RESUBMITTED,
        approved=NotificationType.WIKI_DRAFT_APPROVED,
        rejected=NotificationType.WIKI_DRAFT_REJECTED,
        changes_requested=NotificationType.WIKI_DRAFT_CHANGES_REQUESTED,
        withdrawn=NotificationType.WIKI_DRAFT_WITHDRAWN,
    )

    def status(self, obj: WikiPageDraft) -> str:
        return obj.status

    def set_status(self, obj: WikiPageDraft, status: str) -> None:
        obj.status = status

    def author_id(self, obj: WikiPageDraft) -> Optional[uuid.UUID]:
        return obj.author_id

    def display_name(self, obj: WikiPageDraft) -> str:
        page = obj.page
        if page is None:
            return f"draft {obj.id}"
        return f"{page.title} ({page.slug})"

    def revision_round(self, obj: WikiPageDraft) -> int:
        return obj.revision_round or 0

    def bump_revision_round(self, obj: WikiPageDraft) -> None:
        obj.revision_round = (obj.revision_round or 0) + 1

    def set_returned_note(self, obj: WikiPageDraft, note: Optional[str]) -> None:
        obj.last_returned_note = note

    async def reviewers(self, db: AsyncSession, obj: WikiPageDraft) -> list[uuid.UUID]:
        page: Optional[WikiPage] = obj.page
        if page is None:
            return await notification_service.get_reviewers_for_scope(
                db, "global", None
            )
        return await notification_service.get_reviewers_for_scope(
            db,
            page.scope_type or "global",
            page.scope_id,
        )


# ---------------------------------------------------------------------------
# SkillContribution adapter
# ---------------------------------------------------------------------------


class SkillContributionAdapter:
    artifact_type = "skill_contribution"
    types = _TypeBundle(
        submitted=NotificationType.SKILL_CONTRIBUTION_SUBMITTED,
        resubmitted=NotificationType.SKILL_CONTRIBUTION_RESUBMITTED,
        approved=NotificationType.SKILL_CONTRIBUTION_APPROVED,
        rejected=NotificationType.SKILL_CONTRIBUTION_REJECTED,
        changes_requested=NotificationType.SKILL_CONTRIBUTION_CHANGES_REQUESTED,
        withdrawn=NotificationType.SKILL_CONTRIBUTION_WITHDRAWN,
    )

    def status(self, obj: SkillContribution) -> str:
        return obj.status

    def set_status(self, obj: SkillContribution, status: str) -> None:
        obj.status = status

    def author_id(self, obj: SkillContribution) -> Optional[uuid.UUID]:
        return obj.contributor_id

    def display_name(self, obj: SkillContribution) -> str:
        return obj.title

    def revision_round(self, obj: SkillContribution) -> int:
        return obj.revision_round or 0

    def bump_revision_round(self, obj: SkillContribution) -> None:
        obj.revision_round = (obj.revision_round or 0) + 1

    def set_returned_note(self, obj: SkillContribution, note: Optional[str]) -> None:
        obj.last_returned_note = note

    async def reviewers(
        self, db: AsyncSession, obj: SkillContribution
    ) -> list[uuid.UUID]:
        # Skill contributions currently use the global governance reviewer pool.
        return await notification_service.get_reviewers_for_scope(db, "global", None)


# Singleton instances — adapters are stateless.
wiki_draft_adapter = WikiDraftAdapter()
skill_contribution_adapter = SkillContributionAdapter()


# ---------------------------------------------------------------------------
# State transition helpers
# ---------------------------------------------------------------------------


def _assert_status(adapter: ContributionAdapter, obj, allowed: tuple[str, ...]) -> None:
    current = adapter.status(obj)
    if current not in allowed:
        raise InvalidTransition(
            f"Cannot perform this action while {adapter.artifact_type} is "
            f"in status '{current}'. Allowed: {', '.join(allowed)}."
        )


async def notify_submitted(
    db: AsyncSession,
    adapter: ContributionAdapter,
    obj,
    actor: Employee,
) -> None:
    """Fire when a contribution first enters pending state."""
    # The intent is inserted in this lifecycle transaction; request middleware
    # and worker recovery drain it only after commit.
    if isinstance(obj, WikiPageDraft):
        await stage_ai_pre_review(db, obj)

    recipients = await adapter.reviewers(db, obj)
    await notification_service.notify_many(
        db,
        recipient_ids=recipients,
        type=adapter.types.submitted,
        subject=f"New draft: {adapter.display_name(obj)}",
        body=f"Submitted by {actor.name or actor.email}",
        target_type=adapter.artifact_type,
        target_id=str(obj.id),
        actor_id=actor.id,
    )


async def request_changes(
    db: AsyncSession,
    adapter: ContributionAdapter,
    obj,
    reviewer: Employee,
    note: str,
) -> None:
    """pending → needs_revision. Stores the reviewer note on the artifact."""
    if not note or not note.strip():
        raise InvalidTransition("reviewer_note is required when requesting changes.")
    _assert_status(adapter, obj, ("pending",))
    adapter.set_status(obj, "needs_revision")
    adapter.set_returned_note(obj, note.strip())
    await log_audit(
        db,
        reviewer,
        "request_changes",
        adapter.artifact_type,
        str(obj.id),
        reason=note.strip(),
    )
    if isinstance(obj, WikiPageDraft):
        _ = await append_draft_event(
            db,
            draft_id=obj.id,
            event_type=GovernanceEventType.CHANGES_REQUESTED,
            from_state="in_review",
            to_state="needs_revision",
            actor_id=reviewer.id,
            idempotency_key=transition_key(
                obj.id,
                GovernanceEventType.CHANGES_REQUESTED,
                revision_round=obj.revision_round,
            ),
            reason=note,
            payload={"revision_round": obj.revision_round},
        )
    author_id = adapter.author_id(obj)
    if author_id:
        await notification_service.notify(
            db,
            recipient_id=author_id,
            type=adapter.types.changes_requested,
            subject=f"Changes requested on {adapter.display_name(obj)}",
            body=note.strip(),
            target_type=adapter.artifact_type,
            target_id=str(obj.id),
            actor_id=reviewer.id,
        )


async def resubmit_wiki_draft(
    db: AsyncSession,
    draft: WikiPageDraft,
    author: Employee,
    new_content_md: str,
    author_note: Optional[str] = None,
) -> None:
    """needs_revision → pending. Snapshots prior round and bumps revision_round.

    Wiki-specific because we also append a `wiki_draft_rounds` row capturing
    what the previous submission looked like. Skill contributions snapshot via
    MinIO and aren't covered here.
    """
    await lock_draft_aggregate(db, draft.id)
    await db.refresh(draft)
    adapter = wiki_draft_adapter
    _assert_status(adapter, draft, ("needs_revision",))
    if draft.author_id != author.id and author.role != "admin":
        raise InvalidTransition("Only the original author can resubmit this draft.")

    previous_state = draft.status
    previous_version = draft.version

    # Snapshot the state being replaced — including the AI verdict so the
    # reviewer can compare AI checks across rounds.
    db.add(
        WikiDraftRound(
            draft_id=draft.id,
            round_no=draft.revision_round or 0,
            content_md=draft.content_md,
            author_note=draft.note,
            reviewer_return_note=draft.last_returned_note,
            ai_check_results=draft.ai_check_results,
            submitted_at=datetime.now(timezone.utc),
        )
    )

    draft.content_md = new_content_md
    if author_note is not None:
        draft.note = author_note
    draft.last_returned_note = None
    # Content changed — re-run AI from scratch on the new content.
    draft.ai_check_status = "pending"
    draft.ai_check_results = None
    draft.ai_checked_at = None
    adapter.bump_revision_round(draft)
    draft.version += 1
    adapter.set_status(draft, "pending")
    await db.flush()
    _ = await record_draft_update(
        db,
        draft,
        previous_draft_version=previous_version,
        from_state=previous_state,
        to_state="draft",
        actor_id=author.id,
        action="resubmit",
        reason=author_note,
        lock=False,
    )
    _ = await append_draft_event(
        db,
        draft_id=draft.id,
        event_type=GovernanceEventType.REVIEW_RESUBMITTED,
        from_state="draft",
        to_state="in_review",
        actor_id=author.id,
        idempotency_key=transition_key(
            draft.id,
            GovernanceEventType.REVIEW_RESUBMITTED,
            revision_round=draft.revision_round,
        ),
        reason=author_note,
        payload={"revision_round": draft.revision_round},
        lock=False,
    )
    await stage_ai_pre_review(db, draft)
    await log_audit(
        db,
        author,
        "resubmit",
        adapter.artifact_type,
        str(draft.id),
        reason=f"round {draft.revision_round};draft_version={draft.version}",
    )
    recipients = await adapter.reviewers(db, draft)
    await notification_service.notify_many(
        db,
        recipient_ids=recipients,
        type=adapter.types.resubmitted,
        subject=f"Resubmitted: {adapter.display_name(draft)} (round {draft.revision_round})",
        body=author_note or "",
        target_type=adapter.artifact_type,
        target_id=str(draft.id),
        actor_id=author.id,
    )


async def resubmit_skill_contribution(
    db: AsyncSession,
    contribution: SkillContribution,
    author: Employee,
) -> None:
    """needs_revision → pending for a skill contribution.

    Files are mutated through the existing file endpoints in
    skill_contributions router — calling this just flips the status back to
    pending after the contributor has finished editing.
    """
    adapter = skill_contribution_adapter
    _assert_status(adapter, contribution, ("needs_revision",))
    if contribution.contributor_id != author.id:
        raise InvalidTransition("Only the original contributor can resubmit.")

    contribution.last_returned_note = None
    adapter.bump_revision_round(contribution)
    adapter.set_status(contribution, SkillContributionStatus.PENDING.value)

    await log_audit(
        db,
        author,
        "resubmit",
        adapter.artifact_type,
        str(contribution.id),
        reason=f"round {contribution.revision_round}",
    )
    recipients = await adapter.reviewers(db, contribution)
    await notification_service.notify_many(
        db,
        recipient_ids=recipients,
        type=adapter.types.resubmitted,
        subject=f"Resubmitted: {adapter.display_name(contribution)} (round {contribution.revision_round})",
        target_type=adapter.artifact_type,
        target_id=str(contribution.id),
        actor_id=author.id,
    )


async def submit_skill_contribution(
    db: AsyncSession,
    contribution: SkillContribution,
    author: Employee,
) -> None:
    """draft|needs_revision → pending for a skill contribution."""
    adapter = skill_contribution_adapter
    _assert_status(
        adapter,
        contribution,
        (
            SkillContributionStatus.DRAFT.value,
            SkillContributionStatus.NEEDS_REVISION.value,
        ),
    )
    if contribution.contributor_id != author.id:
        raise InvalidTransition(
            "Only the original contributor can submit this contribution."
        )

    adapter.set_status(contribution, SkillContributionStatus.PENDING.value)
    await log_audit(
        db,
        author,
        "submit",
        adapter.artifact_type,
        str(contribution.id),
    )


async def approve_skill_contribution(
    db: AsyncSession,
    contribution: SkillContribution,
    reviewer: Employee,
    final_scope_type: Optional[str] = None,
    final_scope_ids: Optional[list[uuid.UUID]] = None,
) -> Skill:
    """pending → approved for a skill contribution.

    Runtime skill-version materialization stays in ``SkillService``; this
    function owns the governance transition and its audit trail.
    """
    adapter = skill_contribution_adapter
    _assert_status(adapter, contribution, (SkillContributionStatus.PENDING.value,))

    from cygnus.runtime.services.skill_service import SkillService

    skill = await SkillService.materialize_approved_contribution(
        db,
        contribution,
        final_scope_type=final_scope_type,
        final_scope_ids=final_scope_ids,
    )
    adapter.set_status(contribution, SkillContributionStatus.APPROVED.value)
    contribution.skill_id = skill.id
    await log_audit(
        db,
        reviewer,
        "approve",
        adapter.artifact_type,
        str(contribution.id),
        reason=f"skill:{skill.id}:v{skill.current_version}",
    )
    return skill


async def reject_skill_contribution(
    db: AsyncSession,
    contribution: SkillContribution,
    reviewer: Employee,
) -> None:
    """pending → rejected for a skill contribution."""
    adapter = skill_contribution_adapter
    _assert_status(adapter, contribution, (SkillContributionStatus.PENDING.value,))
    adapter.set_status(contribution, SkillContributionStatus.REJECTED.value)
    await log_audit(
        db,
        reviewer,
        "reject",
        adapter.artifact_type,
        str(contribution.id),
    )


async def withdraw(
    db: AsyncSession,
    adapter: ContributionAdapter,
    obj,
    author: Employee,
) -> None:
    """draft|pending|needs_revision → withdrawn. Author-only unless admin."""
    _assert_status(adapter, obj, ("draft", "pending", "needs_revision"))
    previous_state = adapter.status(obj)
    if author.role != "admin" and adapter.author_id(obj) != author.id:
        raise InvalidTransition(
            "Only the original author can withdraw this contribution."
        )

    adapter.set_status(obj, "withdrawn")
    await log_audit(
        db,
        author,
        "withdraw",
        adapter.artifact_type,
        str(obj.id),
    )
    if isinstance(obj, WikiPageDraft):
        _ = await append_draft_event(
            db,
            draft_id=obj.id,
            event_type=GovernanceEventType.WITHDRAWN,
            from_state=("in_review" if previous_state == "pending" else previous_state),
            to_state="withdrawn",
            actor_id=author.id,
            idempotency_key=transition_key(obj.id, GovernanceEventType.WITHDRAWN),
            payload={"revision_round": obj.revision_round},
        )
    recipients = await adapter.reviewers(db, obj)
    await notification_service.notify_many(
        db,
        recipient_ids=recipients,
        type=adapter.types.withdrawn,
        subject=f"Withdrawn: {adapter.display_name(obj)}",
        target_type=adapter.artifact_type,
        target_id=str(obj.id),
        actor_id=author.id,
    )


# ---------------------------------------------------------------------------
# Notification-only helpers for existing approve / reject paths
# ---------------------------------------------------------------------------


async def notify_approved(
    db: AsyncSession,
    adapter: ContributionAdapter,
    obj,
    reviewer: Employee,
    version_label: Optional[str] = None,
) -> None:
    """Fire after a successful approve. Author gets the good news.

    For wiki drafts we also notify the authors of every OTHER still-pending
    draft on the same page so they know the page has advanced under them —
    their drafts will now flag as having a version conflict on next approve.
    """
    author_id = adapter.author_id(obj)
    if not author_id:
        return
    suffix = f" ({version_label})" if version_label else ""
    await notification_service.notify(
        db,
        recipient_id=author_id,
        type=adapter.types.approved,
        subject=f"Your contribution was approved: {adapter.display_name(obj)}{suffix}",
        body=f"Approved by {reviewer.name or reviewer.email}",
        target_type=adapter.artifact_type,
        target_id=str(obj.id),
        actor_id=reviewer.id,
    )

    # Cross-author awareness for wiki drafts only.
    if isinstance(obj, WikiPageDraft) and obj.page_id is not None:
        from sqlalchemy import select as _select

        sibling_rows = await db.execute(
            _select(WikiPageDraft.author_id, WikiPageDraft.id).where(
                WikiPageDraft.page_id == obj.page_id,
                WikiPageDraft.status == "pending",
                WikiPageDraft.id != obj.id,
            )
        )
        # Group by author so a user with 2 sibling drafts gets 1 notification.
        # Build one batched INSERT via notify_each instead of N round-trips.
        items: list[dict] = []
        seen_authors: set[uuid.UUID] = set()
        body_text = (
            f"{reviewer.name or reviewer.email} approved another draft on "
            "this page. Your draft will flag as conflicting on the next "
            "approve — re-base or withdraw."
        )
        subject_text = (
            f"Page advanced while your draft was pending: "
            f"{adapter.display_name(obj)}{suffix}"
        )
        for sibling_author_id, sibling_id in sibling_rows.all():
            if not sibling_author_id or sibling_author_id == author_id:
                continue
            if sibling_author_id in seen_authors:
                continue
            seen_authors.add(sibling_author_id)
            items.append(
                {
                    "recipient_id": sibling_author_id,
                    "subject": subject_text,
                    "body": body_text,
                    "target_id": str(sibling_id),
                }
            )
        if items:
            await notification_service.notify_each(
                db,
                items=items,
                type=adapter.types.approved,
                target_type=adapter.artifact_type,
                actor_id=reviewer.id,
            )


async def notify_rejected(
    db: AsyncSession,
    adapter: ContributionAdapter,
    obj,
    reviewer: Employee,
    reason: Optional[str] = None,
) -> None:
    """Fire after a reject. Author gets the bad news with the reason."""
    author_id = adapter.author_id(obj)
    if not author_id:
        return
    await notification_service.notify(
        db,
        recipient_id=author_id,
        type=adapter.types.rejected,
        subject=f"Your contribution was rejected: {adapter.display_name(obj)}",
        body=reason or "",
        target_type=adapter.artifact_type,
        target_id=str(obj.id),
        actor_id=reviewer.id,
    )
