from __future__ import annotations
from typing import Any

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient
from httpx import Response

from cygnus.governance.signals import GovernanceSignalConflict
from cygnus.runtime.database import get_db
from cygnus.runtime.main import app
from cygnus.runtime.routers.governance import ticket_imports as ticket_imports_router
from cygnus.runtime.services.auth_service import require_admin


_FIXTURE = Path(__file__).parent / "fixtures" / "resolved_ticket_export.csv"


class TicketImportApiTests(unittest.TestCase):
    def __init__(self, method_name: str = "runTest") -> None:
        super().__init__(method_name)
        self.startup_patches: list[Any] = []
        self.client = TestClient(app)
        self.admin_id = uuid.UUID(int=0)
        self.admin = SimpleNamespace(id=self.admin_id, role="admin")

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
        self.admin_id = uuid.uuid4()
        self.admin = SimpleNamespace(id=self.admin_id, role="admin")
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        for patcher in reversed(self.startup_patches):
            patcher.stop()

    def enable_admin(self) -> None:
        app.dependency_overrides[require_admin] = lambda: self.admin

    def _request(self, content: bytes, **data: str) -> Response:
        return self.client.post(
            "/api/governance/ticket-imports",
            files={
                "file": (
                    "resolved-tickets.csv",
                    content,
                    "text/csv",
                )
            },
            data={
                "source_ref": "sanitized-helpdesk-export/2026-w32",
                "export_format": "csv",
                **data,
            },
        )

    def test_import_is_admin_gated(self) -> None:
        response = self._request(_FIXTURE.read_bytes())
        self.assertEqual(response.status_code, 401)

    def test_import_returns_plan_and_persists_only_qualifying_signals(self) -> None:
        self.enable_admin()
        result = {"record_count": 4, "persisted_signal_count": 1}
        with patch.object(
            ticket_imports_router,
            "import_resolved_ticket_export",
            AsyncMock(return_value=SimpleNamespace(to_dict=lambda: result)),
        ) as import_export:
            response = self._request(
                _FIXTURE.read_bytes(),
                minimum_cluster_size="3",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), result)
        import_export.assert_awaited_once()
        import_call = import_export.await_args
        assert import_call is not None
        self.assertEqual(
            import_call.kwargs["source_ref"],
            "sanitized-helpdesk-export/2026-w32",
        )
        self.assertEqual(import_call.kwargs["minimum_cluster_size"], 3)
        self.assertEqual(import_call.kwargs["created_by_id"], self.admin_id)
        self.assertEqual(import_call.kwargs["export_format"].value, "csv")
        self.assertEqual(import_call.args[1], _FIXTURE.read_bytes())

    def test_invalid_export_returns_bounded_contract_diagnostics(self) -> None:
        self.enable_admin()
        response = self._request(b'{"ticket_id":"missing-fields"}\n')

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail["error"], "invalid_resolved_ticket_export")
        self.assertGreater(detail["total_errors"], 0)
        self.assertTrue(detail["diagnostics"])

    def test_reusing_snapshot_ref_for_different_truth_returns_conflict(self) -> None:
        self.enable_admin()
        with patch.object(
            ticket_imports_router,
            "import_resolved_ticket_export",
            AsyncMock(
                side_effect=GovernanceSignalConflict(
                    "signal_ref is already bound to a different ticket snapshot"
                )
            ),
        ):
            response = self._request(_FIXTURE.read_bytes())

        self.assertEqual(response.status_code, 409)
        self.assertIn("different ticket snapshot", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
