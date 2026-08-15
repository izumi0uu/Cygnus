"""CYG-141 authenticated REST feedback bridge tests.

Covers: authentication is required; the session contract major is required
and echoed; incompatible versions fail before work; the bridge uses the same
shared structured result as MCP; and the caller-owned transaction commits
only on persisted non-replay results — exactly like the MCP path, with no
duplicated business logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient

from cygnus.integrations.governed_feedback_tools import GovernedFeedbackTools
from cygnus.runtime.database import get_db
from cygnus.runtime.main import app
from cygnus.runtime.services.auth_service import get_current_user

_CONTRACT_HEADER = "X-Cygnus-Session-Contract-Version"

_SUCCESS_PAYLOAD = {
    "status": "success",
    "summary": "Consumption feedback recorded durably; no routing was queued.",
    "data": {"signal_id": str(uuid.uuid4()), "replayed": False},
    "signal_id": str(uuid.uuid4()),
    "command_id": "feedback:rest-1",
    "replayed": False,
    "signal_type": "low_rating",
    "object_id": None,
    "draft_id": None,
    "route_id": None,
    "route_ref": None,
    "route_kind": None,
    "route_state": None,
    "routing_state": "recorded_only",
    "review_queued": False,
    "refresh_queued": False,
    "trace_ref": "feedback-signal:test",
    "persisted": True,
    "rehearsal": False,
    "warnings": [],
    "errors": [],
}


class SessionBridgeFeedbackApiTests(unittest.TestCase):
    client: TestClient = cast(TestClient, None)
    db: Any = cast(Any, None)
    employee: SimpleNamespace = cast(SimpleNamespace, None)

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
        self.db = AsyncMock()
        self.employee = SimpleNamespace(
            id=uuid.uuid4(),
            role="employee",
            is_admin=False,
            permissions=(),
        )
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.employee

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        for patcher in reversed(self.startup_patches):
            patcher.stop()

    def _request(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "command_id": "feedback:rest-1",
            "signal_type": "low_rating",
            "audience_context": {"visibility": "internal"},
        }
        body.update(overrides)
        return body

    def test_feedback_requires_authentication(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        response = self.client.post(
            "/api/session-bridge/feedback",
            headers={_CONTRACT_HEADER: "1.0"},
            json=self._request(),
        )
        self.assertEqual(response.status_code, 401)

    def test_contract_major_is_required_and_incompatible_versions_fail_before_work(
        self,
    ) -> None:
        missing = self.client.post(
            "/api/session-bridge/feedback",
            json=self._request(),
        )
        self.assertEqual(missing.status_code, 400)

        incompatible = self.client.post(
            "/api/session-bridge/feedback",
            headers={_CONTRACT_HEADER: "2.0"},
            json=self._request(),
        )
        self.assertEqual(incompatible.status_code, 409)
        self.assertEqual(
            incompatible.json()["detail"]["status"],
            "incompatible_contract_version",
        )

    def test_invalid_body_is_rejected_before_the_business_handler(self) -> None:
        with patch.object(
            GovernedFeedbackTools,
            "record_feedback_signal",
            new=AsyncMock(),
        ) as record:
            response = self.client.post(
                "/api/session-bridge/feedback",
                headers={_CONTRACT_HEADER: "1.0"},
                json=self._request(signal_type="not_a_signal"),
            )

        self.assertEqual(response.status_code, 422)
        record.assert_not_awaited()

    def test_success_commits_once_and_echoes_contract_version(self) -> None:
        with patch.object(
            GovernedFeedbackTools,
            "record_feedback_signal",
            new=AsyncMock(return_value=dict(_SUCCESS_PAYLOAD)),
        ) as record:
            response = self.client.post(
                "/api/session-bridge/feedback",
                headers={_CONTRACT_HEADER: "1.0"},
                json=self._request(
                    audience_context={
                        "visibility": "external",
                        "product_line": "billing",
                    }
                ),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertTrue(payload["persisted"])
        self.db.commit.assert_awaited_once()
        record.assert_awaited_once()
        record.assert_awaited_once_with(
            command_id="feedback:rest-1",
            signal_type="low_rating",
            audience_context={"visibility": "external", "product_line": "billing"},
        )

    def test_exact_replay_returns_stored_result_without_committing(self) -> None:
        replayed = dict(_SUCCESS_PAYLOAD)
        replayed["replayed"] = True
        replayed["summary"] = "Feedback command replayed from durable routing truth."
        with patch.object(
            GovernedFeedbackTools,
            "record_feedback_signal",
            new=AsyncMock(return_value=replayed),
        ) as record:
            response = self.client.post(
                "/api/session-bridge/feedback",
                headers={_CONTRACT_HEADER: "1.0"},
                json=self._request(command_id="feedback:rest-replay-1"),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["replayed"])
        self.assertEqual(payload["contract_version"], "1.0")
        self.db.commit.assert_not_awaited()
        record.assert_awaited_once()

    def test_conflict_never_commits(self) -> None:
        conflict = {
            "status": "conflict",
            "summary": "Feedback command ID is already bound to different input.",
            "data": {},
            "warnings": [],
            "errors": ["idempotency_conflict"],
        }
        with patch.object(
            GovernedFeedbackTools,
            "record_feedback_signal",
            new=AsyncMock(return_value=conflict),
        ) as record:
            response = self.client.post(
                "/api/session-bridge/feedback",
                headers={_CONTRACT_HEADER: "1.0"},
                json=self._request(command_id="feedback:rest-conflict-1"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "conflict")
        self.assertEqual(
            response.json()["errors"],
            ["idempotency_conflict"],
        )
        self.db.commit.assert_not_awaited()
        record.assert_awaited_once()

    def test_draft_id_accepts_only_uuid_shape(self) -> None:
        with patch.object(
            GovernedFeedbackTools,
            "record_feedback_signal",
            new=AsyncMock(return_value=dict(_SUCCESS_PAYLOAD)),
        ) as record:
            invalid = self.client.post(
                "/api/session-bridge/feedback",
                headers={_CONTRACT_HEADER: "1.0"},
                json=self._request(draft_id="not-a-uuid"),
            )
        self.assertEqual(invalid.status_code, 422)
        record.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
