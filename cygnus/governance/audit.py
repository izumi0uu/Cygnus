from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import cast
import uuid

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from cygnus.governance.ledger import GovernanceEventType
from cygnus.runtime.database.models import (
    Employee,
    GovernanceLedgerEvent,
    WikiPage,
    WikiPageDraft,
)
from cygnus.runtime.services.permission_engine import (
    build_wiki_scope_clause,
    get_effective_permissions,
    get_scope_level,
)


class GovernanceAuditPhase(str, Enum):
    REVIEW = "review"
    APPROVAL = "approval"
    PUBLISH = "publish"
    RECOVERY = "recovery"


_PHASE_EVENT_TYPES: dict[GovernanceAuditPhase, tuple[GovernanceEventType, ...]] = {
    GovernanceAuditPhase.REVIEW: (
        GovernanceEventType.PROPOSAL_CREATED,
        GovernanceEventType.REVIEW_REQUESTED,
        GovernanceEventType.CHANGES_REQUESTED,
        GovernanceEventType.REVIEW_RESUBMITTED,
        GovernanceEventType.REJECTED,
        GovernanceEventType.WITHDRAWN,
    ),
    GovernanceAuditPhase.APPROVAL: (
        GovernanceEventType.APPROVED,
        GovernanceEventType.STATE_IMPORTED,
    ),
    GovernanceAuditPhase.PUBLISH: (GovernanceEventType.PUBLISHED,),
    GovernanceAuditPhase.RECOVERY: (GovernanceEventType.PROPAGATION_UPDATED,),
}
_EVENT_PHASE = {
    event_type.value: phase
    for phase, event_types in _PHASE_EVENT_TYPES.items()
    for event_type in event_types
}
if set(_EVENT_PHASE) != {event_type.value for event_type in GovernanceEventType}:
    raise RuntimeError("governance audit phase map must cover every ledger event type")

_DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    GovernanceEventType.PROPOSAL_CREATED.value: (
        "draft_kind",
        "page_id",
        "base_version",
        "revision_round",
        "source",
        "content_sha256",
    ),
    GovernanceEventType.REVIEW_REQUESTED.value: ("revision_round", "source"),
    GovernanceEventType.CHANGES_REQUESTED.value: ("revision_round",),
    GovernanceEventType.REVIEW_RESUBMITTED.value: ("revision_round",),
    GovernanceEventType.APPROVED.value: (
        "page_id",
        "page_version",
        "revision_round",
    ),
    GovernanceEventType.REJECTED.value: ("revision_round",),
    GovernanceEventType.WITHDRAWN.value: ("revision_round",),
    GovernanceEventType.PUBLISHED.value: (
        "publication_id",
        "approval_ref",
        "command_id",
        "object_ref",
        "object_version",
        "action_key",
        "target_channels",
        "initial_propagation_status",
    ),
    GovernanceEventType.PROPAGATION_UPDATED.value: (
        "publication_id",
        "surface_id",
        "previous_status",
        "status",
        "previous_version",
        "version",
        "command_id",
    ),
    GovernanceEventType.STATE_IMPORTED.value: (
        "page_id",
        "page_version",
        "revision_round",
        "source",
    ),
}
if set(_DETAIL_KEYS) != set(_EVENT_PHASE):
    raise RuntimeError("governance audit detail map must cover every ledger event type")


