from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import cast
import unittest
from unittest.mock import AsyncMock, MagicMock
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.ledger import GovernanceEventType
from cygnus.governance.ticket_pilot import (
    TicketPilotFunnelQuery,
    get_ticket_pilot_funnel,
)
from cygnus.runtime.database.models import (
    GovernanceLedgerEvent,
    GovernancePublication,
    GovernanceSignal,
    GovernanceTicketDraftPromotion,
    WikiPageDraft,
)


_NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
_ACTOR_ID = uuid.uuid4()
_SOURCE_REF = "sanitized-helpdesk-export/2026-w32"


class _ScalarRows:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self.rows: tuple[object, ...] = rows

    def all(self) -> tuple[object, ...]:
        return self.rows


class _Result:
    def __init__(self, *rows: object) -> None:
        self.rows: tuple[object, ...] = rows

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self.rows)


def _session(*results: _Result) -> AsyncSession:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    return cast(AsyncSession, cast(object, session))


def _signal(
    *,
    suffix: str,
    source_ref: str = _SOURCE_REF,
    second_source_ref: str | None = None,
    created_at: datetime = _NOW,
) -> GovernanceSignal:
    signal_id = uuid.uuid4()
    sources = (source_ref, second_source_ref or source_ref)
    return GovernanceSignal(
        id=signal_id,
        signal_ref=f"ticket-import:{suffix}",
        signal_type="ticket_cluster",
        object_ref=f"ticket-cluster:{suffix}",
        title=f"Ticket cluster {suffix}",
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
            "ticket_import:digest-w32",
        ],
        evidence_source_type="resolved_ticket",
        freshness="unknown",
        summary="Repeated resolved tickets show one reusable troubleshooting gap.",
        reason="member_count=2 met minimum_cluster_size=2.",
        evidence_excerpt="Sanitized recurring support pattern.",
        evidence_refs=[
            {
                "evidence_id": f"ev-ticket:{suffix}:1",
                "source_ref": f"{sources[0]}#ticket=1",
                "excerpt": "Sanitized ticket one.",
                "observed_at": created_at.isoformat(),
            },
            {
                "evidence_id": f"ev-ticket:{suffix}:2",
                "source_ref": f"{sources[1]}#ticket=2",
                "excerpt": "Sanitized ticket two.",
                "observed_at": created_at.isoformat(),
            },
        ],
        status="active",
        observed_at=created_at - timedelta(hours=1),
        resolved_at=None,
        created_by_id=_ACTOR_ID,
        created_at=created_at,
        updated_at=created_at,
        version=1,
    )


def _promotion(
    signal: GovernanceSignal,
    draft: WikiPageDraft,
    *,
    created_at: datetime,
) -> GovernanceTicketDraftPromotion:
    return GovernanceTicketDraftPromotion(
        id=uuid.uuid4(),
        signal_id=signal.id,
        draft_id=draft.id,
        command_id=f"ticket-draft-promotion:{signal.id}",
        request_fingerprint=uuid.uuid4().hex * 2,
        source_signal_version=1,
        expected_assignment_version=1,
        actor_id=_ACTOR_ID,
        reason="Reviewer promoted this eligible cluster.",
        created_at=created_at,
    )


def _draft(*, status: str, created_at: datetime) -> WikiPageDraft:
    return WikiPageDraft(
        id=uuid.uuid4(),
        page_id=None,
        draft_kind="create",
        suggested_metadata={"title": "Ticket cluster", "slug": "ticket-cluster"},
        author_id=_ACTOR_ID,
        content_md="# Ticket cluster\n\nGoverned draft.",
        note="Reviewer-created pilot draft.",
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
        reviewed_by_id=_ACTOR_ID if status != "draft" else None,
        reviewed_at=created_at if status != "draft" else None,
        reviewer_note=None,
        created_at=created_at,
        updated_at=created_at,
    )


def _event(
    draft: WikiPageDraft,
    *,
    sequence: int,
    event_type: GovernanceEventType,
    from_state: str,
    to_state: str,
    occurred_at: datetime,
) -> GovernanceLedgerEvent:
    return GovernanceLedgerEvent(
        id=uuid.uuid4(),
        draft_id=draft.id,
        sequence=sequence,
        event_type=event_type.value,
        from_state=from_state,
        to_state=to_state,
        actor_id=_ACTOR_ID,
        idempotency_key=f"test:{draft.id}:{sequence}",
        reason="Pilot lifecycle transition.",
        payload={},
        occurred_at=occurred_at,
        recorded_at=occurred_at,
    )


def _publication(
    draft: WikiPageDraft,
    *,
    approval_event: GovernanceLedgerEvent,
    publish_event: GovernanceLedgerEvent,
    published_at: datetime,
) -> GovernancePublication:
    return GovernancePublication(
        id=uuid.uuid4(),
        draft_id=draft.id,
        page_id=uuid.uuid4(),
        approval_event_id=approval_event.id,
        publish_event_id=publish_event.id,
        command_id=f"publish:{draft.id}",
        request_fingerprint=uuid.uuid4().hex * 2,
        object_ref=f"wiki-page:{draft.id}",
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
        published_by_id=_ACTOR_ID,
        published_at=published_at,
    )


