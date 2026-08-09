from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.governance.ledger import lock_governance_command
from cygnus.runtime.database.models import GovernanceAudienceBinding, WikiPage

if TYPE_CHECKING:
    from cygnus.publish.preview import PublishBinding, PublishConflict


class AudienceBindingNotFound(LookupError):
    pass


class AudienceBindingConflict(ValueError):
    pass


class AudienceBindingLifecycle(str, Enum):
    ACTIVE = "active"
    HELD = "held"
    REMOVED = "removed"


def _canonical_dimension(values: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError("audience dimension values must not be blank")
        normalized.add(value)
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceBindingCreate:
    page_id: uuid.UUID
    object_ref: str
    variant_ref: str
    channel: str
    audience_filter: AudienceFilter

    def __post_init__(self) -> None:
        object_ref = self.object_ref.strip()
        variant_ref = self.variant_ref.strip()
        channel = self.channel.strip()
        if not object_ref:
            raise ValueError("object_ref must not be blank")
        if not variant_ref:
            raise ValueError("variant_ref must not be blank")
        if not channel:
            raise ValueError("channel must not be blank")
        object.__setattr__(self, "object_ref", object_ref)
        object.__setattr__(self, "variant_ref", variant_ref)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(
            self,
            "audience_filter",
            AudienceFilter(
                visibility=self.audience_filter.visibility,
                brands=_canonical_dimension(self.audience_filter.brands),
                product_lines=_canonical_dimension(self.audience_filter.product_lines),
                plans=_canonical_dimension(self.audience_filter.plans),
                regions=_canonical_dimension(self.audience_filter.regions),
                languages=_canonical_dimension(self.audience_filter.languages),
                product_versions=_canonical_dimension(
                    self.audience_filter.product_versions
                ),
            ),
        )

    @property
    def binding_key(self) -> str:
        payload = {
            "page_id": str(self.page_id),
            "object_ref": self.object_ref,
            "variant_ref": self.variant_ref,
            "channel": self.channel,
            "audience_filter": self.audience_filter.to_dict(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceBindingConflictRecord:
    left: GovernanceAudienceBinding
    right: GovernanceAudienceBinding

    @property
    def conflict_ref(self) -> str:
        ordered = sorted((str(self.left.id), str(self.right.id)))
        return "audience-conflict:" + hashlib.sha256(":".join(ordered).encode()).hexdigest()

    @property
    def reason(self) -> str:
        return (
            f"Active variants {self.left.variant_ref} and {self.right.variant_ref} "
            f"overlap on {self.left.channel} for {self.left.visibility} visibility."
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "conflict_ref": self.conflict_ref,
            "object_ref": self.left.object_ref,
            "page_id": str(self.left.page_id),
            "channel": self.left.channel,
            "visibility": self.left.visibility,
            "variant_refs": [self.left.variant_ref, self.right.variant_ref],
            "binding_refs": [self.left.binding_key, self.right.binding_key],
            "reason": self.reason,
            "left": audience_binding_to_dict(self.left),
            "right": audience_binding_to_dict(self.right),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceConflictProviderData:
    conflicts: tuple[AudienceBindingConflictRecord, ...]
    covered_signals: tuple[str, ...] = field(default=("audience_conflict",))

    def to_dict(self) -> dict[str, object]:
        return {
            "covered_signals": list(self.covered_signals),
            "observed_count": len(self.conflicts),
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
        }


async def create_audience_binding(
    session: AsyncSession,
    *,
    command: AudienceBindingCreate,
    actor_id: uuid.UUID,
) -> tuple[GovernanceAudienceBinding, bool]:
    """Create one explicit binding, replaying the same semantic command safely."""
    await lock_governance_command(session, f"audience-binding:{command.binding_key}")
    existing = (
        await session.execute(
            select(GovernanceAudienceBinding).where(
                GovernanceAudienceBinding.binding_key == command.binding_key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    page = await session.get(WikiPage, command.page_id)
    if page is None:
        raise AudienceBindingNotFound(f"page_id={command.page_id} was not found")
    expected_object_ref = f"ko-{page.slug}"
    if command.object_ref != expected_object_ref:
        raise AudienceBindingConflict(
            f"object_ref={command.object_ref} does not identify page_id={page.id} "
            f"(expected {expected_object_ref})"
        )

    audience = command.audience_filter
    record = GovernanceAudienceBinding(
        page_id=page.id,
        object_ref=command.object_ref,
        variant_ref=command.variant_ref,
        channel=command.channel,
        visibility=audience.visibility.value,
        brands=list(audience.brands),
        product_lines=list(audience.product_lines),
        plans=list(audience.plans),
        regions=list(audience.regions),
        languages=list(audience.languages),
        product_versions=list(audience.product_versions),
        lifecycle_state=AudienceBindingLifecycle.ACTIVE.value,
        binding_key=command.binding_key,
        created_by_id=actor_id,
        version=1,
    )
    session.add(record)
    await session.flush()
    return record, False


async def update_audience_binding_lifecycle(
    session: AsyncSession,
    *,
    binding_id: uuid.UUID,
    lifecycle_state: AudienceBindingLifecycle,
    expected_version: int,
) -> tuple[GovernanceAudienceBinding, bool]:
    if expected_version < 1:
        raise ValueError("expected_version must be positive")
    record = (
        await session.execute(
            select(GovernanceAudienceBinding)
            .where(GovernanceAudienceBinding.id == binding_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if record is None:
        raise AudienceBindingNotFound(f"binding_id={binding_id} was not found")
    if record.lifecycle_state == lifecycle_state.value:
        return record, True
    if record.version != expected_version:
        raise AudienceBindingConflict(
            f"binding_id={binding_id} version changed "
            f"(expected {expected_version}, actual {record.version})"
        )
    record.lifecycle_state = lifecycle_state.value
    record.version += 1
    await session.flush()
    return record, False


async def list_audience_bindings(
    session: AsyncSession,
    *,
    page_id: uuid.UUID | None = None,
    object_ref: str | None = None,
    channel: str | None = None,
    lifecycle_state: AudienceBindingLifecycle | None = None,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> tuple[GovernanceAudienceBinding, ...]:
    """List bindings with Wiki scope applied in SQL before rows are projected."""
    statement = select(GovernanceAudienceBinding).join(
        WikiPage, WikiPage.id == GovernanceAudienceBinding.page_id
    )
    if page_id is not None:
        statement = statement.where(GovernanceAudienceBinding.page_id == page_id)
    if object_ref is not None:
        statement = statement.where(GovernanceAudienceBinding.object_ref == object_ref)
    if channel is not None:
        statement = statement.where(GovernanceAudienceBinding.channel == channel)
    if lifecycle_state is not None:
        statement = statement.where(
            GovernanceAudienceBinding.lifecycle_state == lifecycle_state.value
        )
    if page_scope_clause is not None:
        statement = statement.where(page_scope_clause)
    statement = statement.order_by(
        GovernanceAudienceBinding.object_ref,
        GovernanceAudienceBinding.channel,
        GovernanceAudienceBinding.visibility,
        GovernanceAudienceBinding.variant_ref,
        GovernanceAudienceBinding.binding_key,
    )
    return tuple((await session.execute(statement)).scalars().all())


def audience_filter_from_binding(record: GovernanceAudienceBinding) -> AudienceFilter:
    return AudienceFilter(
        visibility=Visibility(record.visibility),
        brands=tuple(record.brands),
        product_lines=tuple(record.product_lines),
        plans=tuple(record.plans),
        regions=tuple(record.regions),
        languages=tuple(record.languages),
        product_versions=tuple(record.product_versions),
    )


def publish_binding_from_record(record: GovernanceAudienceBinding) -> PublishBinding:
    from cygnus.publish.preview import PublishBinding
    return PublishBinding(
        audience_filter=audience_filter_from_binding(record),
        channel=record.channel,
    )


def audience_filters_overlap(
    left: AudienceFilter,
    right: AudienceFilter,
) -> bool:
    if left.visibility is not right.visibility:
        return False
    return all(
        not left_values
        or not right_values
        or bool(set(left_values).intersection(right_values))
        for left_values, right_values in (
            (left.brands, right.brands),
            (left.product_lines, right.product_lines),
            (left.plans, right.plans),
            (left.regions, right.regions),
            (left.languages, right.languages),
            (left.product_versions, right.product_versions),
        )
    )


def detect_audience_binding_conflicts(
    bindings: Iterable[GovernanceAudienceBinding],
) -> tuple[AudienceBindingConflictRecord, ...]:
    active = tuple(
        sorted(
            (
                binding
                for binding in bindings
                if binding.lifecycle_state == AudienceBindingLifecycle.ACTIVE.value
            ),
            key=lambda item: (
                item.object_ref,
                item.channel,
                item.visibility,
                item.variant_ref,
                item.binding_key,
            ),
        )
    )
    conflicts: list[AudienceBindingConflictRecord] = []
    for left, right in combinations(active, 2):
        if left.page_id != right.page_id or left.object_ref != right.object_ref:
            continue
        if left.channel != right.channel or left.visibility != right.visibility:
            continue
        if left.variant_ref == right.variant_ref:
            continue
        if not audience_filters_overlap(
            audience_filter_from_binding(left),
            audience_filter_from_binding(right),
        ):
            continue
        conflicts.append(AudienceBindingConflictRecord(left=left, right=right))
    return tuple(conflicts)


def publish_conflicts_from_records(
    bindings: Iterable[GovernanceAudienceBinding],
) -> tuple[PublishConflict, ...]:
    from cygnus.publish.preview import PublishConflict
    by_key: dict[tuple[AudienceFilter, str], PublishConflict] = {}
    for conflict in detect_audience_binding_conflicts(bindings):
        for record in (conflict.left, conflict.right):
            audience = audience_filter_from_binding(record)
            blocked = PublishConflict(
                audience_filter=audience,
                channel=record.channel,
                reason=conflict.reason,
            )
            by_key[blocked.key] = blocked
    return tuple(by_key[key] for key in sorted(by_key, key=lambda item: repr(item)))


async def load_audience_conflict_provider_data(
    session: AsyncSession,
    *,
    page_id: uuid.UUID | None = None,
    object_ref: str | None = None,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> AudienceConflictProviderData:
    bindings = await list_audience_bindings(
        session,
        page_id=page_id,
        object_ref=object_ref,
        lifecycle_state=AudienceBindingLifecycle.ACTIVE,
        page_scope_clause=page_scope_clause,
    )
    return AudienceConflictProviderData(
        conflicts=detect_audience_binding_conflicts(bindings)
    )


def audience_binding_to_dict(
    record: GovernanceAudienceBinding,
) -> dict[str, object]:
    return {
        "id": str(record.id),
        "page_id": str(record.page_id),
        "object_ref": record.object_ref,
        "variant_ref": record.variant_ref,
        "channel": record.channel,
        "visibility": record.visibility,
        "audience_filter": audience_filter_from_binding(record).to_dict(),
        "lifecycle_state": record.lifecycle_state,
        "binding_key": record.binding_key,
        "created_by_id": str(record.created_by_id),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "version": record.version,
    }
