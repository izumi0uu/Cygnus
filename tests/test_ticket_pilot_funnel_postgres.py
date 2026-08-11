from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import os
from typing import cast
import unittest
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cygnus.governance.ledger import GovernanceEventType
from cygnus.governance.ticket_pilot import (
    TicketPilotFunnelQuery,
    get_ticket_pilot_funnel,
)
from cygnus.runtime.database.models import (
    Employee,
    GovernanceLedgerEvent,
    GovernancePublication,
    GovernanceSignal,
    GovernanceTicketDraftPromotion,
    WikiPage,
    WikiPageDraft,
)


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"expected mapping, got {type(value).__name__}")
    return cast(Mapping[str, object], value)


def _signal(
    *,
    signal_id: uuid.UUID,
    actor_id: uuid.UUID,
    suffix: str,
    source_ref: str,
    import_digest: str,
    created_at: datetime,
    status: str = "active",
    second_source_ref: str | None = None,
) -> GovernanceSignal:
    source_refs = (source_ref, second_source_ref or source_ref)
    return GovernanceSignal(
        id=signal_id,
        signal_ref=f"ticket-import:{suffix}",
        signal_type="ticket_cluster",
        object_ref=f"ticket-cluster:{suffix}",
        title=f"CYG-124 ticket cluster {suffix}",
        object_type="troubleshooting_flow",
        page_id=None,
        source_id=None,
        audience_binding_ref=None,
        audience_filter={
            "visibility": "internal",
            "brands": [],
            "product_lines": ["support"],
            "plans": [],
            "regions": [],
            "languages": ["en"],
            "product_versions": [],
        },
        affected_surfaces=["copilot", "review_queue"],
        trigger_signals=[
            "ticket_pressure",
            "ticket_cluster",
            f"ticket_import:{import_digest}",
        ],
        evidence_source_type="resolved_ticket",
        freshness="unknown",
        summary="Repeated sanitized tickets show a reusable troubleshooting gap.",
        reason="member_count=2 met minimum_cluster_size=2.",
        evidence_excerpt="Sanitized recurring support pattern.",
        evidence_refs=[
            {
                "evidence_id": f"ev-ticket:{suffix}:1",
                "source_ref": f"{source_refs[0]}#ticket=1",
                "excerpt": "Sanitized ticket one.",
                "observed_at": created_at.isoformat(),
            },
            {
                "evidence_id": f"ev-ticket:{suffix}:2",
                "source_ref": f"{source_refs[1]}#ticket=2",
                "excerpt": "Sanitized ticket two.",
                "observed_at": created_at.isoformat(),
            },
        ],
        status=status,
        observed_at=created_at - timedelta(hours=1),
        resolved_at=created_at + timedelta(hours=1) if status == "resolved" else None,
        created_by_id=actor_id,
        created_at=created_at,
        updated_at=created_at,
        version=2 if status == "resolved" else 1,
    )


def _draft(
    *,
    draft_id: uuid.UUID,
    actor_id: uuid.UUID,
    status: str,
    created_at: datetime,
    page_id: uuid.UUID | None = None,
) -> WikiPageDraft:
    return WikiPageDraft(
        id=draft_id,
        page_id=page_id,
        draft_kind="create",
        suggested_metadata={
            "title": f"CYG-124 draft {draft_id}",
            "slug": f"cyg-124-{draft_id}",
        },
        author_id=actor_id,
        content_md="# CYG-124 pilot draft\n\nGoverned content.",
        note="Reviewer-created ticket pilot draft.",
        base_version=None,
        version=1,
        revision_round=0,
        last_returned_note=None,
        ai_check_status="passed",
        ai_check_results=None,
        ai_checked_at=created_at,
        status=status,
        source="web_ui",
        source_metadata={"origin": "ticket_cluster_promotion"},
        branch_id=None,
        reviewed_by_id=actor_id if status == "approved" else None,
        reviewed_at=created_at + timedelta(hours=2) if status == "approved" else None,
        reviewer_note="Approved for the pilot." if status == "approved" else None,
        created_at=created_at,
        updated_at=created_at,
    )


