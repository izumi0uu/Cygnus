from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any, cast, final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain import AudienceContext
from cygnus.evidence.freshness import freshness_gate
from cygnus.governance import (
    AudienceBindingLifecycle,
    GovernanceEventType,
    list_audience_bindings,
    list_draft_events,
    publish_binding_from_record,
)
from cygnus.integrations.nanobot_tools import audience_context_from_payload
from cygnus.publish import (
    DurablePublishCommand,
    DurablePublishConflict,
    DurablePublishDenied,
    DurablePublishNotFound,
    apply_durable_publish,
    latest_publication_for_object,
)
from cygnus.retrieval.substrate_provider import wiki_page_to_knowledge_object
from cygnus.runtime.database.models import (
    Source,
    WikiPage,
    WikiPageDraft,
)
from cygnus.substrate.agent_protocol import ToolDefinition


@final
class GovernedPublishTools:
    """Request-scoped governed adapter for durable publication commands."""

    __slots__ = ("_actor_id", "_is_admin", "_session", "_visible_object_ids")

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_id: uuid.UUID,
        is_admin: bool,
        visible_object_ids: Iterable[str],
    ) -> None:
        self._session = session
        self._actor_id = actor_id
        self._is_admin = is_admin
        self._visible_object_ids = frozenset(visible_object_ids)

    @property
    def can_publish(self) -> bool:
        return self._is_admin

    async def validate_publish_policy(
        self,
        *,
        draft_id: str,
        target_channel: str,
        audience_context: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Validate current persisted publish truth without staging writes."""
        return await self._inspect_policy(
            draft_id=draft_id,
            target_channels=(target_channel,),
            audience_context=audience_context,
            expected_version=expected_version,
        )

    async def publish_knowledge_object(
        self,
        *,
        draft_id: str,
        approval_ref: str,
        approval_digest: str,
        scope_digest: str,
        signal_id: str,
        signal_freshness: str,
        command_id: str,
        action_key: str,
        target_channels: list[str],
        expected_version: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Stage one admin- and approval-gated durable publish transaction."""
        if not self._is_admin:
            return _error(
                status="denied",
                summary="Durable publication requires administrator permission.",
                code="admin_required",
            )

        try:
            command = DurablePublishCommand(
                draft_id=_parse_uuid(draft_id, label="draft_id"),
                approval_ref=_parse_uuid(approval_ref, label="approval_ref"),
                approval_digest=approval_digest,
                scope_digest=scope_digest,
                signal_id=_parse_uuid(signal_id, label="signal_id"),
                signal_freshness=signal_freshness,
                command_id=command_id,
                action_key=action_key,
                target_channels=tuple(target_channels),
                expected_version=expected_version,
                reason=reason,
            )
            result = await apply_durable_publish(
                self._session,
                command=command,
                actor_id=self._actor_id,
            )
        except DurablePublishNotFound:
            return _unavailable_draft()
        except DurablePublishConflict as exc:
            message = str(exc)
            return _error(
                status="conflict",
                summary=message,
                code="stale_version"
                if "version conflict" in message
                else "publish_conflict",
            )
        except DurablePublishDenied as exc:
            message = str(exc)
            approval_error = "not approved" in message or "approval_ref" in message
            return _error(
                status="approval_required" if approval_error else "denied",
                summary=message,
                code="approval_required" if approval_error else "publish_denied",
            )
        except ValueError as exc:
            return _error(
                status="invalid",
                summary=str(exc),
                code="invalid_arguments",
            )

        propagation_payload = result.get("propagation")
        pending = 0
        if isinstance(propagation_payload, dict):
            propagation = cast(dict[str, object], propagation_payload)
            summary_payload = propagation.get("summary")
            if isinstance(summary_payload, dict):
                summary = cast(dict[str, object], summary_payload)
                pending_value = summary.get("pending", 0)
                if isinstance(pending_value, int):
                    pending = pending_value
        warnings = ["downstream_propagation_pending"] if pending else []
        replayed = bool(result.get("replayed"))
        return {
            "status": "success",
            "summary": (
                "Durable publication replayed from the existing command."
                if replayed
                else "Durable publication committed; downstream propagation remains explicit."
            ),
            "data": result,
            **result,
            "warnings": warnings,
            "errors": [],
        }

    async def _inspect_policy(
        self,
        *,
        draft_id: str,
        target_channels: Iterable[str],
        audience_context: dict[str, Any] | None,
        expected_version: int | None,
    ) -> dict[str, Any]:
        try:
            parsed_draft_id = _parse_uuid(draft_id, label="draft_id")
            normalized_channels = _normalize_channels(target_channels)
            context = _parse_audience_context(audience_context)
            if expected_version is not None and expected_version < 1:
                raise ValueError("expected_version must be positive")
        except (TypeError, ValueError) as exc:
            return _error(
                status="invalid",
                summary=str(exc),
                code="invalid_arguments",
            )

        draft = await self._session.get(WikiPageDraft, parsed_draft_id)
        if draft is None or draft.page_id is None:
            return _unavailable_draft()
        page = await self._session.get(WikiPage, draft.page_id)
        if page is None:
            return _unavailable_draft()

        knowledge_object = wiki_page_to_knowledge_object(page)
        if knowledge_object is None:
            if not self._is_admin:
                return _unavailable_draft()
            return _error(
                status="denied",
                summary="The approved page is not a supported typed knowledge object.",
                code="unsupported_object_type",
            )
        if (
            not self._is_admin
            and knowledge_object.object_id not in self._visible_object_ids
        ):
            return _unavailable_draft()

        checks: list[dict[str, str]] = [
            _policy_check(
                "scope_visibility",
                "pass",
                "The draft resolves to an object in the caller's governed scope.",
            )
        ]
        common_data: dict[str, Any] = {
            "allowed": False,
            "draft_id": str(draft.id),
            "object_ref": knowledge_object.object_id,
            "object_version": page.version,
            "target_channel": (
                normalized_channels[0] if len(normalized_channels) == 1 else None
            ),
            "target_channels": list(normalized_channels),
            "policy_checks": checks,
        }

        checks.append(
            _policy_check(
                "publish_permission",
                "pass" if self._is_admin else "approval_required",
                "The caller has administrator publication permission."
                if self._is_admin
                else "An administrator must execute the durable publication.",
            )
        )

        if expected_version is not None and page.version != expected_version:
            checks.append(
                _policy_check(
                    "object_version",
                    "fail",
                    "The requested object version is stale.",
                )
            )
            return _error(
                status="conflict",
                summary="The expected object version no longer matches current truth.",
                code="stale_version",
                data=common_data,
            )
        checks.append(
            _policy_check(
                "object_version",
                "pass",
                "The requested version matches current object truth."
                if expected_version is not None
                else "Current object version loaded for a subsequent guarded publish.",
            )
        )

        if draft.status != "approved":
            checks.append(
                _policy_check(
                    "draft_approval",
                    "approval_required",
                    "The draft has not reached the approved lifecycle state.",
                )
            )
            return _error(
                status="approval_required",
                summary="The draft requires approval before durable publication.",
                code="approval_required",
                data=common_data,
            )

        events = await list_draft_events(self._session, draft.id)
        approval = next(
            (
                event
                for event in reversed(events)
                if event.to_state == "approved"
                and event.event_type
                in {
                    GovernanceEventType.APPROVED.value,
                    GovernanceEventType.STATE_IMPORTED.value,
                }
            ),
            None,
        )
        if approval is None:
            checks.append(
                _policy_check(
                    "approval_ledger",
                    "fail",
                    "The approved state has no durable approval ledger event.",
                )
            )
            return _error(
                status="denied",
                summary="The draft approval is not backed by durable governance truth.",
                code="approval_record_missing",
                data=common_data,
            )
        checks.extend(
            (
                _policy_check(
                    "draft_approval",
                    "pass",
                    "The draft is approved.",
                ),
                _policy_check(
                    "approval_ledger",
                    "pass",
                    "A durable approval ledger event authorizes publication.",
                ),
            )
        )
        common_data["approval_ref"] = str(approval.id)

        source_ids = tuple(dict.fromkeys(page.source_ids or ()))
        if not source_ids:
            checks.append(
                _policy_check(
                    "source_readiness",
                    "fail",
                    "Published objects require at least one linked source.",
                )
            )
            return _error(
                status="denied",
                summary="Publish policy rejected the object's source state.",
                code="source_not_ready",
                data=common_data,
            )
        source_rows = (
            (
                await self._session.execute(
                    select(Source).where(Source.id.in_(source_ids))
                )
            )
            .scalars()
            .all()
        )
        source_state = {source.id: source.status for source in source_rows}
        if any(source_state.get(source_id) != "ready" for source_id in source_ids):
            checks.append(
                _policy_check(
                    "source_readiness",
                    "fail",
                    "Every linked source must exist and be ready.",
                )
            )
            return _error(
                status="denied",
                summary="Publish policy rejected the object's source state.",
                code="source_not_ready",
                data=common_data,
            )
        checks.append(
            _policy_check(
                "source_readiness",
                "pass",
                "Every linked source exists and is ready.",
            )
        )

        freshness_gate_result = freshness_gate(source_rows)
        if not freshness_gate_result.passed:
            checks.append(
                _policy_check(
                    "source_freshness",
                    "fail",
                    "Every linked source must carry an explicit, unexpired FRESH "
                    "attestation.",
                )
            )
            return _error(
                status="denied",
                summary="Publish policy rejected the object's source freshness.",
                code="source_freshness_required",
                data=common_data,
            )
        checks.append(
            _policy_check(
                "source_freshness",
                "pass",
                "Every linked source carries an explicit, unexpired FRESH attestation.",
            )
        )

        binding_rows = await list_audience_bindings(
            self._session,
            page_id=page.id,
            object_ref=knowledge_object.object_id,
            lifecycle_state=AudienceBindingLifecycle.ACTIVE,
        )
        bindings = tuple(
            publish_binding_from_record(binding)
            for binding in binding_rows
            if binding.channel in normalized_channels
        )
        bound_channels = {binding.channel for binding in bindings}
        missing_channels = tuple(
            channel for channel in normalized_channels if channel not in bound_channels
        )
        if missing_channels:
            checks.append(
                _policy_check(
                    "audience_binding",
                    "fail",
                    "Every requested channel requires an explicit active audience binding.",
                )
            )
            return _error(
                status="denied",
                summary="Publish policy rejected one or more target channels.",
                code="audience_binding_missing",
                data=common_data,
            )
        checks.append(
            _policy_check(
                "audience_binding",
                "pass",
                "Every requested channel has an explicit active audience binding.",
            )
        )

        if context is not None:
            unmatched_channels = tuple(
                channel
                for channel in normalized_channels
                if not any(
                    binding.channel == channel
                    and binding.audience_filter.matches(context)
                    for binding in bindings
                )
            )
            if unmatched_channels:
                checks.append(
                    _policy_check(
                        "audience_context",
                        "fail",
                        "The supplied audience does not match every requested channel binding.",
                    )
                )
                return _error(
                    status="denied",
                    summary="Publish policy rejected the supplied audience context.",
                    code="audience_mismatch",
                    data=common_data,
                )
            checks.append(
                _policy_check(
                    "audience_context",
                    "pass",
                    "The supplied audience matches every requested channel binding.",
                )
            )

        previous_publication = await latest_publication_for_object(
            self._session,
            knowledge_object.object_id,
        )
        common_data.update(
            {
                "allowed": self._is_admin,
                "approval_required": not self._is_admin,
                "target_bindings": [binding.to_dict() for binding in bindings],
                "recommended_action_key": (
                    "republish" if previous_publication is not None else "publish"
                ),
                "previous_publication_id": (
                    str(previous_publication.id)
                    if previous_publication is not None
                    else None
                ),
            }
        )
        return {
            "status": "success" if self._is_admin else "approval_required",
            "summary": (
                "Publish policy allows an approval-backed durable command."
                if self._is_admin
                else "Publish policy is satisfied; administrator execution is required."
            ),
            "data": common_data,
            "warnings": [],
            "errors": [],
        }


def publish_tool_definitions() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            name="validate_publish_policy",
            description="Validate current durable approval, source, audience, and version truth before publication.",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "format": "uuid"},
                    "target_channel": {"type": "string"},
                    "audience_context": {"type": "object"},
                    "expected_version": {"type": "integer", "minimum": 1},
                },
                "required": ["draft_id", "target_channel"],
            },
            risk_level="R2",
        ),
        ToolDefinition(
            name="publish_knowledge_object",
            description="Commit one admin- and approval-gated durable Cygnus publication.",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "format": "uuid"},
                    "approval_ref": {"type": "string", "format": "uuid"},
                    "approval_digest": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "scope_digest": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "signal_id": {"type": "string", "format": "uuid"},
                    "signal_freshness": {
                        "type": "string",
                        "enum": ["fresh", "stale", "unknown"],
                    },
                    "command_id": {"type": "string"},
                    "action_key": {
                        "type": "string",
                        "enum": [
                            "publish",
                            "republish",
                            "restrict_publish",
                            "hold_external",
                            "republish_internal_only",
                        ],
                    },
                    "target_channels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "expected_version": {"type": "integer", "minimum": 1},
                    "reason": {"type": "string"},
                },
                "required": [
                    "draft_id",
                    "approval_ref",
                    "approval_digest",
                    "scope_digest",
                    "signal_id",
                    "signal_freshness",
                    "command_id",
                    "action_key",
                    "target_channels",
                    "expected_version",
                ],
            },
            risk_level="R3",
        ),
    )


