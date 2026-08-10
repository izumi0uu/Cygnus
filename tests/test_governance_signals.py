from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from sqlalchemy.dialects import postgresql

from cygnus.domain import AudienceFilter, KnowledgeObjectType, Visibility
from cygnus.evidence import EvidenceSourceType, FreshnessState
from cygnus.governance.signals import (
    GovernanceSignalConflict,
    GovernanceSignalInput,
    compile_review_signal_bundles,
    create_governance_signal,
    governance_signal_to_pressure_record,
    list_governance_signals,
    resolve_governance_signal,
)
from cygnus.review import PressureSignalType
from cygnus.runtime.database.models import Employee, GovernanceSignal


_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
_CREATOR_ID = uuid.uuid4()


def _signal(
    *,
    signal_ref: str = "ticket:billing-verification:w32",
    signal_type: str = "ticket_cluster",
    object_ref: str = "ko-billing-verification",
    title: str = "Billing verification pressure",
) -> GovernanceSignal:
    return GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref=signal_ref,
        signal_type=signal_type,
        object_ref=object_ref,
        title=title,
        object_type="troubleshooting_flow",
        page_id=None,
        source_id=None,
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
        trigger_signals=["ticket_pressure"],
        evidence_source_type="resolved_ticket",
        freshness="fresh",
        summary="Repeated tickets show a governed knowledge gap.",
        reason="The recurring intent crossed the review threshold.",
        evidence_excerpt="Agents reconstruct the same verification sequence.",
        status="active",
        observed_at=_NOW,
        resolved_at=None,
        created_by_id=_CREATOR_ID,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


def _signal_input(
    *,
    title: str = "Billing verification pressure",
) -> GovernanceSignalInput:
    return GovernanceSignalInput(
        signal_ref="ticket:billing-verification:w32",
        signal_type=PressureSignalType.TICKET_CLUSTER,
        object_ref="ko-billing-verification",
        title=title,
        object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
        audience_filter=AudienceFilter(
            visibility=Visibility.INTERNAL,
            product_lines=("billing",),
        ),
        affected_surfaces=("copilot", "queue-sidebar"),
        trigger_signals=("ticket_pressure",),
        evidence_source_type=EvidenceSourceType.RESOLVED_TICKET,
        freshness=FreshnessState.FRESH,
        summary="Repeated tickets show a governed knowledge gap.",
        reason="The recurring intent crossed the review threshold.",
        evidence_excerpt="Agents reconstruct the same verification sequence.",
    )


