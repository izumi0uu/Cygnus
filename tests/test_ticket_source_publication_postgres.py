from __future__ import annotations

import asyncio
from collections.abc import Mapping
import os
from pathlib import Path
from typing import cast
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.governance.audience_bindings import (
    AudienceBindingCreate,
    create_audience_binding,
)
from cygnus.governance.ledger import GovernanceEventType, list_draft_events
from cygnus.governance.signals import GovernanceSignalConflict
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
from cygnus.publish.durable import DurablePublishCommand, apply_durable_publish
from cygnus.review.contributions import approve_wiki_draft, submit_wiki_draft
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePropagation,
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
                    file_name=f"other-resolved-tickets-{unique}.csv",
                    file_size=len(_FIXTURE.read_bytes()),
                    status="ready",
                    progress=100,
                    contributed_by_employee_id=actor_id,
                )
                session.add_all((actor, source, other_source))
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

                _ = await create_audience_binding(
                    session,
                    command=AudienceBindingCreate(
                        page_id=page.id,
                        object_ref=f"ko-{page.slug}",
                        variant_ref="internal-ticket-pilot",
                        channel="internal_copilot",
                        audience_filter=AudienceFilter(
                            visibility=Visibility.INTERNAL,
                            product_lines=("workspace",),
                            plans=("test-plan",),
                            regions=("test-region",),
                            languages=("en",),
                            product_versions=("fixture-1",),
                        ),
                    ),
                    actor_id=actor_id,
                )
                events = await list_draft_events(session, draft.id)
                approval = next(
                    event
                    for event in events
                    if event.event_type == GovernanceEventType.APPROVED.value
                )
                publish_command = DurablePublishCommand(
                    draft_id=draft.id,
                    approval_ref=approval.id,
                    command_id=f"cyg125-publish:{unique}",
                    action_key="publish",
                    target_channels=("internal_copilot",),
                    expected_version=page.version,
                    reason="Publish the approved source-grounded pilot object.",
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
                persisted_draft = await session.get(WikiPageDraft, draft_id)
                persisted_page = await session.get(WikiPage, page_id)
                persisted_publication = await session.get(
                    GovernancePublication, publication_id
                )
                self.assertIsNotNone(persisted_signal)
                self.assertIsNotNone(persisted_draft)
                self.assertIsNotNone(persisted_page)
                self.assertIsNotNone(persisted_publication)
                if (
                    persisted_signal is None
                    or persisted_draft is None
                    or persisted_page is None
                    or persisted_publication is None
                ):
                    raise AssertionError(
                        "CYG-125 durable lifecycle truth is incomplete"
                    )
                self.assertEqual(persisted_signal.source_id, source_id)
                self.assertEqual(persisted_page.source_ids, [source_id])

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
        draft_id: uuid.UUID | None,
        page_id: uuid.UUID | None,
        publication_id: uuid.UUID | None,
    ) -> None:
        async with sessions() as session:
            if publication_id is not None:
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
            if signal_id is not None:
                _ = await session.execute(
                    delete(GovernanceReviewAssignment).where(
                        GovernanceReviewAssignment.signal_id == signal_id
                    )
                )
                _ = await session.execute(
                    delete(GovernanceSignal).where(GovernanceSignal.id == signal_id)
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
