"""Sources router — CRUD + upload + arq ingestion pipeline (compiles into wiki).

Permission model v2:
  - doc:read:own_dept → only own department + global docs
  - doc:read:all → all docs
  - Upload creates source_departments M2M entries
"""

import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional, TypedDict, cast

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import delete as sql_delete
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cygnus.evidence.freshness import (
    parse_freshness_state,
    source_freshness_attestation,
    validate_freshness_attestation,
)
from cygnus.runtime.config import settings
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    ScopeType,
    Source,
    SourceDepartment,
    SourceDeletion,
    WikiPage,
)
from cygnus.runtime.database.repository import Repository
from cygnus.runtime.source_deletion import (
    process_source_deletion,
    request_source_deletion,
)
from cygnus.runtime.source_state import (
    mark_source_ingest_queued,
    mark_source_plan_refine_queued,
    mark_source_post_extraction_resume,
    mark_source_requeued_after_department_change,
    mark_source_retry_queued,
)
from cygnus.review import (
    SourcePlanInvalidTransition,
    approve_source_compilation_plan,
    reject_source_compilation_plan,
    request_source_plan_regeneration,
)
from cygnus.runtime.services.audit_service import log_audit
from cygnus.runtime.services.auth_service import (
    get_current_user,
    require_permission,
)
from cygnus.runtime.services.permission_engine import (
    _get_user_permissions,
    build_document_scope_clause,
    build_wiki_scope_clause,
)
from cygnus.substrate.source_url import (
    SourceURLValidationError,
    validate_source_url,
)
from cygnus.substrate.source_language import (
    DEFAULT_SOURCE_LANGUAGE,
    SourceLanguageError,
    normalize_source_language,
)
from cygnus.runtime.worker import get_arq_pool as get_worker_arq_pool
from cygnus.runtime.worker import (
    enqueue_source_ingest_file,
    enqueue_source_ingest_url,
    enqueue_source_map_reduce,
    enqueue_source_plan_regeneration,
    enqueue_source_refine,
    enqueue_source_retry,
)

router = APIRouter()


@router.get("/sources/deletions")
async def list_source_deletions(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:delete"),
):
    """Operator surface for database-led source deletions.

    Partial object failures stay visible here: the intent row keeps
    ``status=failed``, ``last_error`` and ``attempt_count`` until the sweeper
    succeeds or the retry budget is exhausted.
    """
    stmt = (
        select(SourceDeletion).order_by(SourceDeletion.requested_at.desc()).limit(200)
    )
    if status:
        stmt = stmt.where(SourceDeletion.status == status)
    source_scope = build_document_scope_clause(user, action="delete")
    if source_scope is not None:
        visible_source = select(Source.id).where(
            Source.id == SourceDeletion.source_id,
            source_scope,
        )
        # Completed deletion rows lose their source FK by design. Without a
        # current source row, an own-department caller cannot prove visibility,
        # so the operator view fails closed rather than leaking a storage prefix.
        stmt = stmt.where(exists(visible_source))
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "deletions": [
            {
                "id": str(row.id),
                "source_id": str(row.source_id) if row.source_id else None,
                "storage_prefix": row.storage_prefix,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "last_error": row.last_error,
                "requested_at": (
                    row.requested_at.isoformat() if row.requested_at else None
                ),
                "completed_at": (
                    row.completed_at.isoformat() if row.completed_at else None
                ),
            }
            for row in rows
        ]
    }


async def get_arq_pool() -> ArqRedis:
    """Delegate to the shared worker arq pool wiring."""
    return await get_worker_arq_pool()


