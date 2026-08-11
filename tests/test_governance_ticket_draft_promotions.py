from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch
import uuid
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence
from cygnus.review.briefing import OwnerState, ReviewRiskType
from cygnus.review.service import (
    ProposalBundle,
    ReviewSignal,
    build_review_risk_item,
)
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)

from cygnus.governance.ticket_draft_promotions import (
    TicketDraftPromotionCommand,
    TicketDraftPromotionConflict,
    promote_ticket_cluster_to_draft,
)
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    GovernanceReviewAssignment,
    GovernanceSignal,
    GovernanceTicketDraftPromotion,
    WikiPageDraft,
)
from cygnus.runtime.routers.governance.signals import router
from cygnus.runtime.services.auth_service import require_admin

_NOW = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
_ACTOR_ID = uuid.uuid4()


class _Result:
    _row: tuple[GovernanceSignal, GovernanceReviewAssignment] | None
    _scalar: GovernanceTicketDraftPromotion | None

    def __init__(
        self,
        *,
        row: tuple[GovernanceSignal, GovernanceReviewAssignment] | None = None,
        scalar: GovernanceTicketDraftPromotion | None = None,
    ) -> None:
        self._row = row
        self._scalar = scalar

    def one_or_none(
        self,
    ) -> tuple[GovernanceSignal, GovernanceReviewAssignment] | None:
        return self._row

    def scalar_one_or_none(self) -> GovernanceTicketDraftPromotion | None:
        return self._scalar


def _signal(*, source_id: uuid.UUID | None = None) -> GovernanceSignal:
    signal = GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref="ticket:billing-verification:w32",
        signal_type="ticket_cluster",
        object_ref="cluster/billing-verification:w32",
        title="Billing verification cluster",
        object_type="troubleshooting_flow",
        page_id=None,
        source_id=source_id,
        audience_binding_ref=None,
        audience_filter={
            "visibility": "internal",
            "brands": [],
            "product_lines": ["billing"],
            "plans": [],
            "regions": [],
            "languages": [],
            "product_versions": [],
        },
        affected_surfaces=["copilot", "queue-sidebar"],
        trigger_signals=["ticket_cluster", "ticket_import:batch-32"],
        evidence_source_type="resolved_ticket",
        freshness="fresh",
        summary="Repeated tickets show a governed verification gap.",
        reason="The recurring intent crossed the review threshold.",
        evidence_excerpt="Agents repeatedly reconstruct the same steps.",
        evidence_refs=[
            {
                "evidence_id": "ticket-1001",
                "source_ref": "ticket:1001",
                "excerpt": "The verification sequence was unclear.",
                "observed_at": _NOW.isoformat(),
            },
            {
                "evidence_id": "ticket-1002",
                "source_ref": "ticket:1002",
                "excerpt": "A second customer hit the same gap.",
                "observed_at": _NOW.isoformat(),
            },
        ],
        status="active",
        observed_at=_NOW,
        resolved_at=None,
        created_by_id=_ACTOR_ID,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )
    return signal


