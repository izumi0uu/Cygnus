from __future__ import annotations

import hashlib
import asyncio
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from typing import Any, cast
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cygnus.domain import AudienceFilter, Visibility
from cygnus.domain.objects import governed_object_ref
from cygnus.governance import (
    AudienceBindingCreate,
    GovernanceEventType,
    GovernanceLedgerConflict,
    append_draft_event,
    approval_digest,
    create_audience_binding,
    list_draft_events,
)
from cygnus.governance.ledger import record_draft_update
from cygnus.publish import (
    DurablePublishCommand,
    DurablePublishConflict,
    DurablePublishDenied,
    PropagationStatus,
    PropagationUpdateCommand,
    acknowledge_propagation_delivery,
    apply_durable_publish,
    durable_publish_command_for_signal,
    get_publication,
    list_propagation_deliveries,
    list_publication_propagations,
    update_propagation,
)
from cygnus.publish.delivery import canonical_json, sign_body

from cygnus.review.contributions import approve_wiki_draft, create_wiki_draft
from cygnus.runtime.services import wiki_service
from cygnus.runtime.services.auth_service import require_admin
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
    GovernanceSignal,
    Source,
    WikiPage,
    WikiPageDraft,
    WikiPageRevision,
)
from cygnus.runtime.routers.governance.dependencies import (
    get_durable_publish_projection,
)
from cygnus.runtime.routers.governance.publish import (
    PublishApplyRequest,
    publish_apply,
)

_LEDGER_ACK_SECRET = "cyg138-ledger-test-ack-secret"


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value: object = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _LedgerSession:
    def __init__(self, execute_results: list[object]) -> None:
        self.execute: AsyncMock = AsyncMock(
            side_effect=[_ScalarResult(value) for value in execute_results]
        )
        self.flush: AsyncMock = AsyncMock()
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


