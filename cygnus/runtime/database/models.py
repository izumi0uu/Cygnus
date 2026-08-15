"""
SQLAlchemy ORM models for all database tables.

Permission Architecture v2 — Dual-Realm:
  - Global Realm: scoped permissions (doc:read:own_dept, doc:read:all, etc.)
  - Workspace Realm: membership-gated (viewer / contributor / editor / admin)
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from cygnus.substrate.source_language import DEFAULT_SOURCE_LANGUAGE
from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    case,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScopeType(str, PyEnum):
    """Scope for sources/wiki: global or department."""

    GLOBAL = "global"
    DEPARTMENT = "department"


class SkillContributionStatus(str, PyEnum):
    """Status of a skill contribution request."""

    DRAFT = "draft"
    PENDING = "pending"
    NEEDS_REVISION = "needs_revision"
    WITHDRAWN = "withdrawn"
    APPROVED = "approved"
    REJECTED = "rejected"


# Status strings used by WikiPageDraft. Kept as a tuple (not Enum) because the
# column was historically `String(20)` with free-form values; centralising the
# set here lets services validate transitions consistently.
WIKI_DRAFT_STATUSES: tuple[str, ...] = (
    "draft",
    "pending",
    "needs_revision",
    "withdrawn",
    "approved",
    "rejected",
)
AI_PRE_REVIEW_DISPATCH_STATUSES: tuple[str, ...] = (
    "pending",
    "dispatching",
    "enqueued",
    "running",
    "completed",
    "disabled",
    "stale",
    "failed",
)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# ---------------------------------------------------------------------------
# Sources — raw documents (file/URL)
# ---------------------------------------------------------------------------


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[Optional[str]] = mapped_column(String(500))
    full_text: Mapped[Optional[str]] = mapped_column(Text)
    source_type: Mapped[Optional[str]] = mapped_column(String(50))  # "file", "url"
    # --- Scope: global or project (workspace) ---
    scope_type: Mapped[str] = mapped_column(
        String(20),
        default=ScopeType.GLOBAL.value,
        comment="Scope type: global or project",
    )
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Project/workspace ID when scope_type=project. Null for global.",
    )
    # Explicit normalized source language tag (en | zh). Part of the canonical
    # identity of every wiki page compiled from this source: the compiler
    # writes pages under this exact tag. NEVER auto-detected from document
    # content and never silently overwritten — set only from explicit API
    # input; existing rows migrated to 'en' (20260812_08_source_language).
    # Validated via cygnus.substrate.source_language.normalize_source_language.
    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=DEFAULT_SOURCE_LANGUAGE,
        server_default=text("'en'"),
        comment="Explicit normalized source language tag (en|zh); canonical identity for compiled wiki pages.",
    )
    knowledge_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    contributed_by_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(1000))
    url: Mapped[Optional[str]] = mapped_column(String(2000))
    minio_key: Mapped[Optional[str]] = mapped_column(String(500))
    file_name: Mapped[Optional[str]] = mapped_column(String(500))
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[Optional[str]] = mapped_column(String(500))
    job_id: Mapped[Optional[str]] = mapped_column(String(200))
    dispatch_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Monotonic execution generation. Bumped on every new pipeline "
        "cycle (initial ingest, retry, department-change re-ingest). Worker "
        "attempts from an older generation are fenced as stale.",
    )
    delete_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Tombstone: set in the same transaction as the source deletion "
        "intent, before any durable storage object is removed. The source row "
        "is removed only after cleanup completes.",
    )
    extracted_token_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="tiktoken cl100k_base count of full_text. Used by upload gate.",
    )
    auto_recover_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Times sweep_stuck_processing_cron has flipped this source from "
        "'processing' back to 'error'. Reset on successful plan_ready/ready. "
        "Gated by settings.max_auto_recover_attempts.",
    )
    pipeline_strategy: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="single_pass | standard | hierarchical — set by Phase 0 triage",
    )
    pipeline_phase: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="Current MRP phase: map | reduce | plan_review | refine | verify | commit",
    )
    preserve_verbatim: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="If True, skip the LLM wiki pipeline (MRP). The raw full_text is "
        "chunked + embedded as-is into source_chunk_embeddings_<dim> so it is "
        "searchable in the same semantic pool as wiki pages, but never rewritten. "
        "For high-fidelity docs (decrees, official gazettes).",
    )
    # Heading-based TOC tree (PageIndex-style) built at ingest time from extracted markdown.
    # Schema: [{"title": str, "level": int, "page": int, "char_start": int, "char_end": int, "children": [...]}]
    outline_json: Mapped[Optional[list]] = mapped_column(JSONB)
    # Char offset (in full_text) where each extracted page begins.
    # Used by MCP `get_source_pages` to slice raw text by page range.
    page_offsets: Mapped[Optional[list[int]]] = mapped_column(JSONB)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # --- Explicit freshness attestation (governed truth) ---
    # Freshness is never inferred. Only an explicit FRESH attestation carrying
    # actor, reason, attestation time, and a future expiry resolves to FRESH;
    # default/missing/expired always resolve to UNKNOWN. Consumers use
    # cygnus.evidence.freshness.resolve_source_freshness().
    freshness_state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
        comment="Explicit freshness attestation: unknown | fresh | stale. Never inferred.",
    )
    freshness_actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        comment="Employee who recorded the explicit freshness attestation.",
    )
    freshness_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Why the explicit freshness attestation was recorded.",
    )
    freshness_attested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the explicit freshness attestation was recorded.",
    )
    freshness_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When a FRESH attestation lapses; expired attestations are never fresh.",
    )

    # Relationships
    departments: Mapped[list["SourceDepartment"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    knowledge_type: Mapped[Optional["KnowledgeType"]] = relationship()
    contributor: Mapped[Optional["Employee"]] = relationship(
        foreign_keys=[contributed_by_employee_id]
    )

    __table_args__ = (
        CheckConstraint(
            "freshness_state IN ('unknown', 'fresh', 'stale')",
            name="ck_sources_freshness_state",
        ),
        Index("ix_sources_freshness_state", "freshness_state"),
    )


class SourceDepartment(Base):
    """Many-to-many: Source ↔ Department.
    A source with NO rows here is considered Global (visible to all).
    """

    __tablename__ = "source_departments"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="departments")
    department: Mapped["Department"] = relationship(back_populates="source_departments")


class SourceImage(Base):
    """An image extracted from a source document during ingestion.

    Wiki pages reference these by id via `image://<uuid>` markers in content_md.
    The wiki compiler decides which page each image belongs to based on context.
    """

    __tablename__ = "source_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_index: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id", "image_index", name="uq_source_images_source_idx"
        ),
    )

    source: Mapped["Source"] = relationship()


# ---------------------------------------------------------------------------
# MRP Pipeline — MAP/REDUCE/PLAN/REFINE/VERIFY compilation state
# ---------------------------------------------------------------------------


class SourceChunkExtract(Base):
    """Phase 1 MAP output: structured knowledge extracted from one document chunk.

    Each row corresponds to a ~20k-char section of the source document.
    Stored immediately after extraction so the pipeline can resume if interrupted.
    """

    __tablename__ = "source_chunk_extracts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extract_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source_id", "chunk_index", name="uq_sce_source_chunk"),
        Index("ix_sce_source_status", "source_id", "status"),
    )

    source: Mapped["Source"] = relationship()


class SourceCompilationPlan(Base):
    """Phase 2 REDUCE output: compilation plan listing pages to create/update.

    One plan per source. Status flow:
    pending_review → approved (→ in_progress → done) | rejected
    """

    __tablename__ = "source_compilation_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    plan_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending_review"
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_scp_status", "status"),)

    source: Mapped["Source"] = relationship()
    reviewer: Mapped[Optional["Employee"]] = relationship(foreign_keys=[reviewed_by])


# ---------------------------------------------------------------------------
# Wiki — LLM-compiled persistent knowledge layer
# ---------------------------------------------------------------------------


class WikiPage(Base):
    """
    A markdown wiki page maintained by the LLM Wiki Compiler.
    Reserved slugs: '_index' (catalog), '_log' (chronological activity log).
    """

    __tablename__ = "wiki_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="seed",
        comment="Lifecycle status: seed | developing | mature | evergreen",
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # --- Scope: global or project (workspace) ---
    scope_type: Mapped[str] = mapped_column(
        String(20),
        default=ScopeType.GLOBAL.value,
        comment="Scope type: global or project",
    )
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Project/workspace ID. Null for global scope.",
    )
    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
        server_default=text("'en'"),
        comment="Page language (BCP-47-ish); part of the canonical identity.",
    )
    # Canonical identity path derived from the slug via
    # wiki_service.normalize_page_path(). Unique per scope and language — see
    # uq_wiki_pages_canonical_identity_* below. Writers must go through
    # wiki_service.write_page so the identity is always computed the same way.
    normalized_path: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        default="",
        server_default=text("''"),
        comment="Canonical identity path derived from slug; unique per scope and language.",
    )
    knowledge_type_slugs: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
    )
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
    )
    # Embeddings live in per-dimension tables (wiki_page_embeddings_<dim>) so
    # different embedding models with different output sizes can coexist.
    # See cygnus/runtime/ai/embedding_catalog.py and migration 015.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    orphaned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @hybrid_property
    def page_type(self) -> str:
        if self.slug in ("_index", "_log", "_hot"):
            return self.slug.lstrip("_")
        if self.slug.startswith("source/"):
            return "source"
        return "concept"

    @page_type.inplace.expression
    @classmethod
    def _page_type_expression(cls):
        return case(
            (cls.slug == "_index", "index"),
            (cls.slug == "_log", "log"),
            (cls.slug == "_hot", "hot"),
            (cls.slug.like("source/%"), "source"),
            else_="concept",
        )

    __table_args__ = (
        Index("ix_wiki_pages_status", "status"),
        # Canonical identity: a page is uniquely identified by its scope,
        # language, and normalized path. Two partial unique indexes cover the
        # nullable global scope (scope_id IS NULL) — a plain UNIQUE on a
        # nullable column would let unlimited global rows share one identity
        # because Postgres treats NULLs as distinct.
        Index(
            "uq_wiki_pages_canonical_identity_global",
            "scope_type",
            "language",
            "normalized_path",
            unique=True,
            postgresql_where=text("scope_id IS NULL"),
        ),
        Index(
            "uq_wiki_pages_canonical_identity_scoped",
            "scope_type",
            "scope_id",
            "language",
            "normalized_path",
            unique=True,
            postgresql_where=text("scope_id IS NOT NULL"),
        ),
    )


class WikiLink(Base):
    """
    Derived edge from a wiki page to a target slug, parsed from `[[slug]]`
    patterns in content_md. Origin is keyed by page_id so edges are scope-
    disambiguated when the same slug exists in multiple scopes. Target stays
    a slug because dangling links to not-yet-existing pages are valid.
    Refreshed after every page upsert by wiki_service.refresh_links().
    """

    __tablename__ = "wiki_links"

    from_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_slug: Mapped[str] = mapped_column(String(300), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("from_page_id", "to_slug"),
        Index("ix_wiki_links_from_page_id", "from_page_id"),
        Index("ix_wiki_links_to_slug", "to_slug"),
    )


class WikiBranch(Base):
    """
    Named contribution branch grouping multiple page drafts.
    """

    __tablename__ = "wiki_branches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="global"
    )
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    has_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped["Employee"] = relationship("Employee", foreign_keys=[author_id])
    reviewer: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[reviewer_id]
    )
    drafts: Mapped[list["WikiPageDraft"]] = relationship(
        "WikiPageDraft", back_populates="branch", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_wiki_branches_author_id", "author_id"),
        Index("ix_wiki_branches_status", "status"),
    )


class WikiPageDraft(Base):
    """
    Pending contribution proposed by a workspace member.
    An editor/admin reviews and either approves (writing to wiki_pages.content_md)
    or rejects (with a reviewer_note explaining why).
    Multiple drafts per page are allowed — editor resolves all.
    """

    __tablename__ = "wiki_page_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL only when draft_kind='create' — the page is materialised at approval.
    page_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        nullable=True,
    )
    # 'edit' (default): modifies the page referenced by page_id.
    # 'create': proposes a brand new page; suggested_metadata holds slug,
    # title, page_type, knowledge_type_slugs, scope_type, scope_id.
    draft_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="edit")
    suggested_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # version of the target page when this draft was authored; compared at
    # approve-time to detect mid-air collisions (None = pre-migration drafts).
    base_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Monotonic draft-content version used by session-facing optimistic writes.
    # It is distinct from ``base_version``, which protects the target WikiPage.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Increments each time the author resubmits after needs_revision.
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Reviewer's note when sending the draft back for revisions.
    last_returned_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # pending | queued | running | passed | warned | failed | skipped — set by
    # pre-review dispatch and worker.
    ai_check_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # See cygnus/review/pre_review/runner.py for the JSON shape.
    ai_check_results: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ai_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # draft | pending | needs_revision | withdrawn | approved | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # web_ui | mcp_claude_desktop | mcp_claude_code | mcp_other | api_direct
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="web_ui")
    source_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_branches.id", ondelete="CASCADE"),
        nullable=True,
    )
    reviewed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    page: Mapped[Optional["WikiPage"]] = relationship(
        "WikiPage", foreign_keys=[page_id]
    )
    author: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[author_id]
    )
    reviewer: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[reviewed_by_id]
    )
    branch: Mapped[Optional["WikiBranch"]] = relationship(
        "WikiBranch", back_populates="drafts"
    )

    __table_args__ = (
        Index("ix_wiki_drafts_page_id", "page_id"),
        Index("ix_wiki_drafts_status", "status"),
        Index("ix_wiki_drafts_author_id", "author_id"),
        Index("ix_wiki_drafts_branch_id", "branch_id"),
    )


class WikiDraftAiPreReviewDispatch(Base):
    """Durable delivery intent for one exact Wiki draft revision.

    The row is written in the lifecycle transaction and owns every ARQ
    acknowledgement/recovery state.  It is deliberately specific to AI
    pre-review rather than a general-purpose queue abstraction.
    """

    __tablename__ = "wiki_draft_ai_pre_review_dispatches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False)
    # This is stable for the triple above and is passed as ARQ's _job_id.
    job_id: Mapped[str] = mapped_column(String(180), nullable=False)
    # pending | dispatching | enqueued | running | completed | disabled |
    # stale | failed
    dispatch_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    # Number of delivery leases claimed. Enqueue exceptions consume the retry
    # budget; deterministic ARQ duplicate responses are acknowledgements.
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    terminal_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enqueued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "draft_version",
            "revision_round",
            name="uq_wiki_draft_ai_pre_review_dispatch_revision",
        ),
        UniqueConstraint(
            "job_id",
            name="uq_wiki_draft_ai_pre_review_dispatch_job",
        ),
        CheckConstraint(
            "dispatch_status IN ('pending', 'dispatching', 'enqueued', "
            "'running', 'completed', 'disabled', 'stale', 'failed')",
            name="ck_wiki_draft_ai_pre_review_dispatch_status",
        ),
        CheckConstraint(
            "(dispatch_status IN ('pending', 'dispatching', 'enqueued', 'running') "
            "AND terminal_reason IS NULL) OR "
            "(dispatch_status IN ('completed', 'disabled', 'stale', 'failed') "
            "AND terminal_reason IS NOT NULL)",
            name="ck_wiki_draft_ai_pre_review_dispatch_terminal_reason",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_wiki_draft_ai_pre_review_dispatch_attempts",
        ),
        CheckConstraint(
            "draft_version >= 1 AND revision_round >= 0",
            name="ck_wiki_draft_ai_pre_review_dispatch_revision_values",
        ),
        Index(
            "ix_wiki_draft_ai_pre_review_dispatch_recovery",
            "dispatch_status",
            "next_attempt_at",
            "lease_expires_at",
        ),
    )


class WikiPageRevision(Base):
    """
    Immutable snapshot of wiki page content at each version.
    Created on every content-changing operation: agent compile, editor edit,
    draft approval, manual rebuild, rollback.
    """

    __tablename__ = "wiki_page_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    # agent_compile | agent_retry | editor_edit | draft_approved | manual_rebuild | rollback
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="SET NULL"),
        nullable=True,
    )
    changed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_wiki_revisions_page_id", "page_id"),
        # Unique constraint, not just an index — guards against the
        # historical race where two concurrent approves could both INSERT a
        # revision row at the same version. The advisory lock in
        # review.contributions.approve_wiki_draft prevents this in normal operation; this
        # constraint is the DB-level backstop.
        Index("uq_wiki_revisions_page_version", "page_id", "version", unique=True),
    )


class WikiDraftRound(Base):
    """
    Snapshot of a draft's content for one review round. A new row is appended
    every time a reviewer sends the draft back for revisions — capturing the
    content the author had submitted and the note that bounced it back. The
    next author resubmission updates the parent draft and creates the next
    round on the *following* request_changes call.
    """

    __tablename__ = "wiki_draft_rounds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    author_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_return_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # AI verdict at the time this round was sent back — frozen so reviewers
    # can compare AI checks across rounds.
    ai_check_results: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_wiki_draft_rounds_draft_id", "draft_id", "round_no"),)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[Optional[str]] = mapped_column(String(500))
    content: Mapped[Optional[str]] = mapped_column(Text)
    note_type: Mapped[Optional[str]] = mapped_column(String(50))  # "human", "ai"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# App Config (key-value store for settings)
# ---------------------------------------------------------------------------


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Knowledge Types (admin-defined, dynamic)
# ---------------------------------------------------------------------------


class KnowledgeType(Base):
    """
    Admin-defined knowledge type — replaces hardcoded types.
    Examples: SOP, Product, HR Policy, Technical Spec, etc.
    """

    __tablename__ = "knowledge_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        comment="URL-safe identifier, e.g. 'sop', 'product', 'hr-policy'",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Display name, e.g. 'Standard Operating Procedure'",
    )
    color: Mapped[Optional[str]] = mapped_column(
        String(20),
        default="#6366f1",
        comment="Hex color for UI badge",
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# RBAC: Roles, Departments, Employees
# ---------------------------------------------------------------------------


class Department(Base):
    """Organizational department — groups employees and scopes knowledge access."""

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    employee_departments: Mapped[list["EmployeeDepartment"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    employees: Mapped[list["Employee"]] = relationship(
        secondary="employee_departments",
        back_populates="departments",
        viewonly=True,
    )
    source_departments: Mapped[list["SourceDepartment"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )
    skill_departments: Mapped[list["SkillDepartment"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )


class Employee(Base):
    """
    Employee — authenticates via login (JWT) or MCP token.
    Role 'admin' has full access (bypasses all permission checks).
    Role 'employee' access is governed by custom_role permissions.
    """

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="bcrypt hash of password",
    )
    session_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="Monotonic portal JWT revocation version; independent of MCP tokens",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default="employee",
        comment="admin or employee — system-level role",
    )
    global_role: Mapped[str] = mapped_column(
        String(30),
        default="viewer",
        comment="viewer, contributor, knowledge_manager, or admin",
    )
    # Legacy plaintext column — kept nullable for one release so a rollback is
    # possible. The hashed column below is authoritative; new code never reads
    # or writes mcp_token. Drop in a follow-up migration.
    mcp_token: Mapped[Optional[str]] = mapped_column(
        String(500),
        unique=True,
        comment="DEPRECATED — legacy plaintext token, no longer read or written",
    )
    mcp_token_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="HMAC-SHA256(pepper, token) — primary lookup key for MCP auth",
    )
    mcp_token_prefix: Mapped[Optional[str]] = mapped_column(
        String(12),
        nullable=True,
        comment="First 12 chars of the token for UI display (e.g. ark_aBcD…)",
    )
    mcp_token_rotated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_connected: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    employee_departments: Mapped[list["EmployeeDepartment"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    departments: Mapped[list["Department"]] = relationship(
        secondary="employee_departments",
        back_populates="employees",
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "session_version >= 0",
            name="ck_employees_session_version_nonnegative",
        ),
        Index("ix_employees_mcp_token", "mcp_token"),
        Index(
            "ix_employees_mcp_token_hash",
            "mcp_token_hash",
            unique=True,
            postgresql_where=text("mcp_token_hash IS NOT NULL"),
        ),
        Index("ix_employees_email", "email"),
    )

    @property
    def department_ids(self) -> list[uuid.UUID]:
        """All departments this employee belongs to. Empty list = no dept."""
        return [ed.department_id for ed in self.employee_departments]


class EmployeeDepartment(Base):
    """Many-to-many: Employee ↔ Department.

    All departments are equal — there is no concept of a "primary" department.
    `*:*:own_dept` permissions resolve to the union of all departments listed
    here for the employee. An employee with zero rows can only see resources
    scoped to 'global'.
    """

    __tablename__ = "employee_departments"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    employee: Mapped["Employee"] = relationship(back_populates="employee_departments")
    department: Mapped["Department"] = relationship(
        back_populates="employee_departments"
    )

    __table_args__ = (Index("ix_employee_departments_department_id", "department_id"),)


# ---------------------------------------------------------------------------
# AI Skills — Versioned prompt packages and tools
# ---------------------------------------------------------------------------


class Skill(Base):
    """
    An AI Skill package (e.g. 'document-generator').
    Can be scoped to a department or global (NULL department).
    """

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True
    )
    scope_type: Mapped[str] = mapped_column(
        String(20),
        default="global",
        comment="Scope type: global, project, department, team",
    )
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Scope entity ID. Null for global scope.",
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    version_hash: Mapped[Optional[str]] = mapped_column(String(64))
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(
        PgEnum(
            "active",
            "processing",
            "deleting",
            "deprecated",
            "archived",
            name="skill_status",
        ),
        server_default="active",
        nullable=False,
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="True for skills seeded from source code. Immutable via API.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    departments: Mapped[list["SkillDepartment"]] = relationship(
        "SkillDepartment",
        back_populates="skill",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )
    contributions: Mapped[list["SkillContribution"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class SkillDepartment(Base):
    """Many-to-many: Skill ↔ Department.
    A skill with NO rows here is considered Global (visible to all).
    """

    __tablename__ = "skill_departments"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Relationships
    skill: Mapped["Skill"] = relationship(back_populates="departments")
    department: Mapped["Department"] = relationship(back_populates="skill_departments")


class SkillVersion(Base):
    """Specific version of a skill."""

    __tablename__ = "skill_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_hash: Mapped[Optional[str]] = mapped_column(String(64))
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000))
    changelog: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    skill: Mapped["Skill"] = relationship(back_populates="versions")
    author: Mapped[Optional["Employee"]] = relationship()

    __table_args__ = (Index("ix_skill_versions_skill_id", "skill_id"),)


# ---------------------------------------------------------------------------
# Scope-based RBAC: Membership & Audit
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """
    Append-only access decision log.
    Records actions for compliance and debugging.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Employee or agent ID",
    )
    principal_type: Mapped[str] = mapped_column(
        String(20),
        default="human",
        comment="human or agent",
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Action attempted (read, list, delete...)",
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of resource: source, wiki_page, etc.",
    )
    resource_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="UUID or identifier of the resource",
    )
    decision: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="allow or deny",
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        comment="Human-readable reason for the decision",
    )
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        comment="Extra context (IP, user agent, request ID...)",
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Canonical end-to-end request correlation ID (UUID).",
    )
    traceparent: Mapped[Optional[str]] = mapped_column(
        String(55),
        nullable=True,
        comment="W3C traceparent derived from correlation_id.",
    )

    __table_args__ = (
        Index("ix_audit_log_timestamp", "timestamp"),
        Index("ix_audit_log_principal", "principal_id"),
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
        Index("ix_audit_log_correlation_id", "correlation_id"),
    )