class SourceResponse(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    source_type: Optional[str]
    file_name: Optional[str]
    url: Optional[str]
    file_size: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    progress: int = 0
    progress_message: Optional[str] = None
    job_id: Optional[str] = None
    page_count: int = 0
    wiki_page_count: int = 0
    extracted_token_count: Optional[int] = None
    image_count: int = 0
    auto_recover_count: int = 0
    knowledge_type_id: Optional[uuid.UUID] = None
    knowledge_type_name: Optional[str] = None
    knowledge_type_color: Optional[str] = None
    # Multi-department (v2)
    department_ids: list[str] = []
    department_names: list[str] = []
    contributed_by_employee_id: Optional[uuid.UUID] = None
    contributed_by_name: Optional[str] = None
    scope_type: str = "global"
    scope_id: Optional[uuid.UUID] = None
    language: str = "en"
    preserve_verbatim: bool = False
    freshness_state: str = "unknown"
    freshness_active: bool = False
    freshness_expired: bool = False
    freshness_actor_id: Optional[uuid.UUID] = None
    freshness_reason: Optional[str] = None
    freshness_attested_at: Optional[datetime] = None
    freshness_expires_at: Optional[datetime] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class SourceDetail(SourceResponse):
    full_text: Optional[str] = None
    outline: Optional[list[dict[str, object]]] = None
    download_url: Optional[str] = None


class SourceCreateURL(BaseModel):
    url: str
    title: Optional[str] = None
    knowledge_type_id: Optional[uuid.UUID] = None
    department_ids: list[uuid.UUID] = []
    scope_type: Optional[str] = None
    scope_id: Optional[uuid.UUID] = None
    preserve_verbatim: bool = False
    # Explicit normalized language tag (en | zh). REQUIRED: the server never
    # defaults or auto-detects the language of a new source.
    language: str


class SourceUpdate(BaseModel):
    title: Optional[str] = None
    knowledge_type_id: Optional[uuid.UUID] = None
    department_ids: Optional[list[uuid.UUID]] = None
    scope_type: Optional[str] = None
    scope_id: Optional[uuid.UUID] = None
    # Optional: when present, validated + normalized and the source re-ingests
    # under the new language. Absent means "preserve the persisted tag".
    language: Optional[str] = None


class FreshnessAttestationRequest(BaseModel):
    freshness_state: str
    reason: str
    expires_at: Optional[datetime] = None


_ALLOWED_SCOPE_TYPES = frozenset({ScopeType.GLOBAL.value, ScopeType.DEPARTMENT.value})


_UPLOAD_STREAM_CHUNK_BYTES = 1024 * 1024


def _validate_document_assignments(
    user: Employee,
    *,
    department_ids: list[uuid.UUID],
    scope_type: Optional[str],
    scope_id: Optional[uuid.UUID],
    action_scope_perm: str = "doc:create:all",
) -> list[uuid.UUID]:
    """Validate and canonicalize source department/scope assignments.

    A department-scoped Source must have a matching ``SourceDepartment`` row:
    document/MCP readers and the compiler use those rows as the canonical
    visibility relation. The returned, de-duplicated list therefore derives the
    department scope id into the link set in the same database transaction.
    """
    # Omitted scope is the persisted global default, so it must receive the
    # same :all authorization check rather than bypassing assignment policy.
    scope_type = scope_type or ScopeType.GLOBAL.value
    if scope_type not in _ALLOWED_SCOPE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope_type must be one of: {sorted(_ALLOWED_SCOPE_TYPES)}",
        )
    if scope_type == ScopeType.DEPARTMENT.value and scope_id is None:
        raise HTTPException(
            status_code=400,
            detail="scope_id is required when scope_type is 'department'",
        )
    if scope_type != ScopeType.DEPARTMENT.value and scope_id is not None:
        raise HTTPException(
            status_code=400,
            detail="scope_id is only allowed with scope_type 'department'",
        )

    canonical_department_ids = list(dict.fromkeys(department_ids))
    perms = _get_user_permissions(user)
    if user.role != "admin" and action_scope_perm not in perms:
        if scope_type == ScopeType.GLOBAL.value:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to make documents global",
            )

        user_depts = set(user.department_ids)
        for department_id in canonical_department_ids:
            if department_id not in user_depts:
                raise HTTPException(
                    status_code=403,
                    detail="You can only assign documents to your own departments",
                )
        if scope_type == ScopeType.DEPARTMENT.value and scope_id not in user_depts:
            raise HTTPException(
                status_code=403,
                detail="You can only scope documents to your own departments",
            )

    if (
        scope_type == ScopeType.DEPARTMENT.value
        and scope_id is not None
        and scope_id not in canonical_department_ids
    ):
        canonical_department_ids.append(scope_id)
    return canonical_department_ids


async def _get_scoped_source(
    db: AsyncSession,
    source_id: uuid.UUID,
    user: Employee,
    action: str,
    *,
    include_tombstoned: bool = False,
) -> Source:
    """Load a source inside its SQL document scope, or raise the shared 404.

    Tombstoned rows stay hidden by default. DELETE opts in only to preserve its
    idempotent pending-cleanup response while still applying the same SQL scope.
    """
    statement = (
        select(Source).options(*_source_load_options()).where(Source.id == source_id)
    )
    if not include_tombstoned:
        statement = statement.where(Source.delete_requested_at.is_(None))
    scope_clause = build_document_scope_clause(user, action=action)
    if scope_clause is not None:
        statement = statement.where(scope_clause)
    source = (await db.execute(statement)).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


async def _wiki_page_count(
    session: AsyncSession, source_id: uuid.UUID, user: Employee
) -> int:
    """How many permission-visible wiki pages reference this source."""
    stmt = (
        select(func.count())
        .select_from(WikiPage)
        .where(WikiPage.source_ids.contains([source_id]))
    )
    scope_clause = build_wiki_scope_clause(user)
    if scope_clause is not None:
        stmt = stmt.where(scope_clause)
    return (await session.execute(stmt)).scalar_one()


async def _image_count(session: AsyncSession, source_id: uuid.UUID) -> int:
    """How many SourceImage rows exist for this source."""
    from cygnus.runtime.database.models import SourceImage

    stmt = (
        select(func.count())
        .select_from(SourceImage)
        .where(SourceImage.source_id == source_id)
    )
    return (await session.execute(stmt)).scalar_one()