class GovernanceLedgerUnitTests(unittest.TestCase):
    def test_append_rejects_a_transition_from_stale_state(self) -> None:
        draft_id = uuid.uuid4()
        current = SimpleNamespace(sequence=4, to_state="needs_revision")
        fake = _LedgerSession([None, current])

        with patch(
            "cygnus.governance.ledger.lock_draft_aggregate",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(
                GovernanceLedgerConflict,
                "expected needs_revision, got in_review",
            ):
                _ = asyncio.run(
                    append_draft_event(
                        cast(AsyncSession, cast(object, fake)),
                        draft_id=draft_id,
                        event_type=GovernanceEventType.APPROVED,
                        from_state="in_review",
                        to_state="approved",
                        actor_id=uuid.uuid4(),
                        idempotency_key=f"approve:{draft_id}",
                    )
                )

        self.assertEqual(fake.added, [])
        fake.flush.assert_not_awaited()

    def test_append_assigns_the_next_sequence_after_state_validation(self) -> None:
        draft_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        current = SimpleNamespace(sequence=2, to_state="in_review")
        fake = _LedgerSession([None, current])

        with patch(
            "cygnus.governance.ledger.lock_draft_aggregate",
            AsyncMock(return_value=None),
        ):
            event = asyncio.run(
                append_draft_event(
                    cast(AsyncSession, cast(object, fake)),
                    draft_id=draft_id,
                    event_type=GovernanceEventType.APPROVED,
                    from_state="in_review",
                    to_state="approved",
                    actor_id=actor_id,
                    idempotency_key=f"approve:{draft_id}",
                    reason="evidence checked",
                )
            )

        self.assertEqual(event.sequence, 3)
        self.assertEqual(event.from_state, "in_review")
        self.assertEqual(event.to_state, "approved")
        self.assertEqual(fake.added, [event])
        fake.flush.assert_awaited_once()

    def test_record_draft_update_traces_content_version_and_action(self) -> None:
        draft_id = uuid.uuid4()
        content = "# Rebased billing policy\n\nUse the current threshold."
        draft = SimpleNamespace(
            id=draft_id,
            version=4,
            base_version=7,
            revision_round=2,
            content_md=content,
        )
        current = SimpleNamespace(sequence=3, to_state="in_review")
        fake = _LedgerSession([None, current])

        event = asyncio.run(
            record_draft_update(
                cast(AsyncSession, cast(object, fake)),
                cast(WikiPageDraft, draft),
                previous_draft_version=3,
                from_state="in_review",
                to_state="in_review",
                actor_id=uuid.uuid4(),
                action="branch_rebase",
                reason="branch conflict rebase",
                extra_payload={
                    "branch_id": str(uuid.uuid4()),
                    "base_page_version": 7,
                },
                lock=False,
            )
        )

        self.assertEqual(event.event_type, GovernanceEventType.DRAFT_UPDATED.value)
        self.assertEqual(event.sequence, 4)
        self.assertEqual(
            event.idempotency_key,
            f"wiki-draft:{draft_id}:draft_updated:4",
        )
        self.assertEqual(event.payload["action"], "branch_rebase")
        self.assertEqual(event.payload["previous_draft_version"], 3)
        self.assertEqual(event.payload["draft_version"], 4)
        self.assertEqual(event.payload["base_version"], 7)
        self.assertEqual(
            event.payload["content_sha256"],
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(event.reason, "branch conflict rebase")
        fake.flush.assert_awaited_once()

    def test_publish_command_normalizes_channels_and_fingerprints_request(self) -> None:
        draft_id = uuid.uuid4()
        approval_ref = uuid.uuid4()
        signal_id = uuid.uuid4()
        approval_digest = "a" * 64
        scope_digest = "b" * 64
        command = DurablePublishCommand(
            draft_id=draft_id,
            approval_ref=approval_ref,
            approval_digest=approval_digest,
            scope_digest=scope_digest,
            signal_id=signal_id,
            signal_freshness=" fresh ",
            command_id=" command-1 ",
            action_key=" publish ",
            target_channels=("agent-copilot", "agent-copilot", "internal-search"),
            expected_version=3,
            reason=" checked ",
        )
        equivalent = DurablePublishCommand(
            draft_id=draft_id,
            approval_ref=approval_ref,
            approval_digest=approval_digest,
            scope_digest=scope_digest,
            signal_id=signal_id,
            signal_freshness="fresh",
            command_id="command-1",
            action_key="publish",
            target_channels=("agent-copilot", "internal-search"),
            expected_version=3,
            reason="checked",
        )

        self.assertEqual(
            command.target_channels,
            ("agent-copilot", "internal-search"),
        )
        self.assertEqual(command.request_fingerprint, equivalent.request_fingerprint)
        self.assertEqual(command.expected_version, 3)
        self.assertEqual(command.signal_freshness, "fresh")

    def test_publish_command_rejects_missing_or_invalid_guards(self) -> None:
        draft_id = uuid.uuid4()
        approval_ref = uuid.uuid4()
        signal_id = uuid.uuid4()
        common: dict[str, Any] = {
            "draft_id": draft_id,
            "approval_ref": approval_ref,
            "approval_digest": "a" * 64,
            "scope_digest": "b" * 64,
            "signal_id": signal_id,
            "signal_freshness": "fresh",
            "command_id": "command-1",
            "action_key": "publish",
            "target_channels": ("agent-copilot",),
            "expected_version": 3,
        }
        for label, overrides in (
            ("approval_digest", {"approval_digest": "short"}),
            ("scope_digest", {"scope_digest": "x" * 64}),
            ("signal_freshness", {"signal_freshness": "expired"}),
            ("expected_version", {"expected_version": 0}),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    _ = DurablePublishCommand(**{**common, **overrides})

    def test_durable_route_requires_complete_command_envelope(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _ = asyncio.run(
                publish_apply(
                    PublishApplyRequest(
                        draft_id=uuid.uuid4(),
                        action_key="publish",
                    ),
                    request=cast(Request, SimpleNamespace(headers={})),
                    current_user=cast(
                        Employee,
                        cast(object, SimpleNamespace(id=uuid.uuid4())),
                    ),
                    db=cast(AsyncSession, cast(object, SimpleNamespace())),
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("approval_ref", str(raised.exception.detail))

    def test_admin_guard_rejects_non_admin_actor(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _ = asyncio.run(
                require_admin(
                    cast(Employee, cast(object, SimpleNamespace(role="employee")))
                )
            )

        self.assertEqual(raised.exception.status_code, 403)

    def test_durable_route_delegates_a_qualified_command(self) -> None:
        draft_id = uuid.uuid4()
        approval_ref = uuid.uuid4()
        actor_id = uuid.uuid4()
        expected = {
            "persisted": True,
            "rehearsal": False,
            "publication_record_id": str(uuid.uuid4()),
        }
        durable_apply = AsyncMock(return_value=expected)

        with patch(
            "cygnus.runtime.routers.governance.publish.apply_durable_publish",
            durable_apply,
        ):
            result = asyncio.run(
                publish_apply(
                    PublishApplyRequest(
                        draft_id=draft_id,
                        approval_ref=approval_ref,
                        approval_digest="a" * 64,
                        scope_digest="b" * 64,
                        signal_id=uuid.uuid4(),
                        signal_freshness="fresh",
                        command_id="publish-command-1",
                        action_key="publish",
                        target_channels=["agent-copilot"],
                        reason="approved evidence",
                        expected_version=3,
                    ),
                    request=cast(Request, SimpleNamespace(headers={})),
                    current_user=cast(
                        Employee,
                        cast(object, SimpleNamespace(id=actor_id)),
                    ),
                    db=cast(AsyncSession, cast(object, SimpleNamespace())),
                )
            )

        self.assertEqual(result, expected)
        durable_apply.assert_awaited_once()
        command = cast(
            DurablePublishCommand,
            durable_apply.await_args_list[0].kwargs["command"],
        )
        self.assertEqual(command.draft_id, draft_id)
        self.assertEqual(command.approval_ref, approval_ref)
        self.assertEqual(command.reason, "approved evidence")
        self.assertEqual(command.expected_version, 3)


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class GovernanceLedgerPostgresTests(unittest.TestCase):
    def test_publish_and_propagation_survive_new_sessions(self) -> None:
        asyncio.run(self._exercise_restart_durable_workflow())

    async def _exercise_restart_durable_workflow(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        actor_id = uuid.uuid4()
        source_id = uuid.uuid4()
        scope_id = uuid.uuid4()
        draft_id: uuid.UUID | None = None
        page_id: uuid.UUID | None = None
        signal_id: uuid.UUID | None = None
        publication_id: uuid.UUID | None = None
        unique = uuid.uuid4().hex
        source_updated_at = datetime.now(timezone.utc)

        async def persistence_counts(session: AsyncSession) -> tuple[int, int, int]:
            event_count = (
                await session.execute(
                    select(func.count()).select_from(GovernanceLedgerEvent)
                )
            ).scalar_one()
            publication_count = (
                await session.execute(
                    select(func.count()).select_from(GovernancePublication)
                )
            ).scalar_one()
            propagation_count = (
                await session.execute(
                    select(func.count()).select_from(GovernancePropagation)
                )
            ).scalar_one()
            return event_count, publication_count, propagation_count

        try:
            async with sessions() as session:
                actor = Employee(
                    id=actor_id,
                    name="Governance integration reviewer",
                    email=f"governance-{unique}@example.test",
                    role="admin",
                    global_role="admin",
                    is_active=True,
                )
                source = Source(
                    id=source_id,
                    title="Verified support evidence",
                    full_text="A verified internal support procedure.",
                    source_type="url",
                    language="en",
                    url=f"https://example.test/evidence/{unique}",
                    status="ready",
                    progress=100,
                    created_at=source_updated_at,
                    updated_at=source_updated_at,
                    freshness_state="fresh",
                    freshness_actor_id=actor_id,
                    freshness_reason="Attested fresh for governed publication.",
                    freshness_attested_at=source_updated_at + timedelta(seconds=1),
                    freshness_expires_at=source_updated_at + timedelta(days=1),
                )
                session.add_all((actor, source))
                await session.flush()
                draft = await create_wiki_draft(
                    session,
                    page_id=None,
                    author_id=actor.id,
                    content_md="# Refund policy\n\nUse verified evidence before refunding.",
                    note="ready for governed review",
                    draft_kind="create",
                    source_metadata={"source_ids": [str(source.id)]},
                    suggested_metadata={
                        "slug": f"governance-ledger-{unique}",
                        "title": "Governance ledger integration policy",
                        "page_type": "concept",
                        "knowledge_type_slugs": ["answer_card"],
                        "scope_type": "project",
                        "scope_id": str(scope_id),
                    },
                )
                page = await approve_wiki_draft(
                    session,
                    draft,
                    reviewer_id=actor.id,
                    reviewer_note="evidence and audience checked",
                )
                self.assertEqual(page.source_ids, [source.id])
                for channel in ("agent-copilot", "internal-search"):
                    _ = await create_audience_binding(
                        session,
                        command=AudienceBindingCreate(
                            page_id=page.id,
                            object_ref=governed_object_ref(page.id),
                            variant_ref="internal-governed",
                            channel=channel,
                            audience_filter=AudienceFilter(
                                visibility=Visibility.INTERNAL,
                            ),
                        ),
                        actor_id=actor.id,
                    )
                signal = GovernanceSignal(
                    signal_ref=f"governance-ledger-signal-{unique}",
                    signal_type="human_rewrite",
                    object_ref=governed_object_ref(page.id),
                    title="Governance ledger integration policy",
                    object_type="answer_card",
                    page_id=page.id,
                    source_id=source.id,
                    audience_binding_ref=None,
                    audience_filter={
                        "visibility": "internal",
                        "brands": [],
                        "product_lines": [],
                        "plans": [],
                        "regions": [],
                        "languages": [],
                        "product_versions": [],
                    },
                    affected_surfaces=["agent-copilot", "internal-search"],
                    trigger_signals=[],
                    evidence_source_type="support_document",
                    freshness="fresh",
                    summary="Verified support evidence triggers governed publication.",
                    reason="Evidence and audience checked by a reviewer.",
                    evidence_excerpt="A verified internal support procedure.",
                    status="active",
                    observed_at=datetime.now(timezone.utc),
                    resolved_at=None,
                    created_by_id=actor.id,
                    version=1,
                )
                session.add(signal)
                await session.flush()
                signal_id = signal.id
                index_page = await wiki_service.regenerate_index(
                    session,
                    scope_type="project",
                    scope_id=scope_id,
                )
                log_page = await wiki_service.append_log(
                    session,
                    "published governed integration policy",
                    scope_type="project",
                    scope_id=scope_id,
                )
                self.assertEqual(index_page.page_type, "index")
                self.assertEqual(log_page.page_type, "log")
                await session.commit()
                draft_id = draft.id
                page_id = page.id

            async with sessions() as session:
                events = await list_draft_events(session, draft_id)
                approval = next(
                    event
                    for event in events
                    if event.event_type == GovernanceEventType.APPROVED.value
                )
                self.assertIn("approval_digest", approval.payload)
                loaded_draft = await session.get(WikiPageDraft, draft_id)
                loaded_page = await session.get(WikiPage, page_id)
                loaded_signal = await session.get(GovernanceSignal, signal_id)
                self.assertIsNotNone(loaded_draft)
                self.assertIsNotNone(loaded_page)
                self.assertIsNotNone(loaded_signal)
                if loaded_draft is None or loaded_page is None or loaded_signal is None:
                    raise AssertionError("guarded publish fixtures unexpectedly absent")
                canonical_digest = approval_digest(
                    draft=loaded_draft,
                    page=loaded_page,
                    final_content=loaded_page.content_md,
                    reviewer_id=loaded_draft.reviewed_by_id,
                    reviewed_at=loaded_draft.reviewed_at,
                    reviewer_note=loaded_draft.reviewer_note,
                )
                self.assertEqual(
                    canonical_digest,
                    approval.payload["approval_digest"],
                )
                envelope = await durable_publish_command_for_signal(
                    session,
                    signal=loaded_signal,
                    action_key="publish",
                )
                self.assertIsNotNone(envelope)
                if envelope is None:
                    raise AssertionError("durable publish command unexpectedly absent")
                self.assertEqual(envelope["approval_digest"], canonical_digest)
                command = DurablePublishCommand(
                    draft_id=uuid.UUID(cast(str, envelope["draft_id"])),
                    approval_ref=uuid.UUID(cast(str, envelope["approval_ref"])),
                    approval_digest=cast(str, envelope["approval_digest"]),
                    scope_digest=cast(str, envelope["scope_digest"]),
                    signal_id=uuid.UUID(cast(str, envelope["signal_id"])),
                    signal_freshness=cast(str, envelope["signal_freshness"]),
                    command_id=f"publish-{unique}",
                    action_key=cast(str, envelope["action_key"]),
                    target_channels=tuple(cast(list[str], envelope["target_channels"])),
                    expected_version=cast(int, envelope["expected_version"]),
                    reason=cast(str, envelope["reason"]),
                )
                result = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=actor_id,
                )
                self.assertTrue(result["persisted"])
                self.assertFalse(result["rehearsal"])
                self.assertFalse(result["replayed"])
                self.assertEqual(result["approval_digest"], command.approval_digest)
                self.assertEqual(result["scope_digest"], command.scope_digest)
                propagation = cast(dict[str, object], result["propagation"])
                summary = cast(dict[str, int], propagation["summary"])
                self.assertEqual(summary["pending"], 2)
                publication_id = uuid.UUID(cast(str, result["publication_record_id"]))
                await session.commit()

            async with sessions() as session:
                durable_projection = await get_durable_publish_projection(
                    governed_object_ref(page_id),
                    session,
                )
                self.assertIsNotNone(durable_projection)
                if durable_projection is None:
                    raise AssertionError("durable projection unexpectedly absent")
                self.assertTrue(durable_projection["persisted"])
                self.assertEqual(
                    durable_projection["publication_record_id"],
                    str(publication_id),
                )
                replay = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=actor_id,
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(
                    replay["publication_record_id"],
                    str(publication_id),
                )
                propagations = await list_publication_propagations(
                    session,
                    publication_id,
                )
                target = next(
                    item for item in propagations if item.surface_id == "agent-copilot"
                )
                target_id = target.id
                propagation_ids = tuple(item.id for item in propagations)
                forbidden_update = PropagationUpdateCommand(
                    publication_id=publication_id,
                    surface_id=target.surface_id,
                    status=PropagationStatus.SYNCED,
                    expected_version=target.version,
                    command_id=f"propagation-{unique}",
                    reason="downstream acknowledged version",
                    follow_up_commands=(),
                )
                # Manual mutation may never set synced; only the signed ack path can.
                with self.assertRaises(DurablePublishDenied):
                    _ = await update_propagation(
                        session,
                        command=forbidden_update,
                        actor_id=actor_id,
                    )
                await session.rollback()

                deliveries = await list_propagation_deliveries(session, propagation_ids)
                delivery = next(
                    item for item in deliveries if item.propagation_id == target_id
                )
                ack_payload = {
                    "publication_id": str(delivery.publication_id),
                    "surface_id": delivery.surface_id,
                    "version": delivery.expected_page_version,
                    "digest": delivery.desired_digest,
                    "receipt_ref": "ledger-test-receipt",
                }
                ack_body = canonical_json(ack_payload)
                ack_signature = f"sha256={sign_body(ack_body, _LEDGER_ACK_SECRET)}"
                updated = await acknowledge_propagation_delivery(
                    session,
                    delivery_id=delivery.id,
                    ack_body=ack_body,
                    signature=ack_signature,
                    secret=_LEDGER_ACK_SECRET,
                )
                self.assertEqual(updated["status"], "synced")
                self.assertFalse(updated["replayed"])
                self.assertEqual(
                    updated["acknowledged_digest"], delivery.desired_digest
                )
                await session.commit()

            async with sessions() as session:
                propagations = await list_publication_propagations(
                    session,
                    publication_id,
                )
                delivery = next(
                    item
                    for item in await list_propagation_deliveries(
                        session, tuple(item.id for item in propagations)
                    )
                    if item.surface_id == "agent-copilot"
                )
                propagation_replay = await acknowledge_propagation_delivery(
                    session,
                    delivery_id=delivery.id,
                    ack_body=ack_body,
                    signature=ack_signature,
                    secret=_LEDGER_ACK_SECRET,
                )
                self.assertTrue(propagation_replay["replayed"])
                self.assertEqual(
                    propagation_replay["delivery_id"], updated["delivery_id"]
                )
                publication = await get_publication(session, publication_id)
                self.assertIsNotNone(publication)
                events = await list_draft_events(session, draft_id)
                self.assertEqual(
                    [event.sequence for event in events],
                    list(range(1, len(events) + 1)),
                )
                self.assertEqual(
                    [event.event_type for event in events],
                    [
                        "proposal_created",
                        "review_requested",
                        "approved",
                        "published",
                        "propagation_updated",
                    ],
                )

                conflicting = DurablePublishCommand(
                    draft_id=draft_id,
                    approval_ref=command.approval_ref,
                    approval_digest=command.approval_digest,
                    scope_digest=command.scope_digest,
                    signal_id=command.signal_id,
                    signal_freshness=command.signal_freshness,
                    command_id=command.command_id,
                    action_key="publish",
                    target_channels=("agent-copilot",),
                    expected_version=command.expected_version,
                    reason="different request",
                )
                with self.assertRaises(DurablePublishConflict):
                    _ = await apply_durable_publish(
                        session,
                        command=conflicting,
                        actor_id=actor_id,
                    )
                await session.rollback()

            async with sessions() as session:
                persisted_draft = await session.get(WikiPageDraft, draft_id)
                persisted_page = await session.get(WikiPage, page_id)
                persisted_source = await session.get(Source, source_id)
                self.assertIsNotNone(persisted_draft)
                self.assertIsNotNone(persisted_page)
                self.assertIsNotNone(persisted_source)
                if (
                    persisted_draft is None
                    or persisted_page is None
                    or persisted_source is None
                ):
                    raise AssertionError(
                        "durable workflow fixtures unexpectedly absent"
                    )

                baseline_counts = await persistence_counts(session)
                baseline_page_status = persisted_page.status

                async def assert_rejected(
                    *,
                    approval_ref: uuid.UUID = command.approval_ref,
                    action_key: str = "republish",
                    suffix: str,
                ) -> None:
                    rejected = DurablePublishCommand(
                        draft_id=draft_id,
                        approval_ref=approval_ref,
                        approval_digest=command.approval_digest,
                        scope_digest=command.scope_digest,
                        signal_id=command.signal_id,
                        signal_freshness=command.signal_freshness,
                        command_id=f"rejected-{suffix}-{unique}",
                        action_key=action_key,
                        target_channels=("agent-copilot",),
                        expected_version=command.expected_version,
                        reason=f"exercise {suffix} rejection",
                    )
                    # Edit/source/binding/freshness/action drift rejects
                    # atomically as a conflict; structural invalidity denies.
                    with self.assertRaises(
                        (DurablePublishConflict, DurablePublishDenied)
                    ):
                        _ = await apply_durable_publish(
                            session,
                            command=rejected,
                            actor_id=actor_id,
                        )
                    self.assertEqual(
                        await persistence_counts(session),
                        baseline_counts,
                    )
                    self.assertEqual(persisted_page.status, baseline_page_status)

                await assert_rejected(
                    approval_ref=uuid.uuid4(),
                    suffix="foreign-approval",
                )

                persisted_draft.status = "pending"
                await session.flush()
                await assert_rejected(suffix="unapproved-draft")
                persisted_draft.status = "approved"
                await session.flush()

                original_types = list(persisted_page.knowledge_type_slugs or ())
                persisted_page.knowledge_type_slugs = []
                await session.flush()
                await assert_rejected(suffix="untyped-page")
                persisted_page.knowledge_type_slugs = original_types
                await session.flush()

                original_source_ids = list(persisted_page.source_ids or ())
                persisted_page.source_ids = []
                await session.flush()
                await assert_rejected(suffix="missing-evidence")
                persisted_page.source_ids = original_source_ids
                await session.flush()

                persisted_source.status = "error"
                await session.flush()
                await assert_rejected(suffix="non-ready-evidence")
                persisted_source.status = "ready"
                await session.flush()
                active_bindings = tuple(
                    (
                        await session.execute(
                            select(GovernanceAudienceBinding).where(
                                GovernanceAudienceBinding.page_id == persisted_page.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                active_bindings[0].lifecycle_state = "held"
                await session.flush()
                await assert_rejected(suffix="missing-active-channel-binding")
                active_bindings[0].lifecycle_state = "active"
                await session.flush()

                await assert_rejected(
                    action_key="unsupported-action",
                    suffix="unsupported-action",
                )
                await session.rollback()
        finally:
            if draft_id is not None:
                async with sessions() as cleanup:
                    if publication_id is not None:
                        _ = await cleanup.execute(
                            delete(GovernancePropagationDelivery).where(
                                GovernancePropagationDelivery.publication_id
                                == publication_id
                            )
                        )
                        _ = await cleanup.execute(
                            delete(GovernancePropagation).where(
                                GovernancePropagation.publication_id == publication_id
                            )
                        )
                        _ = await cleanup.execute(
                            delete(GovernancePublication).where(
                                GovernancePublication.id == publication_id
                            )
                        )
                    if page_id is not None:
                        _ = await cleanup.execute(
                            delete(GovernanceAudienceBinding).where(
                                GovernanceAudienceBinding.page_id == page_id
                            )
                        )
                    _ = await cleanup.execute(
                        delete(GovernanceLedgerEvent).where(
                            GovernanceLedgerEvent.draft_id == draft_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(WikiPageRevision).where(
                            WikiPageRevision.draft_id == draft_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(WikiPageDraft).where(WikiPageDraft.id == draft_id)
                    )
                    if page_id is not None:
                        _ = await cleanup.execute(
                            delete(WikiPageRevision).where(
                                WikiPageRevision.page_id == page_id
                            )
                        )
                        _ = await cleanup.execute(
                            delete(WikiPage).where(
                                WikiPage.scope_type == "project",
                                WikiPage.scope_id == scope_id,
                            )
                        )
                    if signal_id is not None:
                        _ = await cleanup.execute(
                            delete(GovernanceSignal).where(
                                GovernanceSignal.id == signal_id
                            )
                        )
                    _ = await cleanup.execute(
                        delete(Source).where(Source.id == source_id)
                    )
                    _ = await cleanup.execute(
                        delete(AuditLog).where(AuditLog.principal_id == actor_id)
                    )
                    _ = await cleanup.execute(
                        delete(Employee).where(Employee.id == actor_id)
                    )
                    await cleanup.commit()
            await engine.dispose()


if __name__ == "__main__":
    _ = unittest.main()