# ---------------------------------------------------------------------------
# Governed write ledger and publication truth
# ---------------------------------------------------------------------------


class GovernanceSignal(Base):
    """Durable, scoped input fact compiled into governance review surfaces."""

    __tablename__ = "governance_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_ref: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(320), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    audience_binding_ref: Mapped[Optional[str]] = mapped_column(
        String(220), nullable=True
    )
    audience_filter: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB, nullable=True
    )
    affected_surfaces: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    trigger_signals: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    evidence_source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    freshness: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('ticket_cluster', 'human_rewrite', 'source_failure', "
            "'release_delta', 'incident_delta', 'low_rating', 'stale_answer')",
            name="ck_governance_signals_type",
        ),
        CheckConstraint(
            "status IN ('active', 'resolved', 'dismissed')",
            name="ck_governance_signals_status",
        ),
        CheckConstraint(
            "freshness IN ('fresh', 'stale', 'unknown')",
            name="ck_governance_signals_freshness",
        ),
        CheckConstraint(
            "audience_filter IS NOT NULL OR "
            "(audience_binding_ref IS NOT NULL AND page_id IS NOT NULL)",
            name="ck_governance_signals_audience",
        ),
        CheckConstraint(
            "(status = 'active' AND resolved_at IS NULL) OR "
            "(status <> 'active' AND resolved_at IS NOT NULL)",
            name="ck_governance_signals_resolution",
        ),
        Index(
            "ix_governance_signals_status_observed",
            "status",
            "observed_at",
        ),
        Index("ix_governance_signals_page", "page_id"),
        Index("ix_governance_signals_source", "source_id"),
        Index("ix_governance_signals_object", "object_ref"),
    )