class _FreshnessResponseFields(TypedDict):
    freshness_state: str
    freshness_active: bool
    freshness_expired: bool
    freshness_actor_id: Optional[uuid.UUID]
    freshness_reason: Optional[str]
    freshness_attested_at: Optional[datetime]
    freshness_expires_at: Optional[datetime]


def _freshness_response_fields(source: object) -> _FreshnessResponseFields:
    """Project the evidence-layer attestation onto typed ``SourceResponse`` fields.

    The evidence helper intentionally returns ``dict[str, object]``; this
    boundary narrows each key to the concrete type ``SourceResponse`` declares,
    converting the stringified actor id and ISO timestamps back to structured
    values before pydantic validation.
    """
    raw = source_freshness_attestation(source)
    actor_id = cast(Optional[str], raw["freshness_actor_id"])
    attested_at = cast(Optional[str], raw["freshness_attested_at"])
    expires_at = cast(Optional[str], raw["freshness_expires_at"])
    return {
        "freshness_state": cast(str, raw["freshness_state"]),
        "freshness_active": cast(bool, raw["freshness_active"]),
        "freshness_expired": cast(bool, raw["freshness_expired"]),
        "freshness_actor_id": uuid.UUID(actor_id) if actor_id else None,
        "freshness_reason": cast(Optional[str], raw["freshness_reason"]),
        "freshness_attested_at": (
            datetime.fromisoformat(attested_at) if attested_at else None
        ),
        "freshness_expires_at": (
            datetime.fromisoformat(expires_at) if expires_at else None
        ),
    }


def _to_response(
    source: Source, wiki_page_count: int = 0, image_count: int = 0
) -> SourceResponse:
    # Extract departments from M2M relationship
    dept_ids = []
    dept_names = []
    if hasattr(source, "departments") and source.departments:
        for sd in source.departments:
            dept_ids.append(str(sd.department_id))
            if hasattr(sd, "department") and sd.department:
                dept_names.append(sd.department.name)

    return SourceResponse(
        id=source.id,
        title=source.title,
        source_type=source.source_type,
        file_name=source.file_name,
        url=source.url,
        file_size=source.file_size,
        status=source.status,
        error_message=source.error_message,
        progress=source.progress,
        progress_message=source.progress_message,
        job_id=source.job_id,
        page_count=len(source.page_offsets or []),
        wiki_page_count=wiki_page_count,
        extracted_token_count=source.extracted_token_count,
        image_count=image_count,
        auto_recover_count=source.auto_recover_count or 0,
        knowledge_type_id=source.knowledge_type_id,
        knowledge_type_name=source.knowledge_type.name
        if source.knowledge_type
        else None,
        knowledge_type_color=source.knowledge_type.color
        if source.knowledge_type
        else None,
        department_ids=dept_ids,
        department_names=dept_names,
        contributed_by_employee_id=source.contributed_by_employee_id,
        contributed_by_name=source.contributor.name if source.contributor else None,
        scope_type=source.scope_type or "global",
        scope_id=source.scope_id,
        language=source.language,
        preserve_verbatim=bool(source.preserve_verbatim),
        **_freshness_response_fields(source),
        created_at=source.created_at.isoformat(),
        updated_at=source.updated_at.isoformat(),
    )


def _source_load_options():
    """Common selectinload options for Source queries."""
    return [
        selectinload(Source.knowledge_type),
        selectinload(Source.departments).selectinload(SourceDepartment.department),
        selectinload(Source.contributor),
    ]


