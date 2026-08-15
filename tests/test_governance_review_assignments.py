from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.review_assignments import (
    ReviewAssignmentAction,
    REVIEW_ASSIGNMENT_REASON_MAX_LENGTH,
    ReviewAssignmentCommand,
    ReviewAssignmentConflict,
    apply_review_assignment_command,
)
from cygnus.retrieval.substrate_provider import SubstrateKnowledgeSnapshot
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    GovernanceReviewAssignment,
    GovernanceReviewAssignmentEvent,
    GovernanceSignal,
)
from cygnus.runtime.routers.governance.assignments import router
from cygnus.runtime.routers.governance.dependencies import get_governance_read_snapshot
from cygnus.runtime.services.auth_service import require_admin

_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
_ACTOR_ID = uuid.uuid4()


class _Result:
    def __init__(
        self,
        *,
        row: tuple[GovernanceSignal, GovernanceReviewAssignment] | None = None,
        scalar: GovernanceReviewAssignmentEvent | None = None,
    ) -> None:
        self._row = row
        self._scalar = scalar

    def one_or_none(
        self,
    ) -> tuple[GovernanceSignal, GovernanceReviewAssignment] | None:
        return self._row

    def scalar_one_or_none(self) -> GovernanceReviewAssignmentEvent | None:
        return self._scalar


def _signal() -> GovernanceSignal:
    return GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref="ticket:billing-verification:w32",
        signal_type="ticket_cluster",
        object_ref="ko-billing-verification",
        title="Billing verification pressure",
        object_type="troubleshooting_flow",
        page_id=None,
        source_id=None,
        audience_binding_ref=None,
        audience_filter={"visibility": "internal"},
        affected_surfaces=["copilot"],
        trigger_signals=["ticket_pressure"],
        evidence_source_type="resolved_ticket",
        freshness="fresh",
        summary="Repeated tickets show a governed knowledge gap.",
        reason="The recurring intent crossed the review threshold.",
        evidence_excerpt="Agents reconstruct the same sequence.",
        status="active",
        observed_at=_NOW,
        resolved_at=None,
        created_by_id=_ACTOR_ID,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


def _assignment(signal: GovernanceSignal) -> GovernanceReviewAssignment:
    return GovernanceReviewAssignment(
        id=uuid.uuid4(),
        signal_id=signal.id,
        lifecycle_state="unassigned",
        owner_ref=None,
        escalation_reason=None,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _command(
    *,
    command_id: str,
    action: ReviewAssignmentAction,
    expected_version: int,
    owner_ref: str | None,
    reason: str,
) -> ReviewAssignmentCommand:
    return ReviewAssignmentCommand(
        command_id=command_id,
        action=action,
        expected_version=expected_version,
        owner_ref=owner_ref,
        reason=reason,
    )


def _session(
    signal: GovernanceSignal,
    assignment: GovernanceReviewAssignment,
    *,
    existing_event: GovernanceReviewAssignmentEvent | None = None,
) -> AsyncSession:
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=(
            _Result(row=(signal, assignment)),
            _Result(scalar=existing_event),
        )
    )
    session.flush = AsyncMock()
    return cast(AsyncSession, cast(object, session))