class GovernanceFeedbackSignal(Base):
    """Durable consumption feedback recorded from a governed session."""

    __tablename__ = "governance_feedback_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    command_id: Mapped[str] = mapped_column(String(220), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    audience_context: Mapped[dict[str, str | None]] = mapped_column(
        JSONB, nullable=False
    )
    object_id: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    page_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="RESTRICT"),
        nullable=True,
    )
    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_context_ref: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('answer_accepted', 'human_rewrite', 'escalated', "
            "'low_rating', 'unsupported_answer', 'stale_answer')",
            name="ck_governance_feedback_signals_type",
        ),
        CheckConstraint(
            "command_id = btrim(command_id) "
            "AND char_length(command_id) BETWEEN 1 AND 220",
            name="ck_governance_feedback_signals_command_id",
        ),
        CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_governance_feedback_signals_request_fingerprint",
        ),
        UniqueConstraint(
            "command_id",
            name="uq_governance_feedback_signals_command_id",
        ),
        CheckConstraint(
            "jsonb_typeof(audience_context) = 'object' "
            "AND audience_context ?& ARRAY["
            "'visibility', 'brand', 'product_line', 'plan_tier', 'region', "
            "'language', 'product_version'] "
            "AND audience_context - ARRAY["
            "'visibility', 'brand', 'product_line', 'plan_tier', 'region', "
            "'language', 'product_version'] = '{}'::jsonb "
            "AND jsonb_typeof(audience_context -> 'visibility') = 'string' "
            "AND (audience_context ->> 'visibility') IN ('internal', 'external') "
            "AND (jsonb_typeof(audience_context -> 'brand') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'brand') = 'string' "
            "AND (audience_context ->> 'brand') = "
            "btrim(audience_context ->> 'brand') "
            "AND char_length(audience_context ->> 'brand') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'product_line') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'product_line') = 'string' "
            "AND (audience_context ->> 'product_line') = "
            "btrim(audience_context ->> 'product_line') "
            "AND char_length(audience_context ->> 'product_line') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'plan_tier') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'plan_tier') = 'string' "
            "AND (audience_context ->> 'plan_tier') = "
            "btrim(audience_context ->> 'plan_tier') "
            "AND char_length(audience_context ->> 'plan_tier') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'region') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'region') = 'string' "
            "AND (audience_context ->> 'region') = "
            "btrim(audience_context ->> 'region') "
            "AND char_length(audience_context ->> 'region') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'language') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'language') = 'string' "
            "AND (audience_context ->> 'language') = "
            "btrim(audience_context ->> 'language') "
            "AND char_length(audience_context ->> 'language') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'product_version') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'product_version') = 'string' "
            "AND (audience_context ->> 'product_version') = "
            "btrim(audience_context ->> 'product_version') "
            "AND char_length(audience_context ->> 'product_version') "
            "BETWEEN 1 AND 200))",
            name="ck_governance_feedback_signals_audience_context",
        ),
        CheckConstraint(
            "object_id IS NULL OR (object_id = btrim(object_id) "
            "AND char_length(object_id) BETWEEN 1 AND 320)",
            name="ck_governance_feedback_signals_object_id",
        ),
        CheckConstraint(
            "source_context_ref IS NULL OR (source_context_ref = "
            "btrim(source_context_ref) AND char_length(source_context_ref) "
            "BETWEEN 1 AND 500)",
            name="ck_governance_feedback_signals_source_context_ref",
        ),
        CheckConstraint(
            "notes IS NULL OR (notes = btrim(notes) "
            "AND char_length(notes) BETWEEN 1 AND 10000)",
            name="ck_governance_feedback_signals_notes",
        ),
        Index(
            "ix_governance_feedback_signals_actor_created",
            "actor_id",
            "created_at",
        ),
        Index("ix_governance_feedback_signals_object", "object_id"),
        Index("ix_governance_feedback_signals_page", "page_id"),
        Index("ix_governance_feedback_signals_draft", "draft_id"),
        Index("ix_governance_feedback_signals_correlation_id", "correlation_id"),
    )