def publish_tool_bindings(
    tools: GovernedPublishTools,
) -> tuple[tuple[ToolDefinition, Any], ...]:
    validate_definition, publish_definition = publish_tool_definitions()
    return (
        (validate_definition, tools.validate_publish_policy),
        (publish_definition, tools.publish_knowledge_object),
    )


def _parse_uuid(value: str, *, label: str) -> uuid.UUID:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    try:
        return uuid.UUID(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _normalize_channels(channels: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_channel in channels:
        channel = raw_channel.strip()
        if not channel:
            raise ValueError("target channels must not be blank")
        if channel not in normalized:
            normalized.append(channel)
    if not normalized:
        raise ValueError("target_channels must not be empty")
    return tuple(normalized)


def _parse_audience_context(
    payload: dict[str, Any] | None,
) -> AudienceContext | None:
    if payload is None:
        return None
    context = audience_context_from_payload(payload)
    if context is None:
        raise ValueError("audience_context.visibility is required")
    return context


def _policy_check(name: str, result: str, reason: str) -> dict[str, str]:
    return {"name": name, "result": result, "reason": reason}


def _unavailable_draft() -> dict[str, Any]:
    return _error(
        status="not_found",
        summary="The publish draft is unavailable in the caller's governed scope.",
        code="not_found",
    )


def _error(
    *,
    status: str,
    summary: str,
    code: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "data": data or {},
        "warnings": [],
        "errors": [code],
    }