class ReviewAssignmentServiceTests(unittest.TestCase):
    def test_assign_escalate_release_persist_versioned_events(self) -> None:
        signal = _signal()
        assignment = _assignment(signal)
        assign = _command(
            command_id="assign-1",
            action=ReviewAssignmentAction.ASSIGN,
            expected_version=1,
            owner_ref="support-ops",
            reason="Route the ticket-pressure review.",
        )
        with patch(
            "cygnus.governance.review_assignments.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            assigned = asyncio.run(
                apply_review_assignment_command(
                    _session(signal, assignment),
                    signal_ref=signal.signal_ref,
                    command=assign,
                    actor_id=_ACTOR_ID,
                )
            )
        assert assigned is not None
        self.assertEqual(assignment.lifecycle_state, "assigned")
        self.assertEqual(assignment.owner_ref, "support-ops")
        self.assertEqual(assigned.event.event_type, "assigned")
        self.assertEqual(assigned.event.sequence, 2)

        escalate = _command(
            command_id="escalate-1",
            action=ReviewAssignmentAction.ESCALATE,
            expected_version=2,
            owner_ref="escalation-lead",
            reason="Incident pressure requires lead intervention.",
        )
        with patch(
            "cygnus.governance.review_assignments.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            escalated = asyncio.run(
                apply_review_assignment_command(
                    _session(signal, assignment),
                    signal_ref=signal.signal_ref,
                    command=escalate,
                    actor_id=_ACTOR_ID,
                )
            )
        assert escalated is not None
        self.assertEqual(assignment.lifecycle_state, "escalated")
        self.assertEqual(assignment.escalation_reason, escalate.reason)
        self.assertEqual(escalated.event.sequence, 3)

        release = _command(
            command_id="release-1",
            action=ReviewAssignmentAction.RELEASE,
            expected_version=3,
            owner_ref=None,
            reason="Return the resolved item to the unassigned pool.",
        )
        with patch(
            "cygnus.governance.review_assignments.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            released = asyncio.run(
                apply_review_assignment_command(
                    _session(signal, assignment),
                    signal_ref=signal.signal_ref,
                    command=release,
                    actor_id=_ACTOR_ID,
                )
            )
        assert released is not None
        self.assertEqual(assignment.lifecycle_state, "unassigned")
        self.assertIsNone(assignment.owner_ref)
        self.assertIsNone(assignment.escalation_reason)
        self.assertEqual(released.event.event_type, "released")
        self.assertEqual(released.event.sequence, 4)

    def test_exact_command_replay_returns_original_transition_snapshot(self) -> None:
        signal = _signal()
        assignment = _assignment(signal)
        command = _command(
            command_id="assign-replay",
            action=ReviewAssignmentAction.ASSIGN,
            expected_version=1,
            owner_ref="support-ops",
            reason="Assign the governed review.",
        )
        with patch(
            "cygnus.governance.review_assignments.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            first = asyncio.run(
                apply_review_assignment_command(
                    _session(signal, assignment),
                    signal_ref=signal.signal_ref,
                    command=command,
                    actor_id=_ACTOR_ID,
                )
            )
            assert first is not None
            replay = asyncio.run(
                apply_review_assignment_command(
                    _session(signal, assignment, existing_event=first.event),
                    signal_ref=signal.signal_ref,
                    command=command,
                    actor_id=_ACTOR_ID,
                )
            )
        assert replay is not None
        payload = replay.to_dict()
        self.assertTrue(payload["replayed"])
        assignment_payload = cast(dict[str, object], payload["assignment"])
        event_payload = cast(dict[str, object], payload["event"])
        self.assertEqual(assignment_payload["version"], 2)
        self.assertEqual(assignment_payload["owner_ref"], "support-ops")
        self.assertEqual(
            event_payload["trace_ref"], f"review-assignment-event:{first.event.id}"
        )

    def test_governed_snapshot_keeps_suggested_reviewer_separate_from_owner(
        self,
    ) -> None:
        signal = _signal()
        assignment = _assignment(signal)
        assignment.lifecycle_state = "escalated"
        assignment.owner_ref = "tier-2-lead"
        assignment.escalation_reason = "Escalated for incident pressure."
        assignment.version = 3
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        sources_result = MagicMock()
        sources_result.scalars.return_value.all.return_value = ()
        session = MagicMock()
        session.execute = AsyncMock(side_effect=(count_result, sources_result))

        with (
            patch(
                "cygnus.runtime.routers.governance.dependencies.load_governance_knowledge_snapshot",
                AsyncMock(
                    return_value=SubstrateKnowledgeSnapshot(objects=(), evidence=())
                ),
            ),
            patch(
                "cygnus.runtime.routers.governance.dependencies.list_governance_signals",
                AsyncMock(return_value=(signal,)),
            ),
            patch(
                "cygnus.runtime.routers.governance.dependencies.load_review_assignments",
                AsyncMock(return_value={signal.id: assignment}),
            ),
            patch(
                "cygnus.runtime.routers.governance.dependencies.load_audience_conflict_provider_data",
                AsyncMock(return_value=SimpleNamespace(conflicts=())),
            ),
        ):
            snapshot = asyncio.run(
                get_governance_read_snapshot(
                    current_user=cast(
                        Employee,
                        cast(object, SimpleNamespace(role="admin")),
                    ),
                    db=cast(AsyncSession, cast(object, session)),
                )
            )

        bundle = snapshot.review_bundles[0]
        self.assertEqual(bundle.proposal.review_owner, "support-ops")
        self.assertEqual(bundle.signal.queue_owner, "tier-2-lead")
        assert bundle.owner_state is not None
        self.assertEqual(bundle.owner_state.value, "escalated")
        self.assertEqual(bundle.assignment_version, 3)
        self.assertEqual(snapshot.pressure_records[0].queue_owner, "tier-2-lead")

    def test_stale_version_and_invalid_noop_are_conflicts(self) -> None:
        signal = _signal()
        assignment = _assignment(signal)
        stale = _command(
            command_id="stale-1",
            action=ReviewAssignmentAction.ASSIGN,
            expected_version=2,
            owner_ref="support-ops",
            reason="Stale client write.",
        )
        with patch(
            "cygnus.governance.review_assignments.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(ReviewAssignmentConflict):
                _ = asyncio.run(
                    apply_review_assignment_command(
                        _session(signal, assignment),
                        signal_ref=signal.signal_ref,
                        command=stale,
                        actor_id=_ACTOR_ID,
                    )
                )

        assignment.lifecycle_state = "assigned"
        assignment.owner_ref = "support-ops"
        same_owner = _command(
            command_id="same-owner",
            action=ReviewAssignmentAction.ASSIGN,
            expected_version=1,
            owner_ref="support-ops",
            reason="No-op reassignment.",
        )
        with patch(
            "cygnus.governance.review_assignments.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(ReviewAssignmentConflict):
                _ = asyncio.run(
                    apply_review_assignment_command(
                        _session(signal, assignment),
                        signal_ref=signal.signal_ref,
                        command=same_owner,
                        actor_id=_ACTOR_ID,
                    )
                )

    def test_reason_bound_and_actor_retention_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "reason must be at most"):
            _ = ReviewAssignmentCommand(
                command_id="oversized-reason",
                action=ReviewAssignmentAction.ASSIGN,
                expected_version=1,
                owner_ref="support-ops",
                reason="x" * (REVIEW_ASSIGNMENT_REASON_MAX_LENGTH + 1),
            )

        actor_column = GovernanceReviewAssignmentEvent.__table__.c.actor_id
        self.assertFalse(actor_column.nullable)
        self.assertEqual(tuple(actor_column.foreign_keys), ())


class ReviewAssignmentApiTests(unittest.TestCase):
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

    def test_command_endpoint_returns_durable_assignment_contract(self) -> None:
        assert self.client is not None
        result = SimpleNamespace(
            to_dict=lambda: {
                "assignment": {
                    "id": str(uuid.uuid4()),
                    "signal_ref": "ticket:billing-verification:w32",
                    "owner_ref": "support-ops",
                    "lifecycle_state": "assigned",
                    "escalation_reason": None,
                    "version": 2,
                    "trace_ref": "review-assignment:assignment-id",
                    "persisted": True,
                    "created_at": _NOW.isoformat(),
                    "updated_at": _NOW.isoformat(),
                },
                "event": {
                    "id": str(uuid.uuid4()),
                    "event_type": "assigned",
                    "from_state": "unassigned",
                    "to_state": "assigned",
                    "actor_id": str(_ACTOR_ID),
                    "owner_ref": "support-ops",
                    "reason": "Route the review.",
                    "sequence": 2,
                    "trace_ref": "review-assignment-event:event-id",
                    "persisted": True,
                    "occurred_at": _NOW.isoformat(),
                },
                "replayed": False,
            }
        )
        with patch(
            "cygnus.runtime.routers.governance.assignments.apply_review_assignment_command",
            AsyncMock(return_value=result),
        ) as apply_command:
            response = self.client.post(
                "/api/review-assignments/ticket:billing-verification:w32/commands",
                json={
                    "command_id": "assign-api-1",
                    "action": "assign",
                    "owner_ref": "support-ops",
                    "reason": "Route the review.",
                    "expected_version": 1,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["assignment"]["persisted"])
        self.assertEqual(response.json()["assignment"]["lifecycle_state"], "assigned")
        assert apply_command.await_args is not None
        domain_command = cast(
            ReviewAssignmentCommand,
            apply_command.await_args.kwargs["command"],
        )
        self.assertEqual(domain_command.action, ReviewAssignmentAction.ASSIGN)
        self.assertEqual(domain_command.expected_version, 1)

    def test_command_endpoint_preserves_not_found_conflict_and_validation(self) -> None:
        assert self.client is not None
        payload = {
            "command_id": "assign-api-2",
            "action": "assign",
            "owner_ref": "support-ops",
            "reason": "Route the review.",
            "expected_version": 1,
        }
        with patch(
            "cygnus.runtime.routers.governance.assignments.apply_review_assignment_command",
            AsyncMock(return_value=None),
        ):
            missing = self.client.post(
                "/api/review-assignments/missing/commands",
                json=payload,
            )
        self.assertEqual(missing.status_code, 404)

        with patch(
            "cygnus.runtime.routers.governance.assignments.apply_review_assignment_command",
            AsyncMock(side_effect=ReviewAssignmentConflict("stale version")),
        ):
            conflict = self.client.post(
                "/api/review-assignments/existing/commands",
                json=payload,
            )
        self.assertEqual(conflict.status_code, 409)

        invalid = self.client.post(
            "/api/review-assignments/existing/commands",
            json={**payload, "owner_ref": None},
        )
        self.assertEqual(invalid.status_code, 422)

        oversized = self.client.post(
            "/api/review-assignments/existing/commands",
            json={
                **payload,
                "reason": "x" * (REVIEW_ASSIGNMENT_REASON_MAX_LENGTH + 1),
            },
        )
        self.assertEqual(oversized.status_code, 422)


if __name__ == "__main__":
    unittest.main()