class GovernanceToolCommandReceipt(Base):
    """Actor-bound replay receipt for governed session draft writes (CYG-140).

    ``propose_knowledge_object`` / ``update_draft_object`` persist one receipt
    in the same caller-owned transaction as the draft/ledger/audit truth.
    Exact replay returns the stored result; reusing the command id with
    different normalized input or a different actor conflicts without writes.
    """

    __tablename__ = "governance_tool_command_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    command_id: Mapped[str] = mapped_column(String(220), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    result_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "tool_name IN ('propose_knowledge_object', 'update_draft_object')",
            name="ck_governance_tool_command_receipts_tool_name",
        ),
        CheckConstraint(
            "tool_name = btrim(tool_name) AND char_length(tool_name) BETWEEN 1 AND 60",
            name="ck_governance_tool_command_receipts_tool_name_shape",
        ),
        CheckConstraint(
            "command_id = btrim(command_id) "
            "AND char_length(command_id) BETWEEN 1 AND 220",
            name="ck_governance_tool_command_receipts_command_id",
        ),
        CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_governance_tool_command_receipts_fingerprint",
        ),
        UniqueConstraint(
            "actor_id",
            "tool_name",
            "command_id",
            name="uq_governance_tool_command_receipts_actor_tool_command",
        ),
        Index(
            "ix_governance_tool_command_receipts_actor_created",
            "actor_id",
            "created_at",
        ),
        Index("ix_governance_tool_command_receipts_correlation_id", "correlation_id"),
    )


