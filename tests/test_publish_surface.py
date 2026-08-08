from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
import uuid
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain import AudienceFilter, KnowledgeObjectType, Visibility

from cygnus.publish import (
    PublishActionType,
    PublishBinding,
    PublishPreviewCandidate,
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
)
from cygnus.runtime.database.models import Employee, GovernanceSignal
from cygnus.runtime.routers.governance import publish as publish_router


_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def _persisted_signal() -> GovernanceSignal:
    return GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref="ticket:billing-policy:w32",
        signal_type="ticket_cluster",
        object_ref="ko-billing-policy",
        title="Billing policy pressure",
        object_type="answer_card",
        page_id=uuid.uuid4(),
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
        summary="Repeated tickets expose a governed knowledge gap.",
        reason="The recurring intent crossed the review threshold.",
        evidence_excerpt="Agents reconstruct the same policy sequence.",
        queue_owner="support-ops",
        status="active",
        observed_at=_NOW,
        resolved_at=None,
        created_by_id=uuid.uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


def _persisted_candidate() -> PublishPreviewCandidate:
    audience = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("enterprise",),
        regions=("eu",),
    )
    return PublishPreviewCandidate(
        object_id="ko-billing-policy",
        object_type=KnowledgeObjectType.ANSWER_CARD,
        title="Billing policy pressure",
        action_type=PublishActionType.PUBLISH,
        target_audiences=(audience,),
        target_channels=("help_center",),
        target_bindings=(
            PublishBinding(audience_filter=audience, channel="help_center"),
        ),
    )

class PublishSurfaceTests(unittest.TestCase):
    def test_default_surface_selects_top_queue_item_and_exposes_blast_radius(self) -> None:
        payload = get_pressure_intake_publish_preview_surface().to_dict()

        self.assertEqual(payload["surface_id"], "publish-preview")
        self.assertEqual(payload["selected_card"]["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_preview"]["action_type"], "restrict")
        self.assertIn("channel_gate_matrix", payload["selected_preview"])
        self.assertIn("audience_scope", payload["selected_preview"])
        self.assertIn("available_commands", payload)
        self.assertEqual([preset["command_key"] for preset in payload["action_presets"]], ["restrict_publish", "hold_external"])
        self.assertIsNone(payload["selected_action"])
        self.assertIsNone(payload["action_echo"])
        self.assertGreaterEqual(payload["situation_frame"]["blocked_paths"], 1)

    def test_specific_object_ref_exposes_granular_governance_actions(self) -> None:
        payload = get_pressure_intake_publish_preview_surface("refund-enterprise-rewrite").to_dict()

        self.assertEqual(payload["selected_preview"]["object_id"], "refund-enterprise-rewrite")
        effects = {impact["effect"] for impact in payload["selected_preview"]["impacts"]}
        self.assertIn("conflict", effects)
        self.assertIn("stopped_exposure", effects)
        self.assertIn("hold_external", payload["available_commands"])
        self.assertIn("split_variant", payload["available_commands"])
        self.assertIn("republish_internal_only", payload["available_commands"])
        self.assertIsNotNone(payload["previous_object_ref"])

    def test_selected_action_returns_action_echo_and_updated_preview(self) -> None:
        payload = get_pressure_intake_publish_preview_surface(
            "refund-enterprise-rewrite",
            action_key="republish_internal_only",
        ).to_dict()

        self.assertEqual(payload["selected_action"], "republish_internal_only")
        self.assertIsNotNone(payload["action_echo"])
        self.assertEqual(payload["action_echo"]["selected_action"], "republish_internal_only")
        self.assertEqual(len(payload["action_echo"]["removed_bindings"]), 2)
        effects = {(impact["audience_label"], impact["channel"]): impact["effect"] for impact in payload["selected_preview"]["impacts"]}
        self.assertEqual(effects[("internal · billing", "copilot")], "continuing_exposure")
        self.assertEqual(effects[("external · billing · free · us", "help_center")], "stopped_exposure")

    def test_propagation_surface_defaults_to_recommended_action_and_status_lanes(self) -> None:
        payload = get_pressure_intake_publish_propagation_surface().to_dict()

        self.assertEqual(payload["surface_id"], "publish-propagation")
        self.assertEqual(payload["selected_card"]["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_action"], "restrict_publish")
        self.assertIn("propagation_ledger", payload)
        self.assertIn("status_lanes", payload)
        lane_counts = {lane["status"]: lane["count"] for lane in payload["status_lanes"]}
        self.assertEqual(lane_counts["failed"], 2)
        self.assertGreaterEqual(lane_counts["pending"], 1)
        self.assertIn("repair_source_chain", payload["propagation_ledger"]["continue_commands"])

    def test_propagation_surface_can_rehearse_customer_facing_hold_path(self) -> None:
        payload = get_pressure_intake_publish_propagation_surface(
            "refund-enterprise-rewrite",
            action_key="hold_external",
        ).to_dict()

        self.assertEqual(payload["selected_action"], "hold_external")
        self.assertEqual(payload["action_echo"]["selected_action"], "hold_external")
        record_map = {
            record["surface_id"]: record
            for record in payload["propagation_ledger"]["records"]
        }
        self.assertEqual(record_map["hold_resolution"]["status"], "manual_action_required")
        self.assertEqual(record_map["feedback"]["status"], "manual_action_required")
        self.assertIn("resolve_surface_hold", payload["propagation_ledger"]["continue_commands"])

    def test_runtime_preview_uses_persisted_binding_candidate(self) -> None:
        signal = _persisted_signal()
        candidate = _persisted_candidate()
        with (
            patch.object(
                publish_router,
                "list_governance_signals",
                AsyncMock(return_value=(signal,)),
            ),
            patch.object(
                publish_router,
                "persisted_publish_candidate_for_signal",
                AsyncMock(return_value=candidate),
            ),
            patch.object(
                publish_router,
                "durable_publish_command_for_signal",
                AsyncMock(return_value=None),
            ),
        ):
            payload = asyncio.run(
                publish_router.publish_preview(
                    object_ref=signal.object_ref,
                    current_user=cast(
                        Employee,
                        cast(object, SimpleNamespace(role="admin")),
                    ),
                    db=cast(AsyncSession, cast(object, AsyncMock())),
                )
            )

        selected = cast(dict[str, object], payload["selected_candidate"])
        bindings = cast(list[dict[str, object]], selected["target_bindings"])
        self.assertTrue(payload["persisted"])
        self.assertFalse(payload["rehearsal"])
        self.assertEqual(bindings[0]["channel"], "help_center")
        self.assertEqual(
            cast(dict[str, object], bindings[0]["audience_filter"])["visibility"],
            "external",
        )

    def test_runtime_preview_withholds_when_binding_truth_is_absent(self) -> None:
        signal = _persisted_signal()
        with (
            patch.object(
                publish_router,
                "list_governance_signals",
                AsyncMock(return_value=(signal,)),
            ),
            patch.object(
                publish_router,
                "persisted_publish_candidate_for_signal",
                AsyncMock(return_value=None),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    publish_router.publish_preview(
                        object_ref=signal.object_ref,
                        current_user=cast(
                            Employee,
                            cast(object, SimpleNamespace(role="admin")),
                        ),
                        db=cast(AsyncSession, cast(object, AsyncMock())),
                    )
                )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("no explicit active audience binding truth", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