@router.get("/sources")
async def list_sources(
    knowledge_type_id: Optional[uuid.UUID] = Query(None),
    department_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """List sources with scoped filtering based on user permissions."""
    # Check user has at least some doc:read permission
    perms = _get_user_permissions(user)
    if user.role != "admin" and not any(p.startswith("doc:read:") for p in perms):
        raise HTTPException(403, "Permission required: doc:read")

    base = select(Source).options(*_source_load_options())
    count_base = select(func.count(Source.id))

    # --- Tombstone filtering (database-led deletions hide immediately) ---
    base = base.where(Source.delete_requested_at.is_(None))
    count_base = count_base.where(Source.delete_requested_at.is_(None))

    # --- Scope filtering ---
    scope_clause = build_document_scope_clause(user)
    if scope_clause is not None:
        base = base.where(scope_clause)
        count_base = count_base.where(scope_clause)

    # --- Additional filters ---
    if knowledge_type_id:
        base = base.where(Source.knowledge_type_id == knowledge_type_id)
        count_base = count_base.where(Source.knowledge_type_id == knowledge_type_id)
    if department_id:
        dept_exists = exists(
            select(SourceDepartment.source_id).where(
                SourceDepartment.source_id == Source.id,
                SourceDepartment.department_id == department_id,
            )
        )
        base = base.where(dept_exists)
        count_base = count_base.where(dept_exists)
    if status:
        base = base.where(Source.status == status)
        count_base = count_base.where(Source.status == status)
    if search:
        like = f"%{search}%"
        base = base.where(Source.title.ilike(like) | Source.file_name.ilike(like))
        count_base = count_base.where(
            Source.title.ilike(like) | Source.file_name.ilike(like)
        )

    total = (await db.execute(count_base)).scalar() or 0

    offset = (max(page, 1) - 1) * page_size
    stmt = base.order_by(Source.created_at.desc()).offset(offset).limit(page_size)
    sources = (await db.execute(stmt)).scalars().all()

    items: list[SourceResponse] = []
    for s in sources:
        items.append(_to_response(s, await _wiki_page_count(db, s.id, user)))

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.get("/sources/{source_id}")
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    source = await _get_scoped_source(db, source_id, user, "read")
    if source.delete_requested_at is not None:
        raise HTTPException(status_code=404, detail="Source not found")

    wiki_count = await _wiki_page_count(db, source_id, user)
    img_count = await _image_count(db, source_id)
    download_url = None
    if source.minio_key:
        try:
            from cygnus.runtime.services.storage_service import storage_service

            download_url = storage_service.get_presigned_url(source.minio_key)
        except Exception:
            pass

    base = _to_response(source, wiki_count, img_count)
    return SourceDetail(
        **base.model_dump(),
        full_text=source.full_text,
        outline=source.outline_json,
        download_url=download_url,
    )


@router.get("/sources/{source_id}/progress")
async def get_source_progress(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:read"),
):
    source = await _get_scoped_source(db, source_id, user, "read")
    if source.delete_requested_at is not None:
        raise HTTPException(status_code=404, detail="Source not found")
    wiki_count = await _wiki_page_count(db, source_id, user)
    return {
        "id": str(source.id),
        "status": source.status,
        "progress": source.progress,
        "progress_message": source.progress_message,
        "page_count": len(source.page_offsets or []),
        "wiki_page_count": wiki_count,
    }


@router.post("/sources/upload", response_model=SourceResponse)
async def upload_source(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    knowledge_type_id: Optional[str] = Form(None),
    department_ids: Optional[str] = Form(None),  # comma-separated UUIDs
    scope_type: Optional[str] = Form(None),
    scope_id: Optional[str] = Form(None),
    preserve_verbatim: bool = Form(False),
    language: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:create"),
):
    # Explicit language tag is required and validated BEFORE any lasting
    # mutation (no source row, no upload, no enqueue). Never auto-detected.
    try:
        language = normalize_source_language(language)
    except SourceLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_name = file.filename or "unknown"

    # Parse and authorize document assignments before accepting potentially
    # large bytes. URL and file sources intentionally call the same validator.
    dept_uuids: list[uuid.UUID] = []
    if department_ids:
        for value in department_ids.split(","):
            normalized = value.strip()
            if not normalized:
                continue
            try:
                dept_uuids.append(uuid.UUID(normalized))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid department_id: {normalized}",
                ) from exc

    scope_type_value = scope_type or ScopeType.GLOBAL.value
    try:
        scope_id_value = uuid.UUID(scope_id) if scope_id else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid scope_id") from exc
    dept_uuids = _validate_document_assignments(
        user,
        department_ids=dept_uuids,
        scope_type=scope_type_value,
        scope_id=scope_id_value,
    )

    max_upload = settings.max_source_upload_bytes

    # Spill after the first non-empty write: a source body is never retained in
    # memory beyond the current bounded request chunk before streaming to
    # object storage.
    with tempfile.SpooledTemporaryFile(max_size=1, mode="w+b") as staged_upload:
        upload_size = 0
        while True:
            chunk = await file.read(_UPLOAD_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            if len(chunk) > max_upload - upload_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the maximum size of {max_upload} bytes",
                )
            staged_upload.write(chunk)
            upload_size += len(chunk)

        repo = Repository(db)
        source = Source(
            title=title or file.filename,
            source_type="file",
            file_name=file_name,
            file_size=upload_size,
            knowledge_type_id=(
                uuid.UUID(knowledge_type_id) if knowledge_type_id else None
            ),
            contributed_by_employee_id=user.id,
            scope_type=scope_type_value,
            scope_id=scope_id_value,
            preserve_verbatim=preserve_verbatim,
            language=language,
        )
        mark_source_ingest_queued(source)
        source = await repo.create(source)
        await db.flush()

        for department_id in dept_uuids:
            db.add(SourceDepartment(source_id=source.id, department_id=department_id))
        await db.flush()

        await log_audit(
            db, user, "create", "source", str(source.id), reason=source.title
        )
        await db.commit()
        await db.refresh(source)

        # Reapply the create scope in SQL before the external object-storage
        # action. A changed/invalid source cannot gain a durable object through
        # this request merely because its ID was known earlier in the handler.
        source = await _get_scoped_source(db, source.id, user, "create")

        from cygnus.substrate.source_text import _guess_content_type
        from cygnus.runtime.services.storage_service import storage_service

        minio_key = f"sources/{source.id}/original/{file_name}"
        staged_upload.seek(0)
        await storage_service.upload_stream_async(
            object_name=minio_key,
            stream=staged_upload,
            length=upload_size,
            content_type=_guess_content_type(file_name),
        )
        source.minio_key = minio_key
        source.file_name = file_name
        await db.commit()

        job_id = await enqueue_source_ingest_file(str(source.id), db=db, source=source)
        mark_source_ingest_queued(source, job_id=job_id)
        await db.commit()

        source = await _get_scoped_source(db, source.id, user, "create")

    logger.info(f"Enqueued ingestion job {job_id or 'N/A'} for source {source.id}")
    return _to_response(source)


