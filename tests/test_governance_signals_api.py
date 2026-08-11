from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient

from cygnus.governance.signals import GovernanceSignalConflict
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import GovernanceSignal
from cygnus.runtime.main import app
from cygnus.runtime.routers.governance import signals as signals_router
from cygnus.runtime.services.auth_service import require_admin
from cygnus.review import PressureSignalType


_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def _signal() -> GovernanceSignal:
    creator_id = uuid.uuid4()
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
        audience_filter={
            "visibility": "internal",
            "brands": [],
            "product_lines": ["billing"],
            "plans": [],
            "regions": [],
            "languages": [],
            "product_versions": [],
        },
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
        created_by_id=creator_id,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


_CREATE_PAYLOAD = {
    "signal_ref": "ticket:billing-verification:w32",
    "signal_type": "ticket_cluster",
    "object_ref": "ko-billing-verification",
    "title": "Billing verification pressure",
    "object_type": "troubleshooting_flow",
    "audience_filter": {
        "visibility": "internal",
        "product_lines": ["billing"],
    },
    "affected_surfaces": ["copilot"],
    "trigger_signals": ["ticket_pressure"],
    "freshness": "fresh",
    "summary": "Repeated tickets show a governed knowledge gap.",
    "reason": "The recurring intent crossed the review threshold.",
    "evidence_excerpt": "Agents reconstruct the same sequence.",
}


class GovernanceSignalsApiTests(unittest.TestCase):
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
        self.admin = SimpleNamespace(id=uuid.uuid4(), role="admin")
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        for patcher in reversed(self.startup_patches):
            patcher.stop()

    def enable_admin(self) -> None:
        app.dependency_overrides[require_admin] = lambda: self.admin

    def test_signal_api_is_admin_gated(self) -> None:
        self.assertEqual(
            self.client.get("/api/governance-signals").status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/governance-signals",
                json=_CREATE_PAYLOAD,
            ).status_code,
            401,
        )

    def test_write_and_list_expose_durable_signal_contract(self) -> None:
        self.enable_admin()
        signal = _signal()
        with (
            patch.object(
                signals_router,
                "create_governance_signal",
                AsyncMock(return_value=signal),
            ),
            patch.object(
                signals_router,
                "list_governance_signals",
                AsyncMock(return_value=(signal,)),
            ),
        ):
            created = self.client.post(
                "/api/governance-signals",
                json=_CREATE_PAYLOAD,
            )
            listed = self.client.get("/api/governance-signals")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["signal_ref"], signal.signal_ref)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        self.assertEqual(
            listed.json()["provider_coverage"]["state"],
            "ready",
        )
        self.assertIn(
            "incident_delta",
            listed.json()["provider_coverage"]["covered_signals"],
        )
        self.assertIn(
            "low_rating",
            listed.json()["provider_coverage"]["covered_signals"],
        )
        self.assertIn(
            "stale_answer",
            listed.json()["provider_coverage"]["covered_signals"],
        )

    def test_write_accepts_structured_evidence_refs(self) -> None:
        self.enable_admin()
        evidence_ref = {
            "evidence_id": "ev-ticket:pilot:1001",
            "source_ref": "pilot/2026-w32#ticket=T-1001",
            "excerpt": "Sanitized resolution excerpt.",
            "observed_at": _NOW.isoformat(),
        }
        signal = _signal()
        signal.evidence_refs = [evidence_ref]
        with patch.object(
            signals_router,
            "create_governance_signal",
            AsyncMock(return_value=signal),
        ) as create_signal:
            response = self.client.post(
                "/api/governance-signals",
                json={**_CREATE_PAYLOAD, "evidence_refs": [evidence_ref]},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["evidence_refs"], [evidence_ref])
        create_call = create_signal.await_args
        assert create_call is not None
        signal_input = create_call.args[1]
        self.assertEqual(signal_input.evidence_refs[0].source_ref, evidence_ref["source_ref"])
    def test_write_rejects_worker_owned_feedback_types_before_service_write(
        self,
    ) -> None:
        self.enable_admin()
        for signal_type in ("low_rating", "stale_answer"):
            with (
                self.subTest(signal_type=signal_type),
                patch.object(
                    signals_router,
                    "create_governance_signal",
                    AsyncMock(),
                ) as create_signal,
            ):
                response = self.client.post(
                    "/api/governance-signals",
                    json={
                        **_CREATE_PAYLOAD,
                        "signal_ref": f"feedback-route:{signal_type}",
                        "signal_type": signal_type,
                    },
                )

            self.assertEqual(response.status_code, 422)
            self.assertIn("worker-owned derived type", response.json()["detail"])
            create_signal.assert_not_awaited()

    def test_read_can_filter_worker_owned_feedback_signal_rows(self) -> None:
        self.enable_admin()
        signal = _signal()
        signal.signal_ref = "feedback-route:low-rating"
        signal.signal_type = "low_rating"
        signal.evidence_source_type = "consumption_feedback"
        with patch.object(
            signals_router,
            "list_governance_signals",
            AsyncMock(return_value=(signal,)),
        ) as list_signals:
            response = self.client.get("/api/governance-signals?signal_type=low_rating")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["signals"][0]["signal_type"], "low_rating")
        self.assertEqual(
            list_signals.await_args.kwargs["signal_types"],
            [PressureSignalType.LOW_RATING],
        )

    def test_write_returns_conflict_for_different_signal_ref_reuse(self) -> None:
        self.enable_admin()
        with patch.object(
            signals_router,
            "create_governance_signal",
            AsyncMock(
                side_effect=GovernanceSignalConflict(
                    "signal_ref is already bound to a different signal"
                )
            ),
        ):
            response = self.client.post(
                "/api/governance-signals",
                json=_CREATE_PAYLOAD,
            )

        self.assertEqual(response.status_code, 409)

    def test_resolve_returns_404_or_the_durable_resolved_row(self) -> None:
        self.enable_admin()
        with patch.object(
            signals_router,
            "resolve_governance_signal",
            AsyncMock(return_value=None),
        ):
            missing = self.client.post("/api/governance-signals/missing/resolve")
        self.assertEqual(missing.status_code, 404)

        signal = _signal()
        signal.status = "resolved"
        signal.resolved_at = _NOW
        signal.version = 2
        with patch.object(
            signals_router,
            "resolve_governance_signal",
            AsyncMock(return_value=signal),
        ):
            resolved = self.client.post(
                f"/api/governance-signals/{signal.signal_ref}/resolve"
            )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], "resolved")
        self.assertEqual(resolved.json()["version"], 2)


if __name__ == "__main__":
    unittest.main()