def _assignment(signal: GovernanceSignal) -> GovernanceReviewAssignment:
    return GovernanceReviewAssignment(
        id=uuid.uuid4(),
        signal_id=signal.id,
        lifecycle_state="assigned",
        owner_ref="support-ops",
        escalation_reason=None,
        version=3,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _draft() -> WikiPageDraft:
    return WikiPageDraft(
        id=uuid.uuid4(),
        page_id=None,
        author_id=_ACTOR_ID,
        content_md="# Billing verification cluster\n\nSummary",
        note="Promote the qualifying cluster.",
        status="draft",
        source="web_ui",
        source_metadata={"object_type": "troubleshooting_flow"},
        base_version=None,
        draft_kind="create",
        suggested_metadata={
            "slug": "billing-verification-cluster",
            "title": "Billing verification cluster",
        },
        version=1,
        revision_round=0,
        ai_check_status="pending",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _session(
    signal: GovernanceSignal,
    assignment: GovernanceReviewAssignment,
    *,
    existing_command: GovernanceTicketDraftPromotion | None = None,
    existing_signal: GovernanceTicketDraftPromotion | None = None,
    draft: WikiPageDraft | None = None,
) -> AsyncSession:
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=(
            _Result(row=(signal, assignment)),
            _Result(scalar=existing_command),
            _Result(scalar=existing_signal),
        )
    )
    session.get = AsyncMock(return_value=draft)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return cast(AsyncSession, cast(object, session))


class TicketDraftPromotionServiceTests(unittest.TestCase):
    def test_qualifying_ticket_cluster_creates_unsubmitted_draft_and_resolves_signal(
        self,
    ) -> None:
        source_id = uuid.uuid4()
        signal = _signal(source_id=source_id)
        assignment = _assignment(signal)
        draft = _draft()
        command = TicketDraftPromotionCommand(
            command_id="ticket-draft-promotion:batch-32",
            expected_assignment_version=3,
            reason="Promote the qualifying cluster.",
        )
        create_draft = AsyncMock(return_value=draft)
        resolve_signal = AsyncMock(return_value=signal)
        with (
            patch(
                "cygnus.governance.ticket_draft_promotions.lock_governance_command",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.governance.ticket_draft_promotions.create_wiki_draft",
                create_draft,
            ),
            patch(
                "cygnus.governance.ticket_draft_promotions.resolve_governance_signal",
                resolve_signal,
            ),
        ):
            result = asyncio.run(
                promote_ticket_cluster_to_draft(
                    _session(signal, assignment, draft=draft),
                    signal_ref=signal.signal_ref,
                    command=command,
                    actor_id=_ACTOR_ID,
                )
            )

        assert result is not None
        self.assertFalse(result.replayed)
        self.assertEqual(result.draft, draft)
        promotion = result.promotion
        self.assertEqual(promotion.signal_id, signal.id)
        self.assertEqual(promotion.draft_id, draft.id)
        self.assertEqual(promotion.source_signal_version, 1)
        self.assertEqual(promotion.expected_assignment_version, 3)
        create_draft.assert_awaited_once()
        await_args = create_draft.await_args
        self.assertIsNotNone(await_args)
        assert await_args is not None
        create_kwargs = cast(dict[str, object], await_args.kwargs)
        source_metadata = cast(dict[str, object], create_kwargs["source_metadata"])
        self.assertEqual(create_kwargs["draft_kind"], "create")
        self.assertFalse(create_kwargs["submit_for_review"])
        self.assertEqual(source_metadata["ticket_cluster_ref"], signal.object_ref)
        self.assertEqual(source_metadata["evidence_refs"], signal.evidence_refs)
        self.assertEqual(source_metadata["source_ids"], [str(source_id)])
        resolve_signal.assert_awaited_once_with(
            ANY,
            signal.signal_ref,
            resolved_at=ANY,
        )
        payload = result.to_dict()
        promotion_payload = cast(dict[str, object], payload["promotion"])
        self.assertTrue(promotion_payload["persisted"])
        self.assertEqual(payload["review_state"], "not_submitted")

    def test_exact_command_replay_returns_original_promotion_without_creating_draft(
        self,
    ) -> None:
        signal = _signal()
        assignment = _assignment(signal)
        draft = _draft()
        command = TicketDraftPromotionCommand(
            command_id="ticket-draft-promotion:replay",
            expected_assignment_version=3,
            reason="Promote the qualifying cluster.",
        )
        first_session = _session(signal, assignment, draft=draft)
        with (
            patch(
                "cygnus.governance.ticket_draft_promotions.lock_governance_command",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.governance.ticket_draft_promotions.create_wiki_draft",
                AsyncMock(return_value=draft),
            ),
            patch(
                "cygnus.governance.ticket_draft_promotions.resolve_governance_signal",
                AsyncMock(return_value=signal),
            ),
        ):
            first = asyncio.run(
                promote_ticket_cluster_to_draft(
                    first_session,
                    signal_ref=signal.signal_ref,
                    command=command,
                    actor_id=_ACTOR_ID,
                )
            )
        assert first is not None
        replay_session = _session(
            signal,
            assignment,
            existing_command=first.promotion,
            draft=draft,
        )
        create_draft = AsyncMock()
        with (
            patch(
                "cygnus.governance.ticket_draft_promotions.lock_governance_command",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.governance.ticket_draft_promotions.create_wiki_draft",
                create_draft,
            ),
        ):
            replay = asyncio.run(
                promote_ticket_cluster_to_draft(
                    replay_session,
                    signal_ref=signal.signal_ref,
                    command=command,
                    actor_id=_ACTOR_ID,
                )
            )

        assert replay is not None
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.promotion.id, first.promotion.id)
        create_draft.assert_not_awaited()

    def test_stale_assignment_and_ineligible_evidence_are_rejected(self) -> None:
        signal = _signal()
        assignment = _assignment(signal)
        stale = TicketDraftPromotionCommand(
            command_id="ticket-draft-promotion:stale",
            expected_assignment_version=2,
            reason="Stale owner snapshot.",
        )
        with patch(
            "cygnus.governance.ticket_draft_promotions.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(TicketDraftPromotionConflict):
                _ = asyncio.run(
                    promote_ticket_cluster_to_draft(
                        _session(signal, assignment),
                        signal_ref=signal.signal_ref,
                        command=stale,
                        actor_id=_ACTOR_ID,
                    )
                )

        signal.evidence_refs = signal.evidence_refs[:1]
        valid_version = TicketDraftPromotionCommand(
            command_id="ticket-draft-promotion:insufficient",
            expected_assignment_version=3,
            reason="Evidence is incomplete.",
        )
        with patch(
            "cygnus.governance.ticket_draft_promotions.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "at least two"):
                _ = asyncio.run(
                    promote_ticket_cluster_to_draft(
                        _session(signal, assignment),
                        signal_ref=signal.signal_ref,
                        command=valid_version,
                        actor_id=_ACTOR_ID,
                    )
                )

    def test_review_item_exposes_create_draft_only_for_eligible_ticket_pressure(
        self,
    ) -> None:
        audience = AudienceFilter(
            visibility=Visibility.INTERNAL,
            product_lines=("billing",),
        )
        proposal = CompilationProposal(
            proposal_id="cluster/billing-verification:w32",
            object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
            action=PlanAction.CREATE,
            title="Billing verification cluster",
            summary="Repeated tickets show a governed verification gap.",
            evidence_ids=("ticket-1001", "ticket-1002"),
            urgency=UrgencyLevel.MEDIUM,
            evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
            review_owner="support-ops",
            why_now="The cluster crossed the review threshold.",
        )
        evidence = tuple(
            SupportEvidence(
                evidence_id=f"ticket-100{i}",
                source_type=EvidenceSourceType.RESOLVED_TICKET,
                source_ref=f"ticket:100{i}",
                title=proposal.title,
                content="The same verification gap recurred.",
                audience_filter=audience,
                product_lines=("billing",),
                freshness_state=FreshnessState.FRESH,
            )
            for i in (1, 2)
        )
        item = build_review_risk_item(
            ProposalBundle(
                proposal=proposal,
                signal=ReviewSignal(
                    proposal_id=proposal.proposal_id,
                    signal_ref="ticket:billing-verification:w32",
                    risk_type=ReviewRiskType.TICKET_PRESSURE,
                    affected_audiences=(audience,),
                    affected_surfaces=("copilot",),
                    trigger_signals=("ticket_cluster", "ticket_import:batch-32"),
                ),
                evidence=evidence,
                owner_state=OwnerState.UNASSIGNED,
                assignment_trace_ref="review-assignment:trace",
                assignment_version=3,
            )
        )
        self.assertIn("create_draft", item.recommended_actions)

    def test_promotion_table_keeps_one_signal_one_draft_and_one_command(self) -> None:
        table = GovernanceTicketDraftPromotion.__table__
        self.assertTrue(table.c.signal_id.unique)
        self.assertTrue(table.c.draft_id.unique)
        self.assertTrue(table.c.command_id.unique)
        self.assertFalse(table.c.actor_id.nullable)


class TicketDraftPromotionApiTests(unittest.TestCase):
    client: TestClient | None = None

    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=_ACTOR_ID)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        assert self.client is not None
        self.client.close()

    def test_promotion_endpoint_passes_versioned_command_and_returns_receipt(
        self,
    ) -> None:
        assert self.client is not None
        result = SimpleNamespace(
            to_dict=lambda: {
                "promotion": {"persisted": True, "draft_id": str(uuid.uuid4())},
                "draft": {"draft_status": "draft"},
            }
        )
        with patch(
            "cygnus.runtime.routers.governance.signals.promote_ticket_cluster_to_draft",
            AsyncMock(return_value=result),
        ) as promote:
            response = self.client.post(
                "/api/governance-signals/ticket%3Abilling%3Aw32/commands/promote-draft",
                json={
                    "command_id": "ticket-draft-promotion:api",
                    "expected_assignment_version": 3,
                    "reason": "Promote the reviewed cluster.",
                },
            )

        self.assertEqual(response.status_code, 200)
        response_payload = cast(dict[str, object], response.json())
        response_promotion = cast(dict[str, object], response_payload["promotion"])
        self.assertTrue(response_promotion["persisted"])
        await_args = promote.await_args
        self.assertIsNotNone(await_args)
        assert await_args is not None
        kwargs = cast(dict[str, object], await_args.kwargs)
        self.assertEqual(kwargs["signal_ref"], "ticket:billing:w32")
        self.assertEqual(kwargs["actor_id"], _ACTOR_ID)
        command = cast(TicketDraftPromotionCommand, kwargs["command"])
        self.assertEqual(command.expected_assignment_version, 3)

    def test_promotion_endpoint_maps_conflict_to_409(self) -> None:
        assert self.client is not None
        with patch(
            "cygnus.runtime.routers.governance.signals.promote_ticket_cluster_to_draft",
            AsyncMock(side_effect=TicketDraftPromotionConflict("stale command")),
        ):
            response = self.client.post(
                "/api/governance-signals/ticket%3Abilling%3Aw32/commands/promote-draft",
                json={
                    "command_id": "ticket-draft-promotion:api-conflict",
                    "expected_assignment_version": 3,
                    "reason": "Retry the promotion.",
                },
            )
        self.assertEqual(response.status_code, 409)
        response_payload = cast(dict[str, object], response.json())
        self.assertIn("stale command", cast(str, response_payload["detail"]))


if __name__ == "__main__":
    _ = unittest.main()