class GovernanceFeedbackRoute(Base):
    """Durable lifecycle-owned work derived from one consumption-feedback signal."""

    __tablename__ = "governance_feedback_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feedback_signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_feedback_signals.id", ondelete="CASCADE"),
        nullable=False,
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    route_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
    lease_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome_signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_signals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    terminal_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "route_kind IN ('review', 'refresh')",
            name="ck_governance_feedback_routes_kind",
        ),
        CheckConstraint(
            "lifecycle_state IN ('queued', 'running', 'completed', 'blocked', "
            "'failed')",
            name="ck_governance_feedback_routes_state",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_governance_feedback_routes_attempts",
        ),
        CheckConstraint(
            "(lifecycle_state = 'queued' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NULL "
            "AND outcome_signal_id IS NULL AND terminal_reason IS NULL) OR "
            "(lifecycle_state = 'running' AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND next_attempt_at IS NULL "
            "AND outcome_signal_id IS NULL AND completed_at IS NULL "
            "AND terminal_reason IS NULL AND last_error IS NULL) OR "
            "(lifecycle_state = 'completed' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND next_attempt_at IS NULL "
            "AND outcome_signal_id IS NOT NULL AND completed_at IS NOT NULL "
            "AND terminal_reason IS NULL AND last_error IS NULL) OR "
            "(lifecycle_state = 'blocked' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND next_attempt_at IS NULL "
            "AND terminal_reason IS NOT NULL AND completed_at IS NOT NULL "
            "AND last_error IS NULL AND outcome_signal_id IS NULL) OR "
            "(lifecycle_state = 'failed' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND next_attempt_at IS NULL "
            "AND terminal_reason IS NOT NULL AND last_error IS NOT NULL "
            "AND completed_at IS NOT NULL AND outcome_signal_id IS NULL)",
            name="ck_governance_feedback_routes_lifecycle",
        ),
        UniqueConstraint(
            "outcome_signal_id",
            name="uq_governance_feedback_routes_outcome_signal",
        ),
        UniqueConstraint(
            "feedback_signal_id",
            "route_kind",
            name="uq_governance_feedback_routes_signal_kind",
        ),
        Index(
            "ix_governance_feedback_routes_queue",
            "lifecycle_state",
            "next_attempt_at",
            "lease_expires_at",
            "created_at",
        ),
        Index("ix_governance_feedback_routes_correlation_id", "correlation_id"),
    )


class GovernanceReviewAssignment(Base):
    """Current durable owner state for one governance review signal."""

    __tablename__ = "governance_review_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_signals.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unassigned", server_default="unassigned"
    )
    owner_ref: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(lifecycle_state = 'unassigned' AND owner_ref IS NULL "
            "AND escalation_reason IS NULL) OR "
            "(lifecycle_state = 'assigned' AND owner_ref IS NOT NULL "
            "AND escalation_reason IS NULL) OR "
            "(lifecycle_state = 'escalated' AND owner_ref IS NOT NULL "
            "AND escalation_reason IS NOT NULL "
            "AND char_length(escalation_reason) BETWEEN 1 AND 2000)",
            name="ck_governance_review_assignments_state",
        ),
        Index(
            "ix_governance_review_assignments_state",
            "lifecycle_state",
            "updated_at",
        ),
        Index("ix_governance_review_assignments_owner", "owner_ref"),
    )