@router.post("/sources/url", response_model=SourceResponse)
async def add_url_source(
    req: SourceCreateURL,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:create"),
):
    # Validate the URL destination before any lasting mutation: scheme, host,
    # credentials, and DNS resolution to public (non-private/loopback/link-local/
    # multicast) addresses. Redirects are re-validated at fetch time.
    try:
        validated = await validate_source_url(req.url)
    except SourceURLValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Explicit language tag is required and validated before any lasting
    # mutation; never auto-detected from the fetched document.
    try:
        language = normalize_source_language(req.language)
    except SourceLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Same department/scope assignment permission rules as upload.
    canonical_department_ids = _validate_document_assignments(
        user,
        department_ids=req.department_ids,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
    )

    repo = Repository(db)
    source = Source(
        title=req.title or validated.url,
        source_type="url",
        url=validated.url,
        knowledge_type_id=req.knowledge_type_id,
        contributed_by_employee_id=user.id,
        scope_type=req.scope_type or ScopeType.GLOBAL.value,
        scope_id=req.scope_id,
        preserve_verbatim=req.preserve_verbatim,
        language=language,
    )
    mark_source_ingest_queued(source)
    source = await repo.create(source)
    await db.flush()

    # Create M2M department links
    for did in canonical_department_ids:
        db.add(SourceDepartment(source_id=source.id, department_id=did))
    await db.flush()

    await log_audit(db, user, "create", "source", str(source.id), reason=source.title)
    await db.commit()
    await db.refresh(source)

    # Resolve the just-created source through the same SQL create scope before
    # a durable dispatch is recorded.
    source = await _get_scoped_source(db, source.id, user, "create")

    job_id = await enqueue_source_ingest_url(str(source.id), db=db, source=source)
    mark_source_ingest_queued(source, job_id=job_id)
    await db.commit()

    source = await _get_scoped_source(db, source.id, user, "create")

    logger.info(f"Enqueued URL ingestion job {job_id or 'N/A'} for source {source.id}")
    return _to_response(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    from cygnus.runtime.services import wiki_service

    source = await _get_scoped_source(db, source_id, user, "edit")

    # Scope, department, and language assignments drive where wiki pages get
    # committed and under which canonical identity. The ingestion worker reads
    # them from DB at commit time, so an edit while the pipeline is mid-flight
    # can cause pages to land in the wrong scope/language (visibility leak or
    # identity split). Block those fields for any in-flight status; title and
    # knowledge_type are cosmetic for the pipeline and remain editable.
    in_flight_statuses = ("pending", "processing", "awaiting_approval", "plan_ready")
    scope_change_requested = body.scope_type is not None or body.scope_id is not None
    if source.status in in_flight_statuses and (
        scope_change_requested
        or body.department_ids is not None
        or body.language is not None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot change visibility, departments, or language while the "
                "document is being processed. Wait until it finishes (or fails) "
                "and try again."
            ),
        )

    if body.scope_id is not None and body.scope_type is None:
        raise HTTPException(
            status_code=400,
            detail="scope_type is required when scope_id is provided",
        )

    old_dept_ids = set(
        (
            await db.execute(
                select(SourceDepartment.department_id).where(
                    SourceDepartment.source_id == source_id
                )
            )
        )
        .scalars()
        .all()
    )
    requested_dept_ids = (
        set(body.department_ids) if body.department_ids is not None else old_dept_ids
    )
    requested_scope_type: str = (
        body.scope_type if body.scope_type is not None else source.scope_type
    )
    requested_scope_id = body.scope_id if scope_change_requested else source.scope_id

    # Validate effective assignments before changing any ORM state. In
    # particular, a PATCH that changes only scope_type/scope_id must not bypass
    # own-department authorization or allowed scope validation.
    if scope_change_requested or body.department_ids is not None:
        requested_dept_ids = set(
            _validate_document_assignments(
                user,
                department_ids=list(requested_dept_ids),
                scope_type=requested_scope_type,
                scope_id=requested_scope_id,
                action_scope_perm="doc:edit:all",
            )
        )

    new_language: str | None = None
    language_changed = False
    if body.language is not None:
        try:
            new_language = normalize_source_language(body.language)
        except SourceLanguageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        language_changed = new_language != (source.language or DEFAULT_SOURCE_LANGUAGE)

    department_changed = requested_dept_ids != old_dept_ids
    scope_changed = scope_change_requested and (
        requested_scope_type != source.scope_type
        or requested_scope_id != source.scope_id
    )
    reingest = (
        (department_changed or scope_changed or language_changed)
        and source.status == "ready"
        and not source.preserve_verbatim
    )
    reingest_reason = ""
    if reingest:
        if scope_changed:
            reingest_reason = "scope change"
        elif department_changed:
            reingest_reason = "department change"
        else:
            reingest_reason = "language change"

        # The map-reduce outbox call below starts exactly this next generation.
        # Fence all older compiler drafts before any source change can autoflush;
        # otherwise a reviewer could approve a stale department/language draft.
        from cygnus.review.contributions import invalidate_stale_compiler_drafts
        from cygnus.runtime.ai.mrp.pipeline import _resolve_wiki_scopes

        next_generation = int(source.dispatch_generation or 0) + 1
        await invalidate_stale_compiler_drafts(
            db,
            source_id=source.id,
            current_generation=next_generation,
            reason=f"Source re-ingest required after {reingest_reason}",
        )

        # Resolve and clean old Wiki identities before mutating canonical source
        # scope or department rows. _resolve_wiki_scopes intentionally reads DB
        # truth, so doing this after assignment would regenerate the wrong index
        # and leave stale pages visible in the old scope.
        old_scopes = await _resolve_wiki_scopes(db, source)
        await wiki_service.detach_source_from_wiki(db, source.id)
        for old_scope_type, old_scope_id in old_scopes:
            await wiki_service.regenerate_index(
                db,
                scope_type=old_scope_type,
                scope_id=old_scope_id,
            )

    if body.title is not None:
        source.title = body.title
    if body.knowledge_type_id is not None:
        source.knowledge_type_id = body.knowledge_type_id
    if scope_change_requested:
        source.scope_type = requested_scope_type
        source.scope_id = requested_scope_id
    if department_changed:
        await db.execute(
            sql_delete(SourceDepartment).where(SourceDepartment.source_id == source_id)
        )
        for department_id in requested_dept_ids:
            db.add(SourceDepartment(source_id=source_id, department_id=department_id))
    if new_language is not None:
        source.language = new_language

    await log_audit(db, user, "update", "source", str(source.id), reason=source.title)
    await db.flush()

    if reingest:
        mark_source_requeued_after_department_change(source, reason=reingest_reason)
        await db.flush()

        job_id = await enqueue_source_map_reduce(str(source_id), db=db, source=source)
        mark_source_requeued_after_department_change(
            source,
            job_id=job_id,
            reason=reingest_reason,
        )

    await db.commit()

    source = await _get_scoped_source(db, source_id, user, "edit")
    return _to_response(source, await _wiki_page_count(db, source_id, user))