class TicketPilotFunnelContractTests(unittest.TestCase):
    def test_query_normalizes_exact_source_reference(self) -> None:
        query = TicketPilotFunnelQuery(source_ref=f"  {_SOURCE_REF}  ")
        self.assertEqual(query.source_ref, _SOURCE_REF)

        with self.assertRaises(ValueError):
            _ = TicketPilotFunnelQuery(source_ref="   ")
        with self.assertRaises(ValueError):
            _ = TicketPilotFunnelQuery(source_ref="bad\nsource")
        with self.assertRaises(ValueError):
            _ = TicketPilotFunnelQuery(source_ref="x" * 301)

    def test_report_projects_partial_and_published_funnels(self) -> None:
        eligible = _signal(suffix="eligible")
        unpromoted = _signal(
            suffix="unpromoted", created_at=_NOW + timedelta(minutes=5)
        )
        draft = _draft(status="approved", created_at=_NOW + timedelta(hours=1))
        promotion = _promotion(eligible, draft, created_at=_NOW + timedelta(hours=1))
        review_event = _event(
            draft,
            sequence=2,
            event_type=GovernanceEventType.REVIEW_REQUESTED,
            from_state="draft",
            to_state="in_review",
            occurred_at=_NOW + timedelta(hours=2),
        )
        approval_event = _event(
            draft,
            sequence=3,
            event_type=GovernanceEventType.APPROVED,
            from_state="in_review",
            to_state="approved",
            occurred_at=_NOW + timedelta(hours=3),
        )
        publish_event = _event(
            draft,
            sequence=4,
            event_type=GovernanceEventType.PUBLISHED,
            from_state="approved",
            to_state="published",
            occurred_at=_NOW + timedelta(hours=4),
        )
        publication = _publication(
            draft,
            approval_event=approval_event,
            publish_event=publish_event,
            published_at=_NOW + timedelta(hours=4),
        )
        session = _session(
            _Result(eligible, unpromoted),
            _Result(promotion),
            _Result(draft),
            _Result(review_event, approval_event),
            _Result(publication),
        )

        report = asyncio.run(
            get_ticket_pilot_funnel(
                session,
                query=TicketPilotFunnelQuery(source_ref=_SOURCE_REF),
            )
        ).to_dict()

        summary = cast(Mapping[str, object], report["summary"])
        self.assertEqual(summary["eligible_signal_count"], 2)
        self.assertEqual(summary["promoted_draft_count"], 1)
        self.assertEqual(summary["review_submitted_draft_count"], 1)
        self.assertEqual(summary["review_decided_draft_count"], 1)
        self.assertEqual(summary["approved_draft_count"], 1)
        self.assertEqual(summary["published_draft_count"], 1)
        rates = cast(Mapping[str, object], summary["rates"])
        self.assertEqual(
            rates,
            {
                "signal_to_draft": 0.5,
                "draft_to_review": 1.0,
                "terminal_review_acceptance": 1.0,
                "draft_to_publish": 1.0,
            },
        )
        items = cast(list[Mapping[str, object]], report["items"])
        promoted_item = next(
            item
            for item in items
            if cast(Mapping[str, object], item["promotion"])["id"] is not None
        )
        durations = cast(Mapping[str, object], promoted_item["durations_seconds"])
        self.assertEqual(
            durations,
            {
                "signal_to_draft": 3600.0,
                "draft_to_review": 3600.0,
                "signal_to_publish": 14400.0,
            },
        )
        self.assertNotIn("evidence_excerpt", promoted_item)
        metric_boundary = cast(Mapping[str, object], report["metric_boundary"])
        self.assertFalse(metric_boundary["business_impact_proven"])

    def test_empty_source_is_ready_with_null_rate_denominators(self) -> None:
        session = _session(_Result())

        report = asyncio.run(
            get_ticket_pilot_funnel(
                session,
                query=TicketPilotFunnelQuery(source_ref=_SOURCE_REF),
            )
        ).to_dict()

        self.assertEqual(report["items"], [])
        observation = cast(Mapping[str, object], report["observation"])
        self.assertEqual(observation["state"], "ready")
        summary = cast(Mapping[str, object], report["summary"])
        self.assertEqual(
            summary["rates"],
            {
                "signal_to_draft": None,
                "draft_to_review": None,
                "terminal_review_acceptance": None,
                "draft_to_publish": None,
            },
        )

    def test_mixed_source_evidence_is_excluded_and_explicitly_partial(self) -> None:
        mixed = _signal(
            suffix="mixed",
            second_source_ref="sanitized-helpdesk-export/other",
        )
        session = _session(_Result(mixed), _Result())

        report = asyncio.run(
            get_ticket_pilot_funnel(
                session,
                query=TicketPilotFunnelQuery(source_ref=_SOURCE_REF),
            )
        ).to_dict()

        self.assertEqual(report["matched_signal_count"], 1)
        self.assertEqual(report["excluded_signal_count"], 1)
        self.assertEqual(report["items"], [])
        observation = cast(Mapping[str, object], report["observation"])
        self.assertEqual(observation["state"], "partial")
        self.assertEqual(
            observation["missing_signals"],
            ["ticket_source_evidence_integrity"],
        )


if __name__ == "__main__":
    _ = unittest.main()