class GovernanceReviewAssignmentEvent(Base):
    """Append-only owner transition for one governance review assignment."""

    __tablename__ = "governance_review_assignment_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_review_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    command_id: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    owner_ref: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('initialized', 'assigned', 'reassigned', "
            "'escalated', 'released')",
            name="ck_governance_review_assignment_events_type",
        ),
        CheckConstraint(
            "to_state IN ('unassigned', 'assigned', 'escalated')",
            name="ck_governance_review_assignment_events_state",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000",
            name="ck_governance_review_assignment_events_reason",
        ),
        UniqueConstraint(
            "assignment_id",
            "sequence",
            name="uq_governance_review_assignment_events_sequence",
        ),
        Index(
            "ix_governance_review_assignment_events_assignment",
            "assignment_id",
            "occurred_at",
        ),
        Index("ix_governance_review_assignment_events_type", "event_type"),
        Index(
            "ix_governance_review_assignment_events_correlation_id", "correlation_id"
        ),
    )


class GovernanceTicketDraftPromotion(Base):
    """One idempotent binding from a governed ticket cluster to its draft."""

    __tablename__ = "governance_ticket_draft_promotions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_signals.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    command_id: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    source_signal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_assignment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "source_signal_version >= 1 AND expected_assignment_version >= 1",
            name="ck_governance_ticket_draft_promotions_versions",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000",
            name="ck_governance_ticket_draft_promotions_reason",
        ),
        Index(
            "ix_governance_ticket_draft_promotions_created",
            "created_at",
        ),
        Index("ix_governance_ticket_draft_promotions_correlation_id", "correlation_id"),
    )


class GovernanceAudienceBinding(Base):
    """Explicit variant routing truth for one governed Wiki knowledge object."""

    __tablename__ = "governance_audience_bindings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    object_ref: Mapped[str] = mapped_column(String(320), nullable=False)
    variant_ref: Mapped[str] = mapped_column(String(220), nullable=False)
    channel: Mapped[str] = mapped_column(String(120), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    brands: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    product_lines: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    plans: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    regions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    languages: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    product_versions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    binding_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __table_args__ = (
        CheckConstraint(
            "visibility IN ('internal', 'external')",
            name="ck_governance_audience_bindings_visibility",
        ),
        CheckConstraint(
            "lifecycle_state IN ('active', 'held', 'removed')",
            name="ck_governance_audience_bindings_lifecycle",
        ),
        Index(
            "ix_governance_audience_bindings_object_state",
            "object_ref",
            "lifecycle_state",
        ),
        Index(
            "ix_governance_audience_bindings_page_state",
            "page_id",
            "lifecycle_state",
        ),
        Index(
            "ix_governance_audience_bindings_conflict",
            "object_ref",
            "channel",
            "visibility",
            "lifecycle_state",
        ),
    )


class GovernanceLedgerEvent(Base):
    """Append-only state transition for one governed Wiki draft aggregate."""

    __tablename__ = "governance_ledger_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    from_state: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(220), nullable=False, unique=True
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "sequence",
            name="uq_governance_ledger_events_draft_sequence",
        ),
        Index(
            "ix_governance_ledger_events_draft_recorded",
            "draft_id",
            "recorded_at",
        ),
        Index("ix_governance_ledger_events_type", "event_type"),
        Index("ix_governance_ledger_events_correlation_id", "correlation_id"),
    )


class GovernancePublication(Base):
    """Immutable result of one approved, idempotent publish command."""

    __tablename__ = "governance_publications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_page_drafts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_ledger_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    publish_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_ledger_events.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    command_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    approval_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="",
        comment="Canonical approval digest persisted on the APPROVED ledger event.",
    )
    scope_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="",
        comment="Previewed publish scope digest (approval, object version, bindings, freshness, action/targets).",
    )
    object_ref: Mapped[str] = mapped_column(String(320), nullable=False)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action_key: Mapped[str] = mapped_column(String(50), nullable=False)
    target_channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    previous_object_status: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_object_status: Mapped[str] = mapped_column(String(30), nullable=False)
    candidate: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    opened_bindings: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False
    )
    removed_bindings: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False
    )
    held_bindings: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False
    )
    action_log: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    published_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_governance_publications_object_published",
            "object_ref",
            "published_at",
        ),
        Index(
            "ix_governance_publications_draft_published",
            "draft_id",
            "published_at",
        ),
        Index("ix_governance_publications_correlation_id", "correlation_id"),
    )


class GovernancePropagation(Base):
    """Latest versioned downstream state for one publication surface."""

    __tablename__ = "governance_propagations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_publications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    surface_id: Mapped[str] = mapped_column(String(120), nullable=False)
    desired_digest: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment=(
            "SHA-256 of the canonical approved publication payload staged for "
            "outbound delivery; a signed acknowledgment must echo it exactly."
        ),
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    channel_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    binding_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    follow_up_commands: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_ledger_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "publication_id",
            "surface_id",
            name="uq_governance_propagations_publication_surface",
        ),
        Index("ix_governance_propagations_status", "status"),
    )


class GovernancePropagationDelivery(Base):
    """Durable outbound delivery receipt for one governed propagation surface.

    One row per propagation (``propagation_id`` unique). The canonical payload
    is frozen at publish staging so retries re-send the exact approved bytes
    and the desired digest stays deterministic; only a signed downstream
    acknowledgment may move the paired propagation to ``synced``. The row also
    carries bounded attempt evidence, correlation metadata, and the final
    acknowledgment receipt so governed reads see persisted propagation truth.
    """

    __tablename__ = "governance_propagation_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    propagation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_propagations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_publications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    surface_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    command_id: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(220), nullable=False, unique=True
    )
    desired_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    expected_page_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_binding_versions: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    traceparent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    attempt_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acknowledged_digest: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    acknowledged_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_receipt_ref: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    ack_correlation_id: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    ack_traceparent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_flight', 'synced', 'failed', 'dead_letter')",
            name="ck_governance_propagation_deliveries_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_governance_propagation_deliveries_attempts",
        ),
        CheckConstraint(
            "expected_page_version >= 1 AND expected_approval_version >= 1",
            name="ck_governance_propagation_deliveries_versions",
        ),
        Index("ix_governance_propagation_deliveries_status", "status"),
        Index(
            "ix_governance_propagation_deliveries_publication",
            "publication_id",
        ),
    )


