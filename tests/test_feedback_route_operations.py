from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from cygnus.governance import feedback_operations
from cygnus.governance.feedback_operations import (
    FeedbackRouteOperationsQuery,
    FeedbackRouteWorkerEvent,
    emit_feedback_route_worker_event,
    feedback_route_scope_clause,
    feedback_route_worker_event_fields,
)
from cygnus.governance.feedback_routing import FeedbackRouteKind, FeedbackRouteState
from cygnus.runtime.database.models import (
    Employee,
    EmployeeDepartment,
    GovernanceFeedbackRoute,
)


_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _employee(
    *, role: str, global_role: str, department_id: uuid.UUID | None = None
) -> Employee:
    employee_id = uuid.uuid4()
    employee = Employee(
        id=employee_id,
        name="CYG-120 operator",
        email=f"cyg120-{employee_id}@example.test",
        role=role,
        global_role=global_role,
        is_active=True,
    )
    employee.employee_departments = (
        [
            EmployeeDepartment(
                employee_id=employee_id,
                department_id=department_id,
            )
        ]
        if department_id is not None
        else []
    )
    return employee


class FeedbackRouteOperationsContractTests(unittest.TestCase):
    def test_query_contract_bounds_pagination_and_enums(self) -> None:
        query = FeedbackRouteOperationsQuery(
            route_state=FeedbackRouteState.QUEUED,
            route_kind=FeedbackRouteKind.REVIEW,
            page=2,
            page_size=100,
        )

        self.assertIs(query.route_state, FeedbackRouteState.QUEUED)
        self.assertIs(query.route_kind, FeedbackRouteKind.REVIEW)
        self.assertEqual(query.page, 2)
        self.assertEqual(query.page_size, 100)
        with self.assertRaises(ValueError):
            _ = FeedbackRouteOperationsQuery(page=0)
        with self.assertRaises(ValueError):
            _ = FeedbackRouteOperationsQuery(page_size=0)
        with self.assertRaises(ValueError):
            _ = FeedbackRouteOperationsQuery(page_size=101)

    def test_scope_clause_is_sql_first_and_admin_bypasses_it(self) -> None:
        department_id = uuid.uuid4()
        scoped_user = _employee(
            role="employee",
            global_role="viewer",
            department_id=department_id,
        )
        clause = feedback_route_scope_clause(scoped_user)
        self.assertIsNotNone(clause)
        if clause is None:
            raise AssertionError("scoped user unexpectedly bypassed SQL scope")
        statement = select(GovernanceFeedbackRoute.id).where(clause)
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("governance_feedback_signals", sql)
        self.assertIn("wiki_pages", sql)
        self.assertIn("wiki_page_drafts", sql)
        self.assertIn("EXISTS", sql)
        self.assertIn(str(department_id), sql)
        self.assertIsNone(
            feedback_route_scope_clause(_employee(role="admin", global_role="admin"))
        )

    def test_worker_event_fields_are_allowlisted_and_payload_free(self) -> None:
        route_id = uuid.uuid4()
        outcome_id = uuid.uuid4()
        fields = feedback_route_worker_event_fields(
            event=FeedbackRouteWorkerEvent.FAILED,
            route_id=route_id,
            route_kind=FeedbackRouteKind.REFRESH,
            transition="running_to_failed",
            attempt_count=3,
            duration_ms=17,
            outcome_signal_id=outcome_id,
            terminal_reason="retry_exhausted",
            exception_class="RuntimeError",
        )

        self.assertEqual(
            set(fields),
            {
                "event",
                "route_id",
                "route_kind",
                "transition",
                "attempt_count",
                "duration_ms",
                "outcome_signal_ref",
                "terminal_reason",
                "exception_class",
            },
        )
        self.assertEqual(fields["route_id"], str(route_id))
        self.assertEqual(
            fields["outcome_signal_ref"], f"governance-signal:{outcome_id}"
        )
        encoded = repr(fields)
        for forbidden in (
            "last_error",
            "source_context_ref",
            "notes",
            "customer content",
            "route_state",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_worker_event_logger_binds_only_normalized_fields(self) -> None:
        route_id = uuid.uuid4()
        with patch.object(feedback_operations.logger, "bind") as bind:
            fields = emit_feedback_route_worker_event(
                event=FeedbackRouteWorkerEvent.RETRY_SCHEDULED,
                route_id=route_id,
                route_kind=FeedbackRouteKind.REVIEW,
                transition="running_to_queued",
                attempt_count=1,
                duration_ms=4,
                exception_class="TimeoutError",
            )

        bind.assert_called_once_with(**fields)
        bind.return_value.log.assert_called_once_with(
            "WARNING", "feedback_route_worker_event"
        )

    def test_worker_event_contract_rejects_invalid_identity_and_negative_values(
        self,
    ) -> None:
        route_id = uuid.uuid4()
        with self.assertRaises(ValueError):
            _ = feedback_route_worker_event_fields(
                event=FeedbackRouteWorkerEvent.CLAIMED,
                route_id="not-a-uuid",
                route_kind=FeedbackRouteKind.REVIEW,
                transition="queued_to_running",
                attempt_count=1,
            )
        with self.assertRaises(ValueError):
            _ = feedback_route_worker_event_fields(
                event=FeedbackRouteWorkerEvent.CLAIMED,
                route_id=route_id,
                route_kind=FeedbackRouteKind.REVIEW,
                transition="queued_to_running",
                attempt_count=-1,
            )
        with self.assertRaises(ValueError):
            _ = feedback_route_worker_event_fields(
                event=FeedbackRouteWorkerEvent.CLAIMED,
                route_id=route_id,
                route_kind=FeedbackRouteKind.REVIEW,
                transition="queued_to_running",
                attempt_count=1,
                duration_ms=-1,
            )


if __name__ == "__main__":
    unittest.main()