class GovernanceSignalServiceTests(unittest.TestCase):
    def test_ticket_and_rewrite_rows_compile_as_ticket_pressure(self) -> None:
        rewrite = _signal(
            signal_ref="rewrite:refund:enterprise",
            signal_type="human_rewrite",
            object_ref="ko-refund-policy",
            title="Refund rewrite pressure",
        )
        rewrite.object_type = "policy_rule"
        rewrite.evidence_source_type = "chat_transcript"

        bundles = compile_review_signal_bundles((_signal(), rewrite))

        self.assertEqual(len(bundles), 2)
        self.assertEqual(
            {bundle.signal.risk_type.value for bundle in bundles},
            {"ticket_pressure"},
        )
        self.assertEqual(
            {bundle.proposal.proposal_id for bundle in bundles},
            {"ko-billing-verification", "ko-refund-policy"},
        )

    def test_feedback_rows_default_to_feedback_evidence_and_compile_review_truth(
        self,
    ) -> None:
        for signal_type, freshness in (
            (PressureSignalType.LOW_RATING, FreshnessState.UNKNOWN),
            (PressureSignalType.STALE_ANSWER, FreshnessState.STALE),
        ):
            with self.subTest(signal_type=signal_type.value):
                signal_input = replace(
                    _signal_input(),
                    signal_ref=f"feedback-route:{signal_type.value}",
                    signal_type=signal_type,
                    evidence_source_type=None,
                    freshness=freshness,
                )
                self.assertEqual(
                    signal_input.evidence_source_type,
                    EvidenceSourceType.CONSUMPTION_FEEDBACK,
                )

        low_rating = _signal(
            signal_ref="feedback-route:low-rating",
            signal_type=PressureSignalType.LOW_RATING.value,
            object_ref="ko-feedback-low-rating",
            title="Low answer rating",
        )
        stale_answer = _signal(
            signal_ref="feedback-route:stale-answer",
            signal_type=PressureSignalType.STALE_ANSWER.value,
            object_ref="ko-feedback-stale-answer",
            title="Suspected stale answer",
        )
        for signal, freshness in (
            (low_rating, FreshnessState.UNKNOWN),
            (stale_answer, FreshnessState.STALE),
        ):
            signal.evidence_source_type = EvidenceSourceType.CONSUMPTION_FEEDBACK.value
            signal.freshness = freshness.value
            signal.affected_surfaces = ["feedback", "review_queue"]
            signal.trigger_signals = [signal.signal_type]

        bundles = compile_review_signal_bundles((low_rating, stale_answer))
        bundles_by_ref = {bundle.signal.signal_ref: bundle for bundle in bundles}

        self.assertEqual(
            set(bundles_by_ref),
            {low_rating.signal_ref, stale_answer.signal_ref},
        )
        self.assertEqual(
            bundles_by_ref[low_rating.signal_ref].signal.risk_type.value,
            "ticket_pressure",
        )
        self.assertEqual(
            bundles_by_ref[stale_answer.signal_ref].signal.risk_type.value,
            "drift",
        )
        self.assertEqual(
            bundles_by_ref[low_rating.signal_ref].proposal.urgency.value,
            "medium",
        )
        self.assertEqual(
            bundles_by_ref[stale_answer.signal_ref].proposal.urgency.value,
            "high",
        )
        self.assertEqual(
            {
                bundle.proposal.evidence_sufficiency.value
                for bundle in bundles_by_ref.values()
            },
            {"partial"},
        )
        self.assertEqual(
            {bundle.signal.recommended_actions for bundle in bundles_by_ref.values()},
            {("open_review", "assign_owner")},
        )
        self.assertEqual(
            bundles_by_ref[low_rating.signal_ref].evidence[0].freshness_state,
            FreshnessState.UNKNOWN,
        )
        self.assertEqual(
            bundles_by_ref[stale_answer.signal_ref].evidence[0].freshness_state,
            FreshnessState.STALE,
        )
        self.assertEqual(
            {bundle.evidence[0].source_type for bundle in bundles_by_ref.values()},
            {EvidenceSourceType.CONSUMPTION_FEEDBACK},
        )
        self.assertIn(
            "low answer rating",
            bundles_by_ref[low_rating.signal_ref].proposal.why_now.lower(),
        )
        self.assertIn(
            "may be out of date",
            bundles_by_ref[stale_answer.signal_ref].proposal.why_now.lower(),
        )
        self.assertNotIn(
            "release",
            bundles_by_ref[stale_answer.signal_ref].proposal.why_now.lower(),
        )
        self.assertNotIn(
            "incident",
            bundles_by_ref[stale_answer.signal_ref].proposal.why_now.lower(),
        )

    def test_binding_backed_row_accepts_an_explicit_resolved_filter(self) -> None:
        signal = _signal()
        signal.audience_filter = None
        signal.audience_binding_ref = "binding:billing-internal"

        record = governance_signal_to_pressure_record(
            signal,
            AudienceFilter(
                visibility=Visibility.INTERNAL,
                product_lines=("billing",),
            ),
        )

        self.assertEqual(record.audience_filter.product_lines, ("billing",))
        self.assertEqual(record.proposal_id, "ko-billing-verification")

    def test_create_initializes_one_durable_review_assignment(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        actor_id = uuid.uuid4()

        with (
            patch(
                "cygnus.governance.signals.lock_governance_command",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.governance.signals.initialize_review_assignment",
                AsyncMock(return_value=None),
            ) as initialize_assignment,
        ):
            created = asyncio.run(
                create_governance_signal(
                    session,
                    _signal_input(),
                    created_by_id=actor_id,
                )
            )

        session.add.assert_called_once_with(created)
        session.flush.assert_awaited_once_with()
        initialize_assignment.assert_awaited_once_with(
            session,
            created,
            actor_id=actor_id,
        )

    def test_create_returns_exact_idempotent_signal_ref_replay(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        existing = _signal()
        result.scalar_one_or_none.return_value = existing
        session.execute.return_value = result

        with patch(
            "cygnus.governance.signals.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            replay = asyncio.run(
                create_governance_signal(
                    session,
                    _signal_input(),
                    created_by_id=uuid.uuid4(),
                )
            )

        self.assertIs(replay, existing)
        session.add.assert_not_called()
        session.flush.assert_not_awaited()

    def test_create_rejects_signal_ref_reuse_for_different_content(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _signal()
        session.execute.return_value = result

        with patch(
            "cygnus.governance.signals.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(GovernanceSignalConflict):
                asyncio.run(
                    create_governance_signal(
                        session,
                        _signal_input(title="Different durable fact"),
                        created_by_id=uuid.uuid4(),
                    )
                )

    def test_resolve_is_idempotent_and_versions_the_first_transition(self) -> None:
        session = AsyncMock()
        signal = _signal()
        result = MagicMock()
        result.scalar_one_or_none.return_value = signal
        session.execute.return_value = result

        with patch(
            "cygnus.governance.signals.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            resolved = asyncio.run(
                resolve_governance_signal(
                    session,
                    signal.signal_ref,
                    resolved_at=_NOW,
                )
            )
            replay = asyncio.run(resolve_governance_signal(session, signal.signal_ref))

        self.assertIs(resolved, signal)
        self.assertIs(replay, signal)
        self.assertEqual(signal.status, "resolved")
        self.assertEqual(signal.resolved_at, _NOW)
        self.assertEqual(signal.version, 2)
        self.assertEqual(session.flush.await_count, 1)

    def test_non_admin_list_query_embeds_page_and_source_scope(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute.return_value = result
        user = SimpleNamespace(
            role="employee",
            global_role="viewer",
            department_ids=(uuid.uuid4(),),
        )

        rows = asyncio.run(
            list_governance_signals(
                session,
                current_user=cast(Employee, cast(object, user)),
            )
        )

        statement = session.execute.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertEqual(rows, ())
        self.assertIn("EXISTS", sql)
        self.assertIn("governance_signals.page_id", sql)
        self.assertIn("governance_signals.source_id", sql)
        self.assertIn("source_departments", sql)


if __name__ == "__main__":
    unittest.main()
