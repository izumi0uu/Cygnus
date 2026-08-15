from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient

from cygnus.governance.feedback_operations import FeedbackRouteOperationsQuery
from cygnus.governance.feedback_routing import FeedbackRouteKind, FeedbackRouteState
from cygnus.runtime.database import get_db
from cygnus.runtime.main import app
from cygnus.runtime.routers.governance import feedback_routes as feedback_routes_router
from cygnus.runtime.services.auth_service import get_current_user


class _Projection:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, object]:
        return dict(self._payload)


class FeedbackRouteOperationsApiTests(unittest.TestCase):
    startup_patches: list[Any] = cast(list[Any], None)
    client: TestClient = cast(TestClient, None)
    operator: SimpleNamespace = cast(SimpleNamespace, None)

    def setUp(self) -> None:
        self.startup_patches = [
            patch(
                "cygnus.runtime.main.seed_default_admin",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.services.storage_service.storage_service.ensure_bucket",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.bootstrap.seed_builtin_skills.seed_builtin_skills",
                AsyncMock(return_value=None),
            ),
        ]
        for patcher in self.startup_patches:
            patcher.start()
        self.client = TestClient(app)
        self.operator = SimpleNamespace(id=uuid.uuid4(), role="employee")
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        for patcher in reversed(self.startup_patches):
            patcher.stop()

    def enable_operator(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: self.operator

    def test_operations_reads_require_authentication(self) -> None:
        route_id = uuid.uuid4()
        self.assertEqual(
            self.client.get("/api/governance/feedback-routes").status_code,
            401,
        )
        self.assertEqual(
            self.client.get(f"/api/governance/feedback-routes/{route_id}").status_code,
            401,
        )

    def test_list_passes_typed_filters_and_returns_persisted_projection(self) -> None:
        self.enable_operator()
        projection = _Projection(
            {
                "items": [],
                "summary": {"total": 0},
                "total": 0,
                "page": 2,
                "page_size": 10,
                "observation": {
                    "state": "ready",
                    "observed_count": 0,
                    "reason": "durable_feedback_route_operations",
                },
                "persisted": True,
                "rehearsal": False,
            }
        )
        with patch.object(
            feedback_routes_router,
            "list_feedback_route_operations",
            AsyncMock(return_value=projection),
        ) as list_routes:
            response = self.client.get(
                "/api/governance/feedback-routes"
                "?route_state=queued&route_kind=review&page=2&page_size=10"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["persisted"])
        self.assertFalse(response.json()["rehearsal"])
        awaited = list_routes.await_args
        if awaited is None:
            raise AssertionError("operations service was not awaited")
        query = cast(FeedbackRouteOperationsQuery, awaited.kwargs["query"])
        self.assertIs(query.route_state, FeedbackRouteState.QUEUED)
        self.assertIs(query.route_kind, FeedbackRouteKind.REVIEW)
        self.assertEqual(query.page, 2)
        self.assertEqual(query.page_size, 10)
        self.assertIs(awaited.kwargs["current_user"], self.operator)

    def test_invalid_filters_are_rejected_before_service_read(self) -> None:
        self.enable_operator()
        with patch.object(
            feedback_routes_router,
            "list_feedback_route_operations",
            AsyncMock(),
        ) as list_routes:
            response = self.client.get(
                "/api/governance/feedback-routes?route_state=unknown"
            )

        self.assertEqual(response.status_code, 422)
        list_routes.assert_not_awaited()

    def test_hidden_and_missing_drilldowns_share_not_found_response(self) -> None:
        self.enable_operator()
        hidden_id = uuid.uuid4()
        missing_id = uuid.uuid4()
        with patch.object(
            feedback_routes_router,
            "get_feedback_route_operation",
            AsyncMock(return_value=None),
        ) as get_route:
            hidden = self.client.get(f"/api/governance/feedback-routes/{hidden_id}")
            missing = self.client.get(f"/api/governance/feedback-routes/{missing_id}")

        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(hidden.json(), missing.json())
        self.assertNotIn(str(hidden_id), hidden.text)
        self.assertEqual(get_route.await_count, 2)

    def test_visible_drilldown_returns_trace_projection(self) -> None:
        self.enable_operator()
        route_id = uuid.uuid4()
        projection = _Projection(
            {
                "route": {"route_id": str(route_id)},
                "feedback": {"feedback_ref": "feedback-signal:visible"},
                "outcome": {"signal_ref": "feedback-route:visible"},
                "review_assignment": {"trace_ref": "review-assignment:visible"},
                "audit_traces": [{"trace_ref": "audit-log:visible"}],
                "persisted": True,
                "rehearsal": False,
            }
        )
        with patch.object(
            feedback_routes_router,
            "get_feedback_route_operation",
            AsyncMock(return_value=projection),
        ):
            response = self.client.get(f"/api/governance/feedback-routes/{route_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["route"]["route_id"], str(route_id))
        self.assertTrue(response.json()["persisted"])


if __name__ == "__main__":
    unittest.main()
