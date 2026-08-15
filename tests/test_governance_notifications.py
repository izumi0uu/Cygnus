from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast, final
import unittest
from unittest.mock import AsyncMock
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee, Notification
from cygnus.runtime.routers import notifications as notification_router
from cygnus.runtime.services.auth_service import get_current_user

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OTHER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_NOTIFICATION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _user(user_id: uuid.UUID = _USER_ID) -> Employee:
    return cast(
        Employee,
        cast(
            object,
            SimpleNamespace(
                id=user_id,
                name="Notification reader",
                email="reader@example.test",
                role="employee",
                global_role="viewer",
            ),
        ),
    )


def _notification(
    *,
    recipient_id: uuid.UUID = _USER_ID,
    read_at: datetime | None = None,
) -> Notification:
    return Notification(
        id=_NOTIFICATION_ID,
        recipient_id=recipient_id,
        type="wiki_draft.submitted",
        subject="New draft",
        body="A governed draft needs review.",
        target_type="wiki_draft",
        target_id="draft-1",
        actor_id=_OTHER_USER_ID,
        read_at=read_at,
        created_at=_NOW,
    )


@final
class _ScalarRows:
    def __init__(self, rows: list[Notification]) -> None:
        self.rows = rows

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[Notification]:
        return self.rows


@final
class _SingleResult:
    def __init__(self, value: Notification | None = None, rowcount: int = 0) -> None:
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> Notification | None:
        return self.value

    def scalar(self) -> int:
        return self.rowcount


@final
class NotificationApiTests(unittest.TestCase):
    def api_client(
        self, *, db: AsyncMock | None = None
    ) -> tuple[TestClient, AsyncMock]:
        app = FastAPI()
        app.include_router(notification_router.router)
        fake_db = db or AsyncMock()
        app.dependency_overrides[get_current_user] = lambda: _user()
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)
        self.addCleanup(client.close)
        self.addCleanup(app.dependency_overrides.clear)
        return client, fake_db

    def test_inbox_requires_authentication(self) -> None:
        app = FastAPI()
        app.include_router(notification_router.router)
        with TestClient(app) as client:
            self.assertEqual(client.get("/notifications").status_code, 401)

    def test_list_filters_inside_recipient_scope_and_projects_durable_state(
        self,
    ) -> None:
        fake_db = AsyncMock()
        fake_db.execute.return_value = _ScalarRows([_notification()])
        client, _ = self.api_client(db=fake_db)

        response = client.get("/notifications?lifecycle_state=unread&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["trace_ref"], f"notification:{_NOTIFICATION_ID}")
        self.assertEqual(payload[0]["lifecycle_state"], "unread")
        self.assertTrue(payload[0]["persisted"])
        statement = fake_db.execute.await_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("notifications.recipient_id", sql)
        self.assertIn("notifications.read_at IS NULL", sql)

    def test_mark_read_hides_other_recipient_records(self) -> None:
        fake_db = AsyncMock()
        fake_db.execute.return_value = _SingleResult(None)
        client, _ = self.api_client(db=fake_db)

        response = client.post(f"/notifications/{_NOTIFICATION_ID}/read")

        self.assertEqual(response.status_code, 404)
        statement = fake_db.execute.await_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("notifications.recipient_id", sql)

    def test_mark_read_is_idempotent_and_persists_transition(self) -> None:
        fake_db = AsyncMock()
        notification = _notification()
        fake_db.execute.return_value = _SingleResult(notification)
        client, _ = self.api_client(db=fake_db)

        response = client.post(f"/notifications/{_NOTIFICATION_ID}/read")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lifecycle_state"], "read")
        self.assertTrue(response.json()["persisted"])
        self.assertIsNotNone(notification.read_at)
        fake_db.commit.assert_awaited_once()
        fake_db.refresh.assert_awaited_once_with(notification)

    def test_mark_all_read_reports_durable_lifecycle_transition(self) -> None:
        fake_db = AsyncMock()
        fake_db.execute.return_value = _SingleResult(rowcount=3)
        client, _ = self.api_client(db=fake_db)

        response = client.post("/notifications/read-all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"updated": 3, "lifecycle_state": "read", "persisted": True},
        )
        fake_db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