@router.post("/sources/{source_id}/freshness", response_model=SourceResponse)
async def attest_source_freshness(
    source_id: uuid.UUID,
    body: FreshnessAttestationRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    """Record an explicit freshness attestation for one source.

    Freshness is never inferred: only an explicit FRESH attestation with
    actor/reason/attestation time and a future expiry resolves to fresh.
    Attesting STALE or UNKNOWN records the explicit downgrade (and clears any
    previous expiry).
    """
    source = await _get_scoped_source(db, source_id, user, "edit")

    try:
        state = parse_freshness_state(body.freshness_state)
        validate_freshness_attestation(
            state=state,
            reason=body.reason,
            expires_at=body.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    source.freshness_state = state.value
    source.freshness_reason = body.reason.strip()
    source.freshness_actor_id = user.id
    source.freshness_attested_at = datetime.now(timezone.utc)
    source.freshness_expires_at = body.expires_at if state.value == "fresh" else None

    await log_audit(
        db,
        user,
        "attest_freshness",
        "source",
        str(source.id),
        reason=f"{state.value}: {body.reason.strip()}",
    )
    await db.commit()

    source = await _get_scoped_source(db, source_id, user, "edit")
    return _to_response(source, await _wiki_page_count(db, source_id, user))


@router.post("/sources/{source_id}/retry", response_model=SourceResponse)
async def retry_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    """
    Retry ingestion for a source whose previous attempt failed.

    Only allowed when the source is in `error` status — successful sources
    cannot be re-ingested.
    """
    source = await _get_scoped_source(db, source_id, user, "edit")
    allowed_statuses = ("error", "plan_ready")
    if source.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Retry is only allowed for sources in {allowed_statuses} status",
        )
    # Block runaway loops: if the sweep cron has flipped this source back to
    # 'error' too many times in a row, the failure is almost certainly
    # deterministic (bad provider key, malformed file). Force human review.
    cap = settings.max_auto_recover_attempts
    if (source.auto_recover_count or 0) >= cap and user.role != "admin":
        raise HTTPException(
            status_code=409,
            detail=(
                f"This source has failed {source.auto_recover_count} consecutive "
                f"auto-recoveries (cap={cap}). Check LLM provider config and the "
                f"source file, then ask an admin to reset and retry."
            ),
        )
    if source.source_type == "url" and not source.url:
        raise HTTPException(status_code=400, detail="Source has no URL to retry")
    if source.source_type == "file" and not source.minio_key:
        raise HTTPException(status_code=400, detail="Source file not found in storage")

    retry_from_status = source.status
    mark_source_retry_queued(source)
    await db.flush()

    job_id, task_name = await enqueue_source_retry(
        str(source_id),
        source_type=source.source_type or "file",
        pipeline_phase=source.pipeline_phase,
        current_status=retry_from_status,
        db=db,
        source=source,
    )
    mark_source_retry_queued(source, job_id=job_id)
    await db.commit()
    await db.refresh(source)

    source = await _get_scoped_source(db, source_id, user, "edit")
    logger.info(
        f"Queued retry job {job_id or 'N/A'} ({task_name}) for source {source_id}"
    )
    return _to_response(source)


# ---------------------------------------------------------------------------
# Compilation Plan review endpoints (MRP Phase 2.5)
# ---------------------------------------------------------------------------


class PlanApproveRequest(BaseModel):
    note: Optional[str] = None


class PlanRejectRequest(BaseModel):
    note: str


class PlanRegenerateRequest(BaseModel):
    note: str


class PlanFailure(BaseModel):
    """Sanitized compile-completeness failure exposed to plan reviewers.

    Projected from plan_json['_failures'] (internal). Never carries raw page
    content or secrets: ``message`` is a short, safe summary, and the stable
    ``unit`` / ``phase`` / ``status`` / ``error_type`` / ``retryable`` fields
    are what operators and the Source UI act on.
    """

    unit: str
    phase: str
    status: str
    error_type: str
    retryable: bool
    message: str


def _sanitize_plan_failure(failure: object) -> PlanFailure:
    """Project one internal failure dict onto the typed, safe API contract."""
    if not isinstance(failure, dict):
        return PlanFailure(
            unit="unknown",
            phase="unknown",
            status="error",
            error_type="unknown",
            retryable=False,
            message="",
        )
    message = str(failure.get("message") or "").strip()[:200]
    return PlanFailure(
        unit=str(failure.get("unit") or "unknown"),
        phase=str(failure.get("phase") or "unknown"),
        status=str(failure.get("status") or "error"),
        error_type=str(failure.get("error_type") or "unknown"),
        retryable=bool(failure.get("retryable")),
        message=message,
    )


@router.get("/sources/{source_id}/plan")
async def get_compilation_plan(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:read"),
):
    """Return the current compilation plan for a source (MRP Phase 2.5)."""
    from cygnus.runtime.database.models import SourceCompilationPlan

    await _get_scoped_source(db, source_id, user, "read")
    plan = (
        await db.execute(
            select(SourceCompilationPlan).where(
                SourceCompilationPlan.source_id == source_id
            )
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(
            status_code=404, detail="No compilation plan found for this source"
        )

    plan_json = dict(plan.plan_json or {})
    # Internal resume metadata stays private; failures are re-projected below
    # as a sanitized, typed contract so compile completeness stays observable.
    raw_failures = plan_json.get("_failures") or []
    plan_json.pop("_claims", None)
    plan_json.pop("_entities", None)
    plan_json.pop("_concepts", None)
    plan_json.pop("_page_drafts", None)
    plan_json.pop("_failures", None)

    return {
        "id": str(plan.id),
        "source_id": str(plan.source_id),
        "status": plan.status,
        "plan": plan_json,
        "failures": [_sanitize_plan_failure(f).model_dump() for f in raw_failures],
        "created_at": plan.created_at.isoformat(),
        "reviewed_at": plan.reviewed_at.isoformat() if plan.reviewed_at else None,
        "review_note": plan.review_note,
    }


@router.post("/sources/{source_id}/approve-extraction")
async def approve_extraction(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    """Resume the pipeline for a source paused at status='awaiting_approval'.

    Triggered after a human reviews the extracted token count + image count and
    decides to spend AI tokens on it. Enqueues the runtime-owned post-extraction
    pipeline path based on whether the source has extracted images.
    """
    from cygnus.runtime.worker import enqueue_post_extraction_pipeline

    source = await _get_scoped_source(db, source_id, user, "edit")
    if source.status != "awaiting_approval":
        raise HTTPException(
            400,
            f"Source is not awaiting approval (status={source.status})",
        )

    has_images = (await _image_count(db, source_id)) > 0
    job_id = await enqueue_post_extraction_pipeline(
        str(source_id), has_images=has_images, db=db, source=source
    )

    mark_source_post_extraction_resume(
        source,
        has_images=has_images,
        job_id=job_id,
    )

    await log_audit(db, user, "approve", "source_extraction", str(source.id))
    await db.commit()

    return {
        "status": "processing",
        "job_id": job_id,
        "has_images": has_images,
        "token_count": source.extracted_token_count,
    }


@router.post("/sources/{source_id}/plan/approve")
async def approve_compilation_plan(
    source_id: uuid.UUID,
    body: PlanApproveRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    """Approve (and optionally modify) the compilation plan, then enqueue REFINE task."""
    from cygnus.runtime.database.models import SourceCompilationPlan

    source = await _get_scoped_source(db, source_id, user, "edit")
    plan = (
        await db.execute(
            select(SourceCompilationPlan)
            .where(SourceCompilationPlan.source_id == source_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for this source")
    try:
        await approve_source_compilation_plan(db, plan, source, user, body.note)
    except SourcePlanInvalidTransition as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=409 if "being regenerated" in detail else 400,
            detail=detail,
        ) from exc

    await db.flush()

    job_id = await enqueue_source_refine(str(source_id), db=db, source=source)
    mark_source_plan_refine_queued(source, job_id=job_id)
    await db.commit()

    logger.info(
        f"Plan approved for source {source_id} by user {user.id}, refine job: {job_id or 'N/A'}"
    )
    return {"approved": True, "job_id": job_id}


@router.post("/sources/{source_id}/plan/regenerate")
async def regenerate_compilation_plan(
    source_id: uuid.UUID,
    body: PlanRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    """
    Enqueue a background task to re-run planning with reviewer feedback.

    Plan status transitions: pending_review/rejected → regenerating → pending_review.
    Frontend should poll GET /sources/{id}/plan to detect completion (status flips
    back to pending_review and plan content updates).
    """
    from cygnus.runtime.database.models import SourceCompilationPlan

    if not body.note.strip():
        raise HTTPException(
            status_code=400, detail="Note is required to regenerate plan"
        )

    source = await _get_scoped_source(db, source_id, user, "edit")

    # SELECT FOR UPDATE — atomic state transition, prevents concurrent regenerate/approve.
    plan = (
        await db.execute(
            select(SourceCompilationPlan)
            .where(SourceCompilationPlan.source_id == source_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for this source")
    try:
        await request_source_plan_regeneration(db, plan, user, body.note)
    except SourcePlanInvalidTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()

    source = await _get_scoped_source(db, source_id, user, "edit")
    job_id = await enqueue_source_plan_regeneration(
        str(source_id), body.note, db=db, source=source
    )

    logger.info(
        f"Plan regenerate queued for source {source_id} by user {user.id}, job: {job_id or 'N/A'}"
    )
    return {
        "queued": True,
        "status": plan.status,
        "job_id": job_id,
    }


@router.post("/sources/{source_id}/plan/reject")
async def reject_compilation_plan(
    source_id: uuid.UUID,
    body: PlanRejectRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:edit"),
):
    """Reject the compilation plan. Source moves to error status."""
    from cygnus.runtime.database.models import SourceCompilationPlan

    source = await _get_scoped_source(db, source_id, user, "edit")
    plan = (
        await db.execute(
            select(SourceCompilationPlan)
            .where(SourceCompilationPlan.source_id == source_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for this source")
    try:
        await reject_source_compilation_plan(db, plan, source, user, body.note)
    except SourcePlanInvalidTransition as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=409 if "being regenerated" in detail else 400,
            detail=detail,
        ) from exc

    await db.commit()
    logger.info(f"Plan rejected for source {source_id} by user {user.id}: {body.note}")
    return {"rejected": True}


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = require_permission("doc:delete"),
):
    # Scope/404 pre-check. The delete lifecycle (tombstone + cleanup intent,
    # then durable storage cleanup and row removal by the worker sweeper) is
    # owned by the durable-deletion slice.
    source = await _get_scoped_source(
        db,
        source_id,
        user,
        "delete",
        include_tombstoned=True,
    )
    if source.delete_requested_at is not None:
        return {"deleted": True, "cleanup": "pending"}

    # Database-led deletion: commit the tombstone + cleanup intent in one
    # transaction BEFORE any durable storage object is removed. A crash here
    # leaves an intent row the sweeper finishes; the source is already
    # invisible to readers.
    await request_source_deletion(db, source, actor_id=user.id)
    await log_audit(db, user, "delete", "source", str(source.id), reason=source.title)
    await db.commit()

    # Best-effort immediate cleanup; the worker sweeper retries idempotently
    # and keeps partial object failures visible on the intent row.
    try:
        status = await process_source_deletion(source_id)
    except Exception as exc:
        logger.warning(f"Source {source_id} immediate cleanup failed: {exc}")
        status = "pending"
    return {"deleted": True, "cleanup": status}