class DeliveryConsumerReceipt(Base):
    """Append-only acceptance receipt for one signed propagation delivery.

    The receipt intentionally stores only replay identity and binding metadata.
    It never retains the delivered support payload, so the consumer can prove
    one accepted exact body without becoming another knowledge store.
    """

    __tablename__ = "delivery_consumer_receipts"

    delivery_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    surface_id: Mapped[str] = mapped_column(String(120), nullable=False)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_ref: Mapped[str] = mapped_column(String(220), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "delivery_id = btrim(delivery_id) "
            "AND char_length(delivery_id) BETWEEN 1 AND 220",
            name="ck_delivery_consumer_receipts_delivery_id_shape",
        ),
        CheckConstraint(
            "delivery_id = 'delivery:' || publication_id::text || ':' || surface_id",
            name="ck_delivery_consumer_receipts_identity_binding",
        ),
        CheckConstraint(
            "char_length(body_sha256) = 64",
            name="ck_delivery_consumer_receipts_body_sha256_shape",
        ),
        CheckConstraint(
            "surface_id = btrim(surface_id) "
            "AND char_length(surface_id) BETWEEN 1 AND 120",
            name="ck_delivery_consumer_receipts_surface_id_shape",
        ),
        CheckConstraint(
            "object_version >= 1",
            name="ck_delivery_consumer_receipts_object_version",
        ),
        CheckConstraint(
            "receipt_ref = btrim(receipt_ref) "
            "AND char_length(receipt_ref) BETWEEN 1 AND 220",
            name="ck_delivery_consumer_receipts_receipt_ref_shape",
        ),
        UniqueConstraint(
            "receipt_ref",
            name="uq_delivery_consumer_receipts_receipt_ref",
        ),
    )


