from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import cast
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType, governed_object_ref
from cygnus.evidence.records import FreshnessState
from cygnus.governance.approval_guards import approval_digest
from cygnus.governance.audience_bindings import (
    AudienceBindingCreate,
    create_audience_binding,
)
from cygnus.governance.ledger import GovernanceEventType, list_draft_events
from cygnus.governance.signals import (
    GovernanceSignalConflict,
    GovernanceSignalInput,
    create_governance_signal,
)
from cygnus.governance.ticket_draft_promotions import (
    TicketDraftPromotionCommand,
    promote_ticket_cluster_to_draft,
)
from cygnus.governance.ticket_import import (
    TicketExportFormat,
    import_resolved_ticket_export,
)
from cygnus.governance.ticket_pilot import (
    TicketPilotFunnelQuery,
    get_ticket_pilot_funnel,
)
from cygnus.publish.durable import (
    DurablePublishCommand,
    apply_durable_publish,
    durable_publish_command_for_signal,
)
from cygnus.review.contributions import approve_wiki_draft, submit_wiki_draft
from cygnus.review.intake import PressureSignalType
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
    GovernanceReviewAssignment,
    GovernanceSignal,
    GovernanceTicketDraftPromotion,
    Source,
    WikiPage,
    WikiPageDraft,
    WikiPageRevision,
)


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")
_FIXTURE = Path(__file__).parent / "fixtures" / "resolved_ticket_export.csv"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"expected mapping, got {type(value).__name__}")
    return cast(Mapping[str, object], value)


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class TicketSourcePublicationPostgresTests(unittest.TestCase):
    def test_ticket_import_reaches_durable_publish_with_source_truth(self) -> None:
        asyncio.run(self._exercise_ticket_source_publication())

    async def _exercise_ticket_source_publication(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        actor_id = uuid.uuid4()
        source_id = uuid.uuid4()
        other_source_id = uuid.uuid4()
        source_ref = f"cyg125/sanitized/{unique}"
        signal_id: uuid.UUID | None = None
        draft_id: uuid.UUID | None = None
        page_id: uuid.UUID | None = None
        publication_signal_id: uuid.UUID | None = None
        publication_id: uuid.UUID | None = None

        try:
            async with sessions() as session:
                actor = Employee(
                    id=actor_id,
                    name="CYG-125 pilot reviewer",
                    email=f"cyg125-{unique}@example.test",
                    role="admin",
                    global_role="admin",
                    is_active=True,
                )
                source = Source(
                    id=source_id,
                    title="CYG-125 sanitized resolved-ticket snapshot",
                    full_text=None,
                    source_type="file",
                    language="en",
                    file_name=f"resolved-tickets-{unique}.csv",
                    file_size=len(_FIXTURE.read_bytes()),
                    status="ready",
                    progress=100,
                    contributed_by_employee_id=actor_id,
                )
                other_source = Source(
                    id=other_source_id,
                    title="CYG-125 different sanitized snapshot",
                    full_text=None,
                    source_type="file",
                    language="en",
                    file_name=f"other-resolved-tickets-{unique}.csv",
                    file_size=len(_FIXTURE.read_bytes()),
                    status="ready",
                    progress=100,
                    contributed_by_employee_id=actor_id,
                )
                session.add_all((actor, source, other_source))
                await session.flush()
                source_attested_at = source.updated_at or datetime.now(timezone.utc)
                source.freshness_state = FreshnessState.FRESH.value
                source.freshness_actor_id = actor_id
                source.freshness_reason = (
                    "Attested fresh for the governed pilot publication."
                )
                source.freshness_attested_at = source_attested_at
                source.freshness_expires_at = source_attested_at + timedelta(days=1)
                other_attested_at = other_source.updated_at or datetime.now(
                    timezone.utc
                )
                other_source.freshness_state = FreshnessState.FRESH.value
                other_source.freshness_actor_id = actor_id
                other_source.freshness_reason = (
                    "Attested fresh for the governed pilot publication."
                )
                other_source.freshness_attested_at = other_attested_at
                other_source.freshness_expires_at = other_attested_at + timedelta(
                    days=1
                )
                await session.flush()

                imported = await import_resolved_ticket_export(
                    session,
                    _FIXTURE.read_bytes(),
                    export_format=TicketExportFormat.CSV,
                    source_ref=source_ref,
                    source_id=source_id,
                    minimum_cluster_size=3,
                    created_by_id=actor_id,
                )
                self.assertEqual(len(imported.governance_signals), 1)
                signal = imported.governance_signals[0]
                signal_id = signal.id
                self.assertEqual(signal.source_id, source_id)
                self.assertEqual(imported.to_dict()["source_id"], str(source_id))

                replay = await import_resolved_ticket_export(
                    session,
                    _FIXTURE.read_bytes(),
                    export_format=TicketExportFormat.CSV,
                    source_ref=source_ref,
                    source_id=source_id,
                    minimum_cluster_size=3,
                    created_by_id=actor_id,
                )
                self.assertEqual(replay.governance_signals[0].id, signal.id)

                with self.assertRaises(GovernanceSignalConflict):
                    _ = await import_resolved_ticket_export(
                        session,
                        _FIXTURE.read_bytes(),
                        export_format=TicketExportFormat.CSV,
                        source_ref=source_ref,
                        source_id=other_source_id,
                        minimum_cluster_size=3,
                        created_by_id=actor_id,
                    )

                assignment = (
                    await session.execute(
                        select(GovernanceReviewAssignment).where(
                            GovernanceReviewAssignment.signal_id == signal.id
                        )
                    )
                ).scalar_one()
                promoted = await promote_ticket_cluster_to_draft(
                    session,
                    signal_ref=signal.signal_ref,
                    command=TicketDraftPromotionCommand(
                        command_id=f"cyg125-promote:{unique}",
                        expected_assignment_version=assignment.version,
                        reason="Promote the source-grounded ticket cluster.",
                    ),
                    actor_id=actor_id,
                )
                if promoted is None:
                    raise AssertionError("ticket cluster unexpectedly disappeared")
                draft = promoted.draft
                draft_id = draft.id
                draft_metadata = _mapping(cast(object, draft.source_metadata))
                self.assertEqual(draft_metadata["source_ids"], [str(source_id)])

                with patch(
                    "cygnus.review.contributions.notify_submitted",
                    AsyncMock(return_value=None),
                ):
                    _ = await submit_wiki_draft(
                        session,
                        draft,
                        actor,
                        expected_version=draft.version,
                        review_type="standard",
                        notes="Source and structured ticket evidence verified.",
                    )
                page = await approve_wiki_draft(
                    session,
                    draft,
                    reviewer_id=actor_id,
                    reviewer_note="Approved against ready sanitized evidence.",
                )
                page_id = page.id
                self.assertEqual(page.source_ids, [source_id])

                object_ref = governed_object_ref(page.id)
                audience_filter = AudienceFilter(
                    visibility=Visibility.INTERNAL,
                    product_lines=("workspace",),
                    plans=("test-plan",),
                    regions=("test-region",),
                    languages=("en",),
                    product_versions=("fixture-1",),
                )
                binding, binding_replayed = await create_audience_binding(
                    session,
                    command=AudienceBindingCreate(
                        page_id=page.id,
                        object_ref=object_ref,
                        variant_ref="internal-ticket-pilot",
                        channel="internal_copilot",
                        audience_filter=audience_filter,
                    ),
                    actor_id=actor_id,
                )
                self.assertFalse(binding_replayed)
                self.assertEqual(binding.object_ref, object_ref)
                publication_signal = await create_governance_signal(
                    session,
                    GovernanceSignalInput(
                        signal_ref=f"ticket-publication:{unique}",
                        signal_type=PressureSignalType.TICKET_CLUSTER,
                        object_ref=object_ref,
                        title="Approved source-grounded ticket guidance",
                        object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
                        page_id=page.id,
                        source_id=source_id,
                        audience_filter=audience_filter,
                        affected_surfaces=("internal_copilot",),
                        trigger_signals=("ticket_cluster", "reviewer_approved"),
                        freshness=FreshnessState.FRESH,
                        summary=(
                            "Reviewed ticket evidence supports the approved guidance."
                        ),
                        reason=("Publish the approved source-grounded pilot object."),
                        evidence_excerpt=(
                            "Three sanitized resolved tickets repeat the same flow."
                        ),
                    ),
                    created_by_id=actor_id,
                )
                publication_signal_id = publication_signal.id
                self.assertEqual(publication_signal.object_ref, object_ref)
                events = await list_draft_events(session, draft.id)
                approval = next(
                    event
                    for event in events
                    if event.event_type == GovernanceEventType.APPROVED.value
                )
                self.assertIn("approval_digest", approval.payload)
                refreshed_signal = await session.get(
                    GovernanceSignal, publication_signal_id
                )
                canonical_digest = approval_digest(
                    draft=draft,
                    page=page,
                    final_content=page.content_md,
                    reviewer_id=draft.reviewed_by_id,
                    reviewed_at=draft.reviewed_at,
                    reviewer_note=draft.reviewer_note,
                )
                self.assertEqual(
                    canonical_digest,
                    approval.payload["approval_digest"],
                )
                if refreshed_signal is None:
                    raise AssertionError("pilot signal fixture unexpectedly absent")
                envelope = await durable_publish_command_for_signal(
                    session,
                    signal=refreshed_signal,
                    action_key="publish",
                )
                self.assertIsNotNone(envelope)
                if envelope is None:
                    raise AssertionError("pilot publish command unexpectedly absent")
                self.assertEqual(envelope["approval_digest"], canonical_digest)
                publish_command = DurablePublishCommand(
                    draft_id=uuid.UUID(cast(str, envelope["draft_id"])),
                    approval_ref=uuid.UUID(cast(str, envelope["approval_ref"])),
                    approval_digest=cast(str, envelope["approval_digest"]),
                    scope_digest=cast(str, envelope["scope_digest"]),
                    signal_id=uuid.UUID(cast(str, envelope["signal_id"])),
                    signal_freshness=cast(str, envelope["signal_freshness"]),
                    command_id=f"cyg125-publish:{unique}",
                    action_key=cast(str, envelope["action_key"]),
                    target_channels=tuple(cast(list[str], envelope["target_channels"])),
                    expected_version=cast(int, envelope["expected_version"]),
                    reason=cast(str, envelope["reason"]),
                )
                publish_result = await apply_durable_publish(
                    session,
                    command=publish_command,
                    actor_id=actor_id,
                )
                self.assertTrue(publish_result["persisted"])
                self.assertFalse(publish_result["rehearsal"])
                publication_id = uuid.UUID(
                    cast(str, publish_result["publication_record_id"])
                )
                await session.commit()

            async with sessions() as session:
                persisted_signal = await session.get(GovernanceSignal, signal_id)
                persisted_publication_signal = await session.get(
                    GovernanceSignal, publication_signal_id
                )
                persisted_draft = await session.get(WikiPageDraft, draft_id)
                persisted_page = await session.get(WikiPage, page_id)
                persisted_publication = await session.get(
                    GovernancePublication, publication_id
                )
                self.assertIsNotNone(persisted_signal)
                self.assertIsNotNone(persisted_draft)
                self.assertIsNotNone(persisted_page)
                self.assertIsNotNone(persisted_publication)
                self.assertIsNotNone(persisted_publication_signal)
                if (
                    persisted_signal is None
                    or persisted_publication_signal is None
                    or persisted_draft is None
                    or persisted_page is None
                    or persisted_publication is None
                ):
                    raise AssertionError(
                        "CYG-125 durable lifecycle truth is incomplete"
                    )
                self.assertEqual(persisted_signal.source_id, source_id)
                self.assertEqual(persisted_page.source_ids, [source_id])
                self.assertEqual(persisted_publication_signal.page_id, page_id)
                self.assertEqual(
                    persisted_publication_signal.object_ref,
                    governed_object_ref(persisted_page.id),
                )
                self.assertEqual(
                    persisted_publication.object_ref,
                    governed_object_ref(persisted_page.id),
                )

                replayed_publish = await apply_durable_publish(
                    session,
                    command=publish_command,
                    actor_id=actor_id,
                )
                self.assertTrue(replayed_publish["replayed"])
                self.assertEqual(
                    replayed_publish["publication_record_id"],
                    str(publication_id),
                )

                funnel = await get_ticket_pilot_funnel(
                    session,
                    query=TicketPilotFunnelQuery(source_ref=source_ref),
                )
                funnel_payload = funnel.to_dict()
                self.assertEqual(funnel_payload["matched_signal_count"], 1)
                self.assertEqual(funnel_payload["excluded_signal_count"], 0)
                summary = _mapping(funnel_payload["summary"])
                self.assertEqual(summary["eligible_signal_count"], 1)
                self.assertEqual(summary["promoted_draft_count"], 1)
                self.assertEqual(summary["review_submitted_draft_count"], 1)
                self.assertEqual(summary["approved_draft_count"], 1)
                self.assertEqual(summary["published_draft_count"], 1)
        finally:
            try:
                await self._cleanup(
                    sessions,
                    actor_id=actor_id,
                    source_ids=(source_id, other_source_id),
                    signal_id=signal_id,
                    publication_signal_id=publication_signal_id,
                    draft_id=draft_id,
                    page_id=page_id,
                    publication_id=publication_id,
                )
            finally:
                await engine.dispose()

    async def _cleanup(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        actor_id: uuid.UUID,
        source_ids: tuple[uuid.UUID, ...],
        signal_id: uuid.UUID | None,
        publication_signal_id: uuid.UUID | None,
        draft_id: uuid.UUID | None,
        page_id: uuid.UUID | None,
        publication_id: uuid.UUID | None,
    ) -> None:
        async with sessions() as session:
            if publication_id is not None:
                _ = await session.execute(
                    delete(GovernancePropagationDelivery).where(
                        GovernancePropagationDelivery.publication_id == publication_id
                    )
                )
                _ = await session.execute(
                    delete(GovernancePropagation).where(
                        GovernancePropagation.publication_id == publication_id
                    )
                )
                _ = await session.execute(
                    delete(GovernancePublication).where(
                        GovernancePublication.id == publication_id
                    )
                )
            if page_id is not None:
                _ = await session.execute(
                    delete(GovernanceAudienceBinding).where(
                        GovernanceAudienceBinding.page_id == page_id
                    )
                )
            if signal_id is not None:
                _ = await session.execute(
                    delete(GovernanceTicketDraftPromotion).where(
                        GovernanceTicketDraftPromotion.signal_id == signal_id
                    )
                )
            if draft_id is not None:
                _ = await session.execute(
                    delete(GovernanceLedgerEvent).where(
                        GovernanceLedgerEvent.draft_id == draft_id
                    )
                )
                _ = await session.execute(
                    delete(WikiPageRevision).where(
                        WikiPageRevision.draft_id == draft_id
                    )
                )
                _ = await session.execute(
                    delete(AuditLog).where(AuditLog.resource_id == str(draft_id))
                )
                _ = await session.execute(
                    delete(WikiPageDraft).where(WikiPageDraft.id == draft_id)
                )
            governance_signal_ids = tuple(
                item for item in (signal_id, publication_signal_id) if item is not None
            )
            if governance_signal_ids:
                _ = await session.execute(
                    delete(GovernanceReviewAssignment).where(
                        GovernanceReviewAssignment.signal_id.in_(governance_signal_ids)
                    )
                )
                _ = await session.execute(
                    delete(GovernanceSignal).where(
                        GovernanceSignal.id.in_(governance_signal_ids)
                    )
                )
            if page_id is not None:
                _ = await session.execute(
                    delete(WikiPageRevision).where(WikiPageRevision.page_id == page_id)
                )
                _ = await session.execute(
                    delete(WikiPage).where(WikiPage.id == page_id)
                )
            _ = await session.execute(delete(Source).where(Source.id.in_(source_ids)))
            _ = await session.execute(delete(Employee).where(Employee.id == actor_id))
            await session.commit()


if __name__ == "__main__":
    _ = unittest.main()
