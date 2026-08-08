from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.governance.ledger import (
    GovernanceEventType,
    append_draft_event,
    dedupe_strings,
    get_approval_event,
    get_latest_draft_event,
    lock_draft_aggregate,
    lock_governance_command,
)
from cygnus.publish.actions import (
    PublishGovernanceAction,
    PublishGovernanceActionType,
    PublishGovernanceResult,
    apply_publish_governance_actions,
)
from cygnus.publish.preview import (
    PublishActionType,
    PublishBinding,
    PublishPreviewCandidate,
)
from cygnus.publish.propagation import PropagationStatus
from cygnus.retrieval.substrate_provider import wiki_page_to_knowledge_object
from cygnus.runtime.database.models import (
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePublication,
    Source,
    WikiPage,
    WikiPageDraft,
)


class DurablePublishNotFound(LookupError):
    pass


class DurablePublishDenied(ValueError):
    pass


class DurablePublishConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class DurablePublishCommand:
    draft_id: uuid.UUID
    approval_ref: uuid.UUID
    command_id: str
    action_key: str
    target_channels: tuple[str, ...]
    reason: str | None = None

    def __post_init__(self) -> None:
        command_id = self.command_id.strip()
        action_key = self.action_key.strip()
        reason = self.reason.strip() if self.reason is not None else None
        if not command_id:
            raise ValueError("command_id must not be blank")
        if len(command_id) > 200:
            raise ValueError("command_id must not exceed 200 characters")
        if not action_key:
            raise ValueError("action_key must not be blank")
        if reason == "":
            raise ValueError("reason must not be blank when provided")
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "action_key", action_key)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "target_channels",
            dedupe_strings(self.target_channels, label="target channel"),
        )
        if not self.target_channels:
            raise ValueError("target_channels must not be empty")

    @property
    def request_fingerprint(self) -> str:
        payload = {
            "draft_id": str(self.draft_id),
            "approval_ref": str(self.approval_ref),
            "action_key": self.action_key,
            "target_channels": list(self.target_channels),
            "reason": self.reason,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class PropagationUpdateCommand:
    publication_id: uuid.UUID
    surface_id: str
    status: PropagationStatus
    expected_version: int
    command_id: str
    reason: str
    follow_up_commands: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        surface_id = self.surface_id.strip()
        command_id = self.command_id.strip()
        reason = self.reason.strip()
        if not surface_id:
            raise ValueError("surface_id must not be blank")
        if not command_id:
            raise ValueError("command_id must not be blank")
        if len(command_id) > 200:
            raise ValueError("command_id must not exceed 200 characters")
        if not reason:
            raise ValueError("reason must not be blank")
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        object.__setattr__(self, "surface_id", surface_id)
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "follow_up_commands",
            dedupe_strings(self.follow_up_commands, label="follow-up command"),
        )

    @property
    def request_fingerprint(self) -> str:
        payload = {
            "publication_id": str(self.publication_id),
            "surface_id": self.surface_id,
            "status": self.status.value,
            "expected_version": self.expected_version,
            "reason": self.reason,
            "follow_up_commands": list(self.follow_up_commands),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()


async def apply_durable_publish(
    session: AsyncSession,
    *,
    command: DurablePublishCommand,
    actor_id: uuid.UUID,
) -> dict[str, object]:
    """Execute and atomically stage one qualified durable publication."""
    await lock_draft_aggregate(session, command.draft_id)
    await lock_governance_command(session, f"publish:{command.command_id}")

    existing = (
        await session.execute(
            select(GovernancePublication).where(
                GovernancePublication.command_id == command.command_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.draft_id != command.draft_id
            or existing.request_fingerprint != command.request_fingerprint
        ):
            raise DurablePublishConflict(
                f"command_id={command.command_id} is already bound to a different publish request"
            )
        existing_propagations = await list_publication_propagations(
            session, existing.id
        )
        return durable_publication_result(
            existing,
            propagations=existing_propagations,
            replayed=True,
        )

    draft = (
        await session.execute(
            select(WikiPageDraft).where(WikiPageDraft.id == command.draft_id)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise DurablePublishNotFound(f"draft_id={command.draft_id} was not found")
    if draft.status != "approved":
        raise DurablePublishDenied(
            f"draft_id={command.draft_id} is not approved (status={draft.status})"
        )
    approval_event = await get_approval_event(
        session,
        draft_id=draft.id,
        approval_ref=command.approval_ref,
    )
    if approval_event is None:
        raise DurablePublishDenied(
            f"approval_ref={command.approval_ref} is not an approval for draft_id={draft.id}"
        )
    if draft.page_id is None:
        raise DurablePublishDenied("approved draft has no materialized WikiPage")
    page = (
        await session.execute(
            select(WikiPage).where(WikiPage.id == draft.page_id).with_for_update()
        )
    ).scalar_one_or_none()
    if page is None:
        raise DurablePublishDenied("approved draft has no materialized WikiPage")

    source_ids = tuple(dict.fromkeys(page.source_ids or ()))
    if not source_ids:
        raise DurablePublishDenied(
            "published objects must reference at least one source"
        )
    sources = tuple(
        (await session.execute(select(Source).where(Source.id.in_(source_ids))))
        .scalars()
        .all()
    )
    source_by_id = {source.id: source for source in sources}
    missing_source_ids = tuple(
        source_id for source_id in source_ids if source_id not in source_by_id
    )
    non_ready_source_ids = tuple(
        source_id
        for source_id in source_ids
        if source_id in source_by_id and source_by_id[source_id].status != "ready"
    )
    if missing_source_ids or non_ready_source_ids:
        raise DurablePublishDenied(
            "published objects require every linked source to exist and be ready"
        )

    evidence_ids = tuple(f"ev-src-{source_id}" for source_id in source_ids)
    knowledge_object = wiki_page_to_knowledge_object(
        page,
        evidence_ids=evidence_ids,
    )
    if knowledge_object is None:
        raise DurablePublishDenied(
            "approved WikiPage must declare one supported knowledge object type"
        )

    previous_publication = await latest_publication_for_object(
        session,
        knowledge_object.object_id,
    )
    if previous_publication is None and command.action_key != "publish":
        raise DurablePublishDenied(
            "the first durable command for an object must use action_key=publish"
        )
    current_bindings = (
        _bindings_from_candidate(previous_publication.candidate)
        if previous_publication is not None
        else ()
    )
    action_type = (
        PublishActionType.PUBLISH
        if previous_publication is None
        else PublishActionType.REPUBLISH
    )
    target_bindings = tuple(
        PublishBinding(audience_filter=audience, channel=channel)
        for audience in knowledge_object.supported_audiences
        for channel in command.target_channels
    )
    candidate = PublishPreviewCandidate(
        object_id=knowledge_object.object_id,
        object_type=knowledge_object.object_type,
        title=knowledge_object.title,
        action_type=action_type,
        target_audiences=knowledge_object.supported_audiences,
        target_channels=command.target_channels,
        target_bindings=target_bindings,
        current_bindings=current_bindings,
    )
    result = execute_durable_publish_action(
        candidate,
        command.action_key,
        reason=command.reason,
    )

    publication_id = uuid.uuid4()
    effective_bindings = result.updated_candidate.target_bindings
    previous_object_status = page.status
    effective_object_status = (
        previous_object_status
        if previous_object_status == "evergreen"
        else "mature"
        if effective_bindings
        else "developing"
    )
    publish_event = await append_draft_event(
        session,
        draft_id=draft.id,
        event_type=GovernanceEventType.PUBLISHED,
        from_state="published" if current_bindings else "approved",
        to_state="published" if effective_bindings else "approved",
        actor_id=actor_id,
        idempotency_key=f"publish:{command.command_id}",
        reason=command.reason or f"durable publish action {command.action_key}",
        payload={
            "publication_id": str(publication_id),
            "approval_ref": str(command.approval_ref),
            "command_id": command.command_id,
            "request_fingerprint": command.request_fingerprint,
            "object_ref": knowledge_object.object_id,
            "object_version": page.version,
            "action_key": command.action_key,
            "target_channels": list(command.target_channels),
            "reason": command.reason,
            "initial_propagation_status": PropagationStatus.PENDING.value,
        },
        lock=False,
    )
    page.status = effective_object_status
    publication = GovernancePublication(
        id=publication_id,
        draft_id=draft.id,
        page_id=page.id,
        approval_event_id=approval_event.id,
        publish_event_id=publish_event.id,
        command_id=command.command_id,
        request_fingerprint=command.request_fingerprint,
        object_ref=knowledge_object.object_id,
        object_type=knowledge_object.object_type.value,
        object_version=page.version,
        action_key=command.action_key,
        target_channels=list(command.target_channels),
        previous_object_status=previous_object_status,
        effective_object_status=effective_object_status,
        candidate=result.updated_candidate.to_dict(),
        preview=result.preview.to_dict(),
        opened_bindings=[binding.to_dict() for binding in result.opened_bindings],
        removed_bindings=[binding.to_dict() for binding in result.removed_bindings],
        held_bindings=[binding.to_dict() for binding in result.held_bindings],
        action_log=list(result.action_log),
        published_by_id=actor_id,
    )
    session.add(publication)
    await session.flush()

    affected_channels = dedupe_strings(
        (
            *command.target_channels,
            *(binding.channel for binding in current_bindings),
            *(binding.channel for binding in result.removed_bindings),
        ),
        label="affected channel",
    )
    new_propagations: list[GovernancePropagation] = []
    for channel in affected_channels:
        binding_refs = _binding_dicts_for_channel(result, channel)
        propagation = GovernancePropagation(
            publication_id=publication.id,
            surface_id=channel,
            status=PropagationStatus.PENDING.value,
            reason="awaiting_downstream_confirmation",
            channel_refs=[channel],
            binding_refs=binding_refs,
            follow_up_commands=[f"confirm_propagation:{publication.id}:{channel}"],
            version=1,
            last_event_id=publish_event.id,
            updated_by_id=actor_id,
        )
        session.add(propagation)
        new_propagations.append(propagation)

    await session.flush()
    return durable_publication_result(
        publication,
        propagations=tuple(new_propagations),
        replayed=False,
    )


def execute_durable_publish_action(
    candidate: PublishPreviewCandidate,
    action_key: str,
    *,
    reason: str | None = None,
) -> PublishGovernanceResult:
    """Map a durable command key onto the existing governed publish kernel."""
    normalized = action_key.strip()
    reason_by_action = {
        "publish": "open the approved governed publish path",
        "republish": "refresh the approved governed publish path",
        "restrict_publish": "withdraw the selected governed publish path",
        "hold_external": "hold external exposure pending explicit confirmation",
        "republish_internal_only": "keep internal support truth live while external exposure stops",
    }
    if normalized not in reason_by_action:
        raise DurablePublishDenied(f"unsupported durable action_key={normalized}")
    if normalized == "hold_external" and not any(
        audience.visibility is Visibility.EXTERNAL
        for audience in candidate.target_audiences
    ):
        raise DurablePublishDenied(
            "hold_external is unavailable because the persisted object has no external audience"
        )

    if normalized in {"publish", "republish"}:
        action_type = PublishGovernanceActionType.PUBLISH
        audiences: tuple[AudienceFilter, ...] = ()
    elif normalized == "restrict_publish":
        action_type = PublishGovernanceActionType.RESTRICT
        audiences = candidate.target_audiences
    elif normalized == "hold_external":
        action_type = PublishGovernanceActionType.HOLD_EXTERNAL
        audiences = ()
    else:
        action_type = PublishGovernanceActionType.REPUBLISH_INTERNAL_ONLY
        audiences = ()

    return apply_publish_governance_actions(
        candidate,
        (
            PublishGovernanceAction(
                action_type=action_type,
                audiences=audiences,
                channels=candidate.target_channels,
                reason=reason or reason_by_action[normalized],
            ),
        ),
    )


async def update_propagation(
    session: AsyncSession,
    *,
    command: PropagationUpdateCommand,
    actor_id: uuid.UUID,
) -> dict[str, object]:
    publication = await get_publication(session, command.publication_id)
    if publication is None:
        raise DurablePublishNotFound(
            f"publication_id={command.publication_id} was not found"
        )
    await lock_draft_aggregate(session, publication.draft_id)
    await lock_governance_command(session, f"propagation:{command.command_id}")

    idempotency_key = f"propagation:{command.command_id}"
    existing_event = (
        await session.execute(
            select(GovernanceLedgerEvent).where(
                GovernanceLedgerEvent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        payload = existing_event.payload
        if payload.get("request_fingerprint") != command.request_fingerprint:
            raise DurablePublishConflict(
                f"command_id={command.command_id} is already bound to a different propagation update"
            )
        raw_result_payload: object = payload.get("result")
        if not isinstance(raw_result_payload, dict):
            raise DurablePublishConflict(
                f"command_id={command.command_id} has no replayable propagation result"
            )
        result_payload = cast(dict[str, object], raw_result_payload)
        return result_payload | {"replayed": True}

    propagation = (
        await session.execute(
            select(GovernancePropagation)
            .where(
                GovernancePropagation.publication_id == command.publication_id,
                GovernancePropagation.surface_id == command.surface_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if propagation is None:
        raise DurablePublishNotFound(
            f"surface_id={command.surface_id} is not part of publication_id={command.publication_id}"
        )
    if propagation.version != command.expected_version:
        raise DurablePublishConflict(
            f"propagation version conflict: expected {command.expected_version}, current {propagation.version}"
        )

    previous_status = propagation.status
    next_version = propagation.version + 1
    result_payload: dict[str, object] = {
        "propagation_id": str(propagation.id),
        "publication_id": str(propagation.publication_id),
        "surface_id": propagation.surface_id,
        "status": command.status.value,
        "reason": command.reason,
        "version": next_version,
        "follow_up_commands": list(command.follow_up_commands),
        "persisted": True,
        "rehearsal": False,
    }
    current_event = await get_latest_draft_event(session, publication.draft_id)
    if current_event is None:
        raise DurablePublishConflict(
            f"draft_id={publication.draft_id} has no governance state"
        )
    event = await append_draft_event(
        session,
        draft_id=publication.draft_id,
        event_type=GovernanceEventType.PROPAGATION_UPDATED,
        from_state=current_event.to_state,
        to_state=current_event.to_state,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        reason=command.reason,
        payload={
            "publication_id": str(publication.id),
            "surface_id": propagation.surface_id,
            "previous_status": previous_status,
            "status": command.status.value,
            "previous_version": propagation.version,
            "version": next_version,
            "command_id": command.command_id,
            "request_fingerprint": command.request_fingerprint,
            "result": result_payload,
        },
        lock=False,
    )
    propagation.status = command.status.value
    propagation.reason = command.reason
    propagation.follow_up_commands = list(command.follow_up_commands)
    propagation.version = next_version
    propagation.last_event_id = event.id
    propagation.updated_by_id = actor_id
    await session.flush()
    return result_payload | {"ledger_event_id": str(event.id), "replayed": False}


async def get_publication(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> GovernancePublication | None:
    return await session.get(GovernancePublication, publication_id)


async def list_draft_publications(
    session: AsyncSession,
    draft_id: uuid.UUID,
) -> tuple[GovernancePublication, ...]:
    records = (
        (
            await session.execute(
                select(GovernancePublication)
                .where(GovernancePublication.draft_id == draft_id)
                .order_by(
                    GovernancePublication.published_at,
                    GovernancePublication.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return tuple(records)


async def latest_publication_for_object(
    session: AsyncSession,
    object_ref: str,
) -> GovernancePublication | None:
    return (
        await session.execute(
            select(GovernancePublication)
            .where(GovernancePublication.object_ref == object_ref)
            .order_by(
                GovernancePublication.published_at.desc(),
                GovernancePublication.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_publication_propagations(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> tuple[GovernancePropagation, ...]:
    records = (
        (
            await session.execute(
                select(GovernancePropagation)
                .where(GovernancePropagation.publication_id == publication_id)
                .order_by(GovernancePropagation.surface_id)
            )
        )
        .scalars()
        .all()
    )
    return tuple(records)


def durable_publication_result(
    publication: GovernancePublication,
    *,
    propagations: tuple[GovernancePropagation, ...],
    replayed: bool,
) -> dict[str, object]:
    return {
        "selected_action": publication.action_key,
        "action_log": list(publication.action_log),
        "opened_bindings": list(publication.opened_bindings),
        "removed_bindings": list(publication.removed_bindings),
        "held_bindings": list(publication.held_bindings),
        "updated_candidate": dict(publication.candidate),
        "preview": dict(publication.preview),
        "rehearsal": False,
        "persisted": True,
        "replayed": replayed,
        "publication_record_id": str(publication.id),
        "ledger_event_id": str(publication.publish_event_id),
        "approval_ref": str(publication.approval_event_id),
        "command_id": publication.command_id,
        "object_ref": publication.object_ref,
        "object_version": publication.object_version,
        "published_at": publication.published_at.isoformat(),
        "propagation": propagation_summary(propagations),
    }


def propagation_summary(
    propagations: tuple[GovernancePropagation, ...],
) -> dict[str, object]:
    counts = {status.value: 0 for status in PropagationStatus}
    for propagation in propagations:
        counts[propagation.status] = counts.get(propagation.status, 0) + 1
    return {
        "summary": counts,
        "records": [propagation_to_dict(record) for record in propagations],
    }


def propagation_to_dict(record: GovernancePropagation) -> dict[str, object]:
    return {
        "propagation_id": str(record.id),
        "publication_id": str(record.publication_id),
        "surface_id": record.surface_id,
        "status": record.status,
        "reason": record.reason,
        "channel_refs": list(record.channel_refs),
        "binding_refs": list(record.binding_refs),
        "follow_up_commands": list(record.follow_up_commands),
        "version": record.version,
        "last_event_id": str(record.last_event_id),
        "updated_by_id": (
            str(record.updated_by_id) if record.updated_by_id is not None else None
        ),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def publication_to_dict(
    publication: GovernancePublication,
    *,
    propagations: tuple[GovernancePropagation, ...],
) -> dict[str, object]:
    return {
        "publication_record_id": str(publication.id),
        "draft_id": str(publication.draft_id),
        "page_id": str(publication.page_id),
        "approval_ref": str(publication.approval_event_id),
        "ledger_event_id": str(publication.publish_event_id),
        "command_id": publication.command_id,
        "object_ref": publication.object_ref,
        "object_type": publication.object_type,
        "object_version": publication.object_version,
        "action_key": publication.action_key,
        "target_channels": list(publication.target_channels),
        "previous_object_status": publication.previous_object_status,
        "effective_object_status": publication.effective_object_status,
        "published_by_id": (
            str(publication.published_by_id)
            if publication.published_by_id is not None
            else None
        ),
        "published_at": publication.published_at.isoformat(),
        "result": durable_publication_result(
            publication,
            propagations=propagations,
            replayed=False,
        ),
    }


def _bindings_from_candidate(
    candidate_payload: dict[str, object],
) -> tuple[PublishBinding, ...]:
    raw_bindings = candidate_payload.get("target_bindings")
    if not isinstance(raw_bindings, list):
        raise DurablePublishConflict(
            "stored publication candidate has invalid target_bindings"
        )
    return tuple(_binding_from_dict(item) for item in cast(list[object], raw_bindings))


def _binding_from_dict(payload: object) -> PublishBinding:
    if not isinstance(payload, dict):
        raise DurablePublishConflict("stored publish binding must be an object")
    binding_payload = cast(dict[str, object], payload)
    audience_payload = binding_payload.get("audience_filter")
    channel = binding_payload.get("channel")
    if not isinstance(audience_payload, dict) or not isinstance(channel, str):
        raise DurablePublishConflict(
            "stored publish binding is missing audience/channel"
        )
    audience_mapping = cast(dict[str, object], audience_payload)
    visibility = audience_mapping.get("visibility")
    if not isinstance(visibility, str):
        raise DurablePublishConflict("stored audience is missing visibility")

    def _dimension(name: str) -> tuple[str, ...]:
        value: object = audience_mapping.get(name, [])
        if not isinstance(value, list):
            raise DurablePublishConflict(f"stored audience dimension {name} is invalid")
        dimension_values = cast(list[object], value)
        if not all(isinstance(item, str) for item in dimension_values):
            raise DurablePublishConflict(f"stored audience dimension {name} is invalid")
        return tuple(cast(list[str], dimension_values))

    audience = AudienceFilter(
        visibility=Visibility(visibility),
        brands=_dimension("brands"),
        product_lines=_dimension("product_lines"),
        plans=_dimension("plans"),
        regions=_dimension("regions"),
        languages=_dimension("languages"),
        product_versions=_dimension("product_versions"),
    )
    return PublishBinding(audience_filter=audience, channel=channel)


def _binding_dicts_for_channel(
    result: PublishGovernanceResult,
    channel: str,
) -> list[dict[str, object]]:
    by_key: dict[tuple[AudienceFilter, str], dict[str, object]] = {}
    for binding in (
        *result.updated_candidate.target_bindings,
        *result.removed_bindings,
    ):
        if binding.channel == channel:
            by_key[binding.key] = binding.to_dict()
    return list(by_key.values())