class Notification(Base):
    """
    In-app notification delivered to one recipient. Created synchronously by
    NotificationService when a contribution lifecycle event fires. Read state
    is tracked per-row (read_at timestamp). No retention policy yet — caller
    can prune by created_at if the table grows.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    # e.g. "wiki_draft.submitted", "skill_contribution.approved"
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # target_type/target_id: a generic pointer (wiki_draft + UUID, etc.) so the
    # frontend can deep-link without us joining at query time.
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        comment="Employee who caused the event (author/reviewer)",
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_notifications_recipient_unread", "recipient_id", "read_at"),
        Index("ix_notifications_created_at", "created_at"),
        Index("ix_notifications_target", "target_type", "target_id"),
    )


# ---------------------------------------------------------------------------
# Multi-dimension wiki page embeddings
# ---------------------------------------------------------------------------
# One table per supported output dimension. The active embedding model spec
# (stored in app_config.active_embedding_model_spec_id) determines which table
# search & ingestion read/write. See cygnus/runtime/ai/embedding_catalog.py.


class _WikiPageEmbeddingBase:
    """Mixin: shared columns for all wiki_page_embeddings_<dim> tables."""

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model_spec_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WikiPageEmbedding768(_WikiPageEmbeddingBase, Base):
    __tablename__ = "wiki_page_embeddings_768"
    embedding = mapped_column(Vector(768), nullable=False)


class WikiPageEmbedding1024(_WikiPageEmbeddingBase, Base):
    __tablename__ = "wiki_page_embeddings_1024"
    embedding = mapped_column(Vector(1024), nullable=False)


class WikiPageEmbedding1536(_WikiPageEmbeddingBase, Base):
    __tablename__ = "wiki_page_embeddings_1536"
    embedding = mapped_column(Vector(1536), nullable=False)


class WikiPageEmbedding3072(_WikiPageEmbeddingBase, Base):
    # 3072d uses halfvec — pgvector's HNSW index caps `vector` at 2000 dims.
    __tablename__ = "wiki_page_embeddings_3072"
    embedding = mapped_column(HALFVEC(3072), nullable=False)


_EMBEDDING_MODEL_BY_DIM: dict[int, type] = {
    768: WikiPageEmbedding768,
    1024: WikiPageEmbedding1024,
    1536: WikiPageEmbedding1536,
    3072: WikiPageEmbedding3072,
}


def get_embedding_model_for_dim(dimension: int) -> type:
    """Return the WikiPageEmbedding<dim> ORM class for a supported dimension."""
    try:
        return _EMBEDDING_MODEL_BY_DIM[dimension]
    except KeyError as e:
        raise ValueError(
            f"Unsupported embedding dimension: {dimension}. "
            f"Supported: {sorted(_EMBEDDING_MODEL_BY_DIM)}"
        ) from e


# ---------------------------------------------------------------------------
# Multi-dimension source chunk embeddings (verbatim sources)
# ---------------------------------------------------------------------------
# Raw, verbatim slices of a preserve_verbatim Source.full_text, embedded as-is
# (no LLM rewriting). Searched in the same semantic pool as wiki pages so that
# high-fidelity docs (decrees, gazettes) are discoverable without being
# "wiki-ified". Mirrors the per-dimension wiki_page_embeddings_<dim> tables.


class _SourceChunkEmbeddingBase:
    """Mixin: shared columns for all source_chunk_embeddings_<dim> tables."""

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_spec_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Char offsets in Source.full_text (slice full_text[start_char:end_char] for
    # a clean preview without the chunker's overlap prefix).
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceChunkEmbedding768(_SourceChunkEmbeddingBase, Base):
    __tablename__ = "source_chunk_embeddings_768"
    embedding = mapped_column(Vector(768), nullable=False)


class SourceChunkEmbedding1024(_SourceChunkEmbeddingBase, Base):
    __tablename__ = "source_chunk_embeddings_1024"
    embedding = mapped_column(Vector(1024), nullable=False)


class SourceChunkEmbedding1536(_SourceChunkEmbeddingBase, Base):
    __tablename__ = "source_chunk_embeddings_1536"
    embedding = mapped_column(Vector(1536), nullable=False)


class SourceChunkEmbedding3072(_SourceChunkEmbeddingBase, Base):
    # 3072d uses halfvec — pgvector's HNSW index caps `vector` at 2000 dims.
    __tablename__ = "source_chunk_embeddings_3072"
    embedding = mapped_column(HALFVEC(3072), nullable=False)


_SOURCE_CHUNK_EMBEDDING_MODEL_BY_DIM: dict[int, type] = {
    768: SourceChunkEmbedding768,
    1024: SourceChunkEmbedding1024,
    1536: SourceChunkEmbedding1536,
    3072: SourceChunkEmbedding3072,
}


def get_source_chunk_embedding_model_for_dim(dimension: int) -> type:
    """Return the SourceChunkEmbedding<dim> ORM class for a supported dimension."""
    try:
        return _SOURCE_CHUNK_EMBEDDING_MODEL_BY_DIM[dimension]
    except KeyError as e:
        raise ValueError(
            f"Unsupported embedding dimension: {dimension}. "
            f"Supported: {sorted(_SOURCE_CHUNK_EMBEDDING_MODEL_BY_DIM)}"
        ) from e


class EmbeddingJob(Base):
    """Tracks a background re-embed job triggered when admin switches model."""

    __tablename__ = "embedding_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_spec_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | running | completed | failed | cancelled
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_embedding_jobs_status", "status", "created_at"),)


# Skill Contributions — Pull Request style workflow
# ---------------------------------------------------------------------------


class SkillContribution(Base):
    """
    A request to create a new skill or update an existing one.
    Acts as a 'Pull Request' where files are stored in a temporary path
    until approved by an admin.
    """

    __tablename__ = "skill_contributions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=True,
    )
    contributor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE")
    )
    base_version: Mapped[Optional[int]] = mapped_column(
        Integer,
        comment="Version number this contribution was forked from. Null for new skills.",
    )
    status: Mapped[str] = mapped_column(
        String(20), default=SkillContributionStatus.DRAFT.value
    )
    # Increments each time the contributor resubmits after needs_revision.
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Reviewer's note when sending the contribution back for changes.
    last_returned_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(
        String(20),
        default="global",
        comment="Scope type for NEW skills: global or department",
    )
    scope_ids: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        comment="List of Department IDs if scope_type is department",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_path: Mapped[Optional[str]] = mapped_column(
        String(1000),
        comment="MinIO prefix for this contribution's files, e.g. 'skill-contributions/{id}/'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    skill: Mapped[Optional["Skill"]] = relationship(back_populates="contributions")
    contributor: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index("ix_skill_contributions_contributor_id", "contributor_id"),
        Index("ix_skill_contributions_status", "status"),
    )


# ---------------------------------------------------------------------------
# MCP query log — one row per MCP tool call (for usage analytics & gap detection)
# ---------------------------------------------------------------------------


class MCPQueryLog(Base):
    __tablename__ = "mcp_query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        comment="Caller; NULL if token resolution failed before call",
    )
    tool_name: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="MCP tool invoked: search_wiki, read_wiki_page, propose_wiki_edit, ...",
    )
    query_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Search/query string when applicable",
    )
    result_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scope_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Department/project/filters used for the call",
    )
    result_ids: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        comment="IDs returned (wiki_page_id or source_id list)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ok",
        comment="ok | error | denied",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Canonical end-to-end request correlation ID (UUID).",
    )
    traceparent: Mapped[Optional[str]] = mapped_column(
        String(55),
        nullable=True,
        comment="W3C traceparent derived from correlation_id.",
    )

    __table_args__ = (
        Index("ix_mcp_query_log_created_at", "created_at"),
        Index("ix_mcp_query_log_employee_id", "employee_id"),
        Index("ix_mcp_query_log_tool_name", "tool_name"),
        Index("ix_mcp_query_log_zero_result", "created_at", "result_count"),
        Index("ix_mcp_query_log_correlation_id", "correlation_id"),
    )


# ---------------------------------------------------------------------------
# Stats daily rollup — pre-aggregated metrics for the admin dashboard
# ---------------------------------------------------------------------------


class StatsDailyRollup(Base):
    """
    One row per (date, metric_key, dimensions). value_numeric for scalar metrics;
    value_json for top-N lists or structured payloads (top contributors, gap topics).
    """

    __tablename__ = "stats_daily_rollup"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC date the metric covers (midnight UTC)",
    )
    metric_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="e.g. wiki.pages.total, mcp.queries.zero_result, draft.pending",
    )
    dimensions: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="{department_id, project_id, tool_name, source}",
    )
    dimensions_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        comment="md5 of canonical-serialized dimensions; empty string when dimensions is NULL",
    )
    value_numeric: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "date", "metric_key", "dimensions_hash", name="uq_stats_rollup_keys"
        ),
        Index("ix_stats_rollup_date", "date"),
        Index("ix_stats_rollup_metric", "metric_key", "date"),
    )


class SourceDispatchExecution(Base):
    """Durable outbox row for one (source, generation, stage) worker handoff.

    Written transactionally with the API enqueue path and reconciled by the
    worker sweep. The deterministic ``job_id`` is passed as ARQ's ``_job_id``
    so a crash/restart can never enqueue the same stage twice: ARQ returns
    ``None`` for an existing job, which is treated as a successful
    acknowledgement. Workers claim a lease at task entry and fence critical
    commits against the source's current ``dispatch_generation``.
    """

    __tablename__ = "source_dispatch_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Monotonic cycle counter snapshot for this execution. Workers fence against
    # the source's current dispatch_generation: an older value is stale.
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    # ingest | post_extraction | map_reduce | refine | regenerate_plan
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    task_args: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # Deterministic: source-dispatch:{source_id}:{stage}:{generation}
    job_id: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    traceparent: Mapped[Optional[str]] = mapped_column(String(55), nullable=True)
    # pending | dispatching | enqueued | running | completed | stale | failed
    dispatch_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    # Number of delivery leases claimed; enqueue exceptions consume the retry
    # budget, deterministic ARQ duplicate responses are acknowledgements.
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enqueued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "generation",
            "stage",
            name="uq_source_dispatch_execution_stage",
        ),
        UniqueConstraint("job_id", name="uq_source_dispatch_execution_job"),
        CheckConstraint(
            "dispatch_status IN ('pending', 'dispatching', 'enqueued', 'running', "
            "'completed', 'stale', 'failed')",
            name="ck_source_dispatch_execution_status",
        ),
        CheckConstraint(
            "generation >= 1 AND attempt_count >= 0",
            name="ck_source_dispatch_execution_values",
        ),
        CheckConstraint(
            "(dispatch_status IN ('pending', 'dispatching', 'enqueued', 'running') "
            "AND terminal_reason IS NULL) OR "
            "(dispatch_status IN ('completed', 'stale', 'failed') "
            "AND terminal_reason IS NOT NULL)",
            name="ck_source_dispatch_execution_terminal_reason",
        ),
        Index(
            "ix_source_dispatch_execution_recovery",
            "dispatch_status",
            "next_attempt_at",
            "lease_expires_at",
        ),
        Index("ix_source_dispatch_execution_source", "source_id"),
        Index("ix_source_dispatch_execution_correlation_id", "correlation_id"),
    )


class SourceDeletion(Base):
    """Database-led deletion intent for one source (tombstone + cleanup state).

    The DELETE endpoint commits this row in the same transaction as
    ``sources.delete_requested_at``. The worker sweep performs the durable
    storage cleanup idempotently and only then removes the source row; a
    partial object failure keeps the row in ``failed`` with ``last_error`` so
    the problem stays visible and is retried. The row survives the source row
    removal (``source_id`` is set NULL) so completed deletions stay auditable.
    """

    __tablename__ = "source_deletions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_by_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    # e.g. "sources/{source_id}/" — the exact prefix the sweeper deletes.
    storage_prefix: Mapped[str] = mapped_column(String(500), nullable=False)
    # pending | in_progress | completed | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed')",
            name="ck_source_deletions_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_source_deletions_attempts",
        ),
        Index("ix_source_deletions_recovery", "status", "updated_at"),
        Index("ix_source_deletions_source", "source_id"),
    )