def _promotion(
    *,
    promotion_id: uuid.UUID,
    signal: GovernanceSignal,
    draft: WikiPageDraft,
    actor_id: uuid.UUID,
    created_at: datetime,
) -> GovernanceTicketDraftPromotion:
    return GovernanceTicketDraftPromotion(
        id=promotion_id,
        signal_id=signal.id,
        draft_id=draft.id,
        command_id=f"cyg124-promote:{promotion_id}",
        request_fingerprint=uuid.uuid4().hex * 2,
        source_signal_version=1,
        expected_assignment_version=1,
        actor_id=actor_id,
        reason="Reviewer promoted this cluster for the pilot.",
        created_at=created_at,
    )


def _event(
    *,
    event_id: uuid.UUID,
    draft_id: uuid.UUID,
    actor_id: uuid.UUID,
    sequence: int,
    event_type: GovernanceEventType,
    from_state: str | None,
    to_state: str,
    occurred_at: datetime,
) -> GovernanceLedgerEvent:
    return GovernanceLedgerEvent(
        id=event_id,
        draft_id=draft_id,
        sequence=sequence,
        event_type=event_type.value,
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        idempotency_key=f"cyg124:{event_id}",
        reason="CYG-124 integration lifecycle event.",
        payload={},
        occurred_at=occurred_at,
        recorded_at=occurred_at,
    )


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class TicketPilotFunnelPostgresTests(unittest.TestCase):
    def test_source_scoped_funnel_survives_restart(self) -> None:
        asyncio.run(self._exercise_source_scoped_funnel())

    async def _exercise_source_scoped_funnel(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        now = datetime.now(timezone.utc).replace(microsecond=0)
        actor_id = uuid.uuid4()
        page_id = uuid.uuid4()
        source_ref = f"cyg124/sanitized/{unique}"
        other_source_ref = f"cyg124/sanitized/other-{unique}"
        import_digest = unique[:24]
        signal_ids = {
            "unpromoted": uuid.uuid4(),
            "pending": uuid.uuid4(),
            "published": uuid.uuid4(),
            "mixed": uuid.uuid4(),
            "other": uuid.uuid4(),
        }
        draft_ids = {"pending": uuid.uuid4(), "published": uuid.uuid4()}
        promotion_ids = {"pending": uuid.uuid4(), "published": uuid.uuid4()}
        event_ids = {
            "pending_proposal": uuid.uuid4(),
            "pending_review": uuid.uuid4(),
            "published_proposal": uuid.uuid4(),
            "published_review": uuid.uuid4(),
            "published_approval": uuid.uuid4(),
            "published_publish": uuid.uuid4(),
        }
        publication_id = uuid.uuid4()

        try:
            async with sessions() as session:
                actor = Employee(
                    id=actor_id,
                    name="CYG-124 pilot operator",
                    email=f"cyg124-{unique}@example.test",
                    role="admin",
                    global_role="admin",
                    is_active=True,
                )
                page = WikiPage(
                    id=page_id,
                    slug=f"cyg-124-{unique}",
                    title="CYG-124 published pilot object",
                    status="mature",
                    content_md="# Published pilot object",
                    summary="Published pilot object.",
                    scope_type="global",
                    scope_id=None,
                    knowledge_type_slugs=["troubleshooting_flow"],
                    source_ids=[],
                    version=1,
                    orphaned=False,
                    created_at=now,
                    updated_at=now,
                )
                signals = {
                    "unpromoted": _signal(
                        signal_id=signal_ids["unpromoted"],
                        actor_id=actor_id,
                        suffix=f"{unique}:unpromoted",
                        source_ref=source_ref,
                        import_digest=import_digest,
                        created_at=now,
                    ),
                    "pending": _signal(
                        signal_id=signal_ids["pending"],
                        actor_id=actor_id,
                        suffix=f"{unique}:pending",
                        source_ref=source_ref,
                        import_digest=import_digest,
                        created_at=now + timedelta(minutes=1),
                        status="resolved",
                    ),
                    "published": _signal(
                        signal_id=signal_ids["published"],
                        actor_id=actor_id,
                        suffix=f"{unique}:published",
                        source_ref=source_ref,
                        import_digest=import_digest,
                        created_at=now + timedelta(minutes=2),
                        status="resolved",
                    ),
                    "mixed": _signal(
                        signal_id=signal_ids["mixed"],
                        actor_id=actor_id,
                        suffix=f"{unique}:mixed",
                        source_ref=source_ref,
                        second_source_ref=other_source_ref,
                        import_digest=import_digest,
                        created_at=now + timedelta(minutes=3),
                    ),
                    "other": _signal(
                        signal_id=signal_ids["other"],
                        actor_id=actor_id,
                        suffix=f"{unique}:other",
                        source_ref=other_source_ref,
                        import_digest=f"other-{import_digest}"[:24],
                        created_at=now + timedelta(minutes=4),
                    ),
                }
                pending_draft = _draft(
                    draft_id=draft_ids["pending"],
                    actor_id=actor_id,
                    status="pending",
                    created_at=now + timedelta(hours=1),
                )
                published_draft = _draft(
                    draft_id=draft_ids["published"],
                    actor_id=actor_id,
                    status="approved",
                    created_at=now + timedelta(hours=1, minutes=2),
                    page_id=page_id,
                )
                pending_promotion = _promotion(
                    promotion_id=promotion_ids["pending"],
                    signal=signals["pending"],
                    draft=pending_draft,
                    actor_id=actor_id,
                    created_at=now + timedelta(hours=1, minutes=1),
                )
                published_promotion = _promotion(
                    promotion_id=promotion_ids["published"],
                    signal=signals["published"],
                    draft=published_draft,
                    actor_id=actor_id,
                    created_at=now + timedelta(hours=1, minutes=2),
                )
                pending_events = (
                    _event(
                        event_id=event_ids["pending_proposal"],
                        draft_id=pending_draft.id,
                        actor_id=actor_id,
                        sequence=1,
                        event_type=GovernanceEventType.PROPOSAL_CREATED,
                        from_state=None,
                        to_state="draft",
                        occurred_at=now + timedelta(hours=1, minutes=1),
                    ),
                    _event(
                        event_id=event_ids["pending_review"],
                        draft_id=pending_draft.id,
                        actor_id=actor_id,
                        sequence=2,
                        event_type=GovernanceEventType.REVIEW_REQUESTED,
                        from_state="draft",
                        to_state="in_review",
                        occurred_at=now + timedelta(hours=2, minutes=1),
                    ),
                )
                published_events = (
                    _event(
                        event_id=event_ids["published_proposal"],
                        draft_id=published_draft.id,
                        actor_id=actor_id,
                        sequence=1,
                        event_type=GovernanceEventType.PROPOSAL_CREATED,
                        from_state=None,
                        to_state="draft",
                        occurred_at=now + timedelta(hours=1, minutes=2),
                    ),
                    _event(
                        event_id=event_ids["published_review"],
                        draft_id=published_draft.id,
                        actor_id=actor_id,
                        sequence=2,
                        event_type=GovernanceEventType.REVIEW_REQUESTED,
                        from_state="draft",
                        to_state="in_review",
                        occurred_at=now + timedelta(hours=2, minutes=2),
                    ),
                    _event(
                        event_id=event_ids["published_approval"],
                        draft_id=published_draft.id,
                        actor_id=actor_id,
                        sequence=3,
                        event_type=GovernanceEventType.APPROVED,
                        from_state="in_review",
                        to_state="approved",
                        occurred_at=now + timedelta(hours=3, minutes=2),
                    ),
                    _event(
                        event_id=event_ids["published_publish"],
                        draft_id=published_draft.id,
                        actor_id=actor_id,
                        sequence=4,
                        event_type=GovernanceEventType.PUBLISHED,
                        from_state="approved",
                        to_state="published",
                        occurred_at=now + timedelta(hours=4, minutes=2),
                    ),
                )
                publication = GovernancePublication(
                    id=publication_id,
                    draft_id=published_draft.id,
                    page_id=page_id,
                    approval_event_id=event_ids["published_approval"],
                    publish_event_id=event_ids["published_publish"],
                    command_id=f"cyg124-publish:{unique}",
                    request_fingerprint=uuid.uuid4().hex * 2,
                    object_ref=f"wiki-page:{page_id}",
                    object_type="troubleshooting_flow",
                    object_version=1,
                    action_key="publish",
                    target_channels=["internal_copilot"],
                    previous_object_status="draft",
                    effective_object_status="published",
                    candidate={},
                    preview={},
                    opened_bindings=[],
                    removed_bindings=[],
                    held_bindings=[],
                    action_log=["published"],
                    published_by_id=actor_id,
                    published_at=now + timedelta(hours=4, minutes=2),
                )
                session.add_all(
                    [actor, page, *signals.values(), pending_draft, published_draft]
                )
                await session.flush()
                session.add_all(
                    [
                        pending_promotion,
                        published_promotion,
                        *pending_events,
                        *published_events,
                    ]
                )
                await session.flush()
                session.add(publication)
                await session.commit()

            async with sessions() as session:
                report = await get_ticket_pilot_funnel(
                    session,
                    query=TicketPilotFunnelQuery(source_ref=source_ref),
                )
                payload = report.to_dict()
                self.assertEqual(payload["matched_signal_count"], 4)
                self.assertEqual(payload["excluded_signal_count"], 1)
                self.assertEqual(payload["import_digests"], [import_digest])
                observation = _mapping(payload["observation"])
                self.assertEqual(observation["state"], "partial")
                summary = _mapping(payload["summary"])
                self.assertEqual(summary["eligible_signal_count"], 3)
                self.assertEqual(summary["promoted_draft_count"], 2)
                self.assertEqual(summary["review_submitted_draft_count"], 2)
                self.assertEqual(summary["review_decided_draft_count"], 1)
                self.assertEqual(summary["approved_draft_count"], 1)
                self.assertEqual(summary["published_draft_count"], 1)
                self.assertEqual(
                    _mapping(summary["rates"]),
                    {
                        "signal_to_draft": 0.6667,
                        "draft_to_review": 1.0,
                        "terminal_review_acceptance": 1.0,
                        "draft_to_publish": 0.5,
                    },
                )
                source_items = cast(list[object], payload["items"])
                self.assertEqual(len(source_items), 3)
                self.assertTrue(
                    all(
                        _mapping(item)["source_ref"] == source_ref
                        for item in source_items
                    )
                )

                other_report = await get_ticket_pilot_funnel(
                    session,
                    query=TicketPilotFunnelQuery(source_ref=other_source_ref),
                )
                other_payload = other_report.to_dict()
                self.assertEqual(other_payload["matched_signal_count"], 2)
                self.assertEqual(other_payload["excluded_signal_count"], 1)
                self.assertEqual(
                    _mapping(other_payload["summary"])["eligible_signal_count"],
                    1,
                )

            async with sessions() as session:
                restarted_payload = (
                    await get_ticket_pilot_funnel(
                        session,
                        query=TicketPilotFunnelQuery(source_ref=source_ref),
                    )
                ).to_dict()
                self.assertEqual(restarted_payload, payload)
        finally:
            try:
                async with sessions() as session:
                    _ = await session.execute(
                        delete(GovernancePublication).where(
                            GovernancePublication.id == publication_id
                        )
                    )
                    _ = await session.execute(
                        delete(GovernanceTicketDraftPromotion).where(
                            GovernanceTicketDraftPromotion.id.in_(
                                tuple(promotion_ids.values())
                            )
                        )
                    )
                    _ = await session.execute(
                        delete(GovernanceLedgerEvent).where(
                            GovernanceLedgerEvent.id.in_(tuple(event_ids.values()))
                        )
                    )
                    _ = await session.execute(
                        delete(WikiPageDraft).where(
                            WikiPageDraft.id.in_(tuple(draft_ids.values()))
                        )
                    )
                    _ = await session.execute(
                        delete(GovernanceSignal).where(
                            GovernanceSignal.id.in_(tuple(signal_ids.values()))
                        )
                    )
                    _ = await session.execute(
                        delete(WikiPage).where(WikiPage.id == page_id)
                    )
                    _ = await session.execute(
                        delete(Employee).where(Employee.id == actor_id)
                    )
                    await session.commit()
            finally:
                await engine.dispose()


if __name__ == "__main__":
    _ = unittest.main()