_AUDIT_COVERAGE = (
    "review_transition",
    "approval_transition",
    "publish_transition",
    "recovery_transition",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceAuditQuery:
    phase: GovernanceAuditPhase | None = None
    event_type: GovernanceEventType | None = None
    draft_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    page: int = 1
    page_size: int = 50

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceAuditEntry:
    event_id: uuid.UUID
    draft_id: uuid.UUID
    sequence: int
    phase: GovernanceAuditPhase
    event_type: str
    from_state: str | None
    to_state: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    page_id: uuid.UUID | None
    page_slug: str | None
    page_title: str | None
    object_ref: str | None
    scope_type: str
    scope_id: str | None
    reason: str | None
    details: dict[str, object]
    occurred_at: str
    recorded_at: str

    @property
    def trace_ref(self) -> str:
        return f"governance-event:{self.event_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "trace_ref": self.trace_ref,
            "draft_id": str(self.draft_id),
            "sequence": self.sequence,
            "phase": self.phase.value,
            "event_type": self.event_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "actor": (
                {
                    "actor_id": str(self.actor_id),
                    "name": self.actor_name,
                }
                if self.actor_id is not None
                else None
            ),
            "resource": {
                "page_id": str(self.page_id) if self.page_id is not None else None,
                "slug": self.page_slug,
                "title": self.page_title,
                "object_ref": self.object_ref,
                "scope_type": self.scope_type,
                "scope_id": self.scope_id,
            },
            "reason": self.reason,
            "details": dict(self.details),
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "persisted": True,
            "rehearsal": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceAuditPage:

    items: tuple[GovernanceAuditEntry, ...]
    total: int
    page: int
    page_size: int

    def to_dict(self) -> dict[str, object]:
        from cygnus.review.surface import ObservationState, SurfaceObservation

        observation = SurfaceObservation(
            state=ObservationState.READY,
            observed_count=self.total,
            reason="durable_governance_ledger",
            covered_signals=_AUDIT_COVERAGE,
        )
        return {
            "items": [item.to_dict() for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "observation": observation.to_dict(),
            "persisted": True,
            "rehearsal": False,
        }


def governance_audit_phase(event_type: str) -> GovernanceAuditPhase:
    try:
        return _EVENT_PHASE[event_type]
    except KeyError as exc:
        raise ValueError(f"unsupported governance ledger event_type={event_type}") from exc


def governance_audit_scope_clause(
    current_user: Employee,
) -> ColumnElement[bool] | None:
    """Limit ledger rows to Wiki truth visible to the current user inside SQL."""
    permissions = get_effective_permissions(current_user)
    scope_level = get_scope_level(permissions, "wiki", "read")
    if current_user.role == "admin" or scope_level == "all":
        return None
    if scope_level is None:
        return GovernanceLedgerEvent.id.is_(None)

    wiki_scope = build_wiki_scope_clause(current_user)
    materialized_page_visible = exists(
        select(WikiPage.id)
        .correlate(GovernanceLedgerEvent)
        .join(WikiPageDraft, WikiPageDraft.page_id == WikiPage.id)
        .where(
            WikiPageDraft.id == GovernanceLedgerEvent.draft_id,
            *(() if wiki_scope is None else (wiki_scope,)),
        )
    )

    suggested_scope_type = func.coalesce(
        WikiPageDraft.suggested_metadata.op("->>")("scope_type"),
        "global",
    )
    suggested_scope_id = WikiPageDraft.suggested_metadata.op("->>")("scope_id")
    visible_unmaterialized_scope: ColumnElement[bool] = (
        suggested_scope_type == "global"
    )
    department_ids = tuple(str(value) for value in current_user.department_ids)
    if department_ids:
        visible_unmaterialized_scope = or_(
            visible_unmaterialized_scope,
            and_(
                suggested_scope_type == "department",
                suggested_scope_id.in_(department_ids),
            ),
        )
    unmaterialized_draft_visible = exists(
        select(WikiPageDraft.id)
        .correlate(GovernanceLedgerEvent)
        .where(
            WikiPageDraft.id == GovernanceLedgerEvent.draft_id,
            WikiPageDraft.page_id.is_(None),
            visible_unmaterialized_scope,
        )
    )
    return or_(materialized_page_visible, unmaterialized_draft_visible)


async def list_governance_audit_events(
    session: AsyncSession,
    *,
    current_user: Employee,
    query: GovernanceAuditQuery,
) -> GovernanceAuditPage:
    filters = _audit_filters(current_user=current_user, query=query)
    total = int(
        (
            await session.execute(
                select(func.count(GovernanceLedgerEvent.id)).where(*filters)
            )
        ).scalar_one()
    )
    statement = (
        select(GovernanceLedgerEvent, WikiPageDraft, WikiPage, Employee)
        .join(WikiPageDraft, WikiPageDraft.id == GovernanceLedgerEvent.draft_id)
        .outerjoin(WikiPage, WikiPage.id == WikiPageDraft.page_id)
        .outerjoin(Employee, Employee.id == GovernanceLedgerEvent.actor_id)
        .where(*filters)
        .order_by(
            GovernanceLedgerEvent.recorded_at.desc(),
            GovernanceLedgerEvent.id.desc(),
        )
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    raw_rows = (await session.execute(statement)).all()
    rows = cast(
        list[
            tuple[
                GovernanceLedgerEvent,
                WikiPageDraft,
                WikiPage | None,
                Employee | None,
            ]
        ],
        cast(object, raw_rows),
    )
    entries = tuple(
        governance_audit_entry(event=event, draft=draft, page=page, actor=actor)
        for event, draft, page, actor in rows
    )
    return GovernanceAuditPage(
        items=entries,
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


async def get_governance_audit_event(
    session: AsyncSession,
    *,
    current_user: Employee,
    event_id: uuid.UUID,
) -> GovernanceAuditEntry | None:
    filters: list[ColumnElement[bool]] = [GovernanceLedgerEvent.id == event_id]
    scope_clause = governance_audit_scope_clause(current_user)
    if scope_clause is not None:
        filters.append(scope_clause)
    statement = (
        select(GovernanceLedgerEvent, WikiPageDraft, WikiPage, Employee)
        .join(WikiPageDraft, WikiPageDraft.id == GovernanceLedgerEvent.draft_id)
        .outerjoin(WikiPage, WikiPage.id == WikiPageDraft.page_id)
        .outerjoin(Employee, Employee.id == GovernanceLedgerEvent.actor_id)
        .where(*filters)
    )
    raw_row = (await session.execute(statement)).one_or_none()
    row = cast(
        tuple[
            GovernanceLedgerEvent,
            WikiPageDraft,
            WikiPage | None,
            Employee | None,
        ]
        | None,
        cast(object, raw_row),
    )
    if row is None:
        return None
    event, draft, page, actor = row
    return governance_audit_entry(event=event, draft=draft, page=page, actor=actor)



def governance_audit_entry(
    *,
    event: GovernanceLedgerEvent,
    draft: WikiPageDraft,
    page: WikiPage | None,
    actor: Employee | None,
) -> GovernanceAuditEntry:
    payload = event.payload or {}
    details = {
        key: payload[key]
        for key in _DETAIL_KEYS[event.event_type]
        if key in payload
    }
    if event.event_type in {
        GovernanceEventType.APPROVED.value,
        GovernanceEventType.STATE_IMPORTED.value,
    }:
        details["approval_ref"] = str(event.id)

    suggested = draft.suggested_metadata or {}
    scope_type = _optional_string(suggested.get("scope_type")) or "global"
    scope_id = _optional_string(suggested.get("scope_id"))
    page_slug = _optional_string(suggested.get("slug"))
    page_title = _optional_string(suggested.get("title"))
    page_id = draft.page_id
    if page is not None:
        scope_type = page.scope_type or "global"
        scope_id = str(page.scope_id) if page.scope_id is not None else None
        page_slug = page.slug
        page_title = page.title
        page_id = page.id

    return GovernanceAuditEntry(
        event_id=event.id,
        draft_id=event.draft_id,
        sequence=event.sequence,
        phase=governance_audit_phase(event.event_type),
        event_type=event.event_type,
        from_state=event.from_state,
        to_state=event.to_state,
        actor_id=event.actor_id,
        actor_name=actor.name if actor is not None else None,
        page_id=page_id,
        page_slug=page_slug,
        page_title=page_title,
        object_ref=_optional_string(payload.get("object_ref")),
        scope_type=scope_type,
        scope_id=scope_id,
        reason=event.reason,
        details=details,
        occurred_at=event.occurred_at.isoformat(),
        recorded_at=event.recorded_at.isoformat(),
    )


def _audit_filters(
    *,
    current_user: Employee,
    query: GovernanceAuditQuery,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    scope_clause = governance_audit_scope_clause(current_user)
    if scope_clause is not None:
        filters.append(scope_clause)
    if query.phase is not None:
        filters.append(
            GovernanceLedgerEvent.event_type.in_(
                tuple(
                    event_type.value
                    for event_type in _PHASE_EVENT_TYPES[query.phase]
                )
            )
        )
    if query.event_type is not None:
        filters.append(GovernanceLedgerEvent.event_type == query.event_type.value)
    if query.draft_id is not None:
        filters.append(GovernanceLedgerEvent.draft_id == query.draft_id)
    if query.page_id is not None:
        filters.append(
            exists(
                select(WikiPageDraft.id)
                .correlate(GovernanceLedgerEvent)
                .where(

                    WikiPageDraft.id == GovernanceLedgerEvent.draft_id,
                    WikiPageDraft.page_id == query.page_id,
                )
            )
        )
    if query.actor_id is not None:
        filters.append(GovernanceLedgerEvent.actor_id == query.actor_id)
    return filters


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
