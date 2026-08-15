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
from cygnus.evidence import EvidenceSourceType, FreshnessState

from cygnus.publish import (
    PublishActionType,
    PublishBinding,
    PublishPreviewCandidate,
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
    durable_publish_command_for_signal,
    persisted_publish_candidate_for_signal,
)
from cygnus.review import PressureIntakeRecord, PressureSignalType
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


def _feedback_record(
    signal_type: PressureSignalType = PressureSignalType.STALE_ANSWER,
) -> PressureIntakeRecord:
    return PressureIntakeRecord(
        signal_type=signal_type,
        signal_ref=f"feedback-route:{signal_type.value}",
        title=f"{signal_type.value} feedback",
        summary="Consumption feedback requires governed review.",
        source_ref=f"feedback-route:{signal_type.value}",
        source_type=EvidenceSourceType.CONSUMPTION_FEEDBACK,
        audience_filter=AudienceFilter(visibility=Visibility.EXTERNAL),
        object_type=KnowledgeObjectType.ANSWER_CARD,
        affected_surfaces=("feedback", "review_queue"),
        trigger_signals=(signal_type.value,),
        freshness_state=(
            FreshnessState.STALE
            if signal_type is PressureSignalType.STALE_ANSWER
            else FreshnessState.UNKNOWN
        ),
    )


def _preview_surface_payload(
    selected_object_ref: str | None = None,
    *,
    action_key: str | None = None,
) -> dict[str, object]:
    return get_pressure_intake_publish_preview_surface(
        selected_object_ref, action_key=action_key
    ).to_dict()


def _propagation_surface_payload(
    selected_object_ref: str | None = None,
    *,
    action_key: str | None = None,
) -> dict[str, object]:
    return get_pressure_intake_publish_propagation_surface(
        selected_object_ref, action_key=action_key
    ).to_dict()


class PublishSurfaceTests(unittest.TestCase):
    def test_default_surface_selects_top_queue_item_and_exposes_blast_radius(
        self,
    ) -> None:
        payload = _preview_surface_payload()

        self.assertEqual(payload["surface_id"], "publish-preview")
        selected_card = cast(dict[str, object], payload["selected_card"])
        self.assertEqual(selected_card["object_ref"], "incident-sync-eu-billing")
        selected_preview = cast(dict[str, object], payload["selected_preview"])
        self.assertEqual(selected_preview["action_type"], "restrict")
        self.assertIn("channel_gate_matrix", selected_preview)
        self.assertIn("audience_scope", selected_preview)
        self.assertIn("available_commands", payload)
        action_presets = cast(list[dict[str, object]], payload["action_presets"])
        self.assertEqual(
            [cast(str, preset["command_key"]) for preset in action_presets],
            ["restrict_publish", "hold_external"],
        )
        self.assertIsNone(payload["selected_action"])
        self.assertIsNone(payload["action_echo"])
        situation_frame = cast(dict[str, object], payload["situation_frame"])
        self.assertGreaterEqual(cast(int, situation_frame["blocked_paths"]), 1)

    def test_specific_object_ref_exposes_granular_governance_actions(self) -> None:
        payload = _preview_surface_payload("refund-enterprise-rewrite")

        selected_preview = cast(dict[str, object], payload["selected_preview"])
        self.assertEqual(selected_preview["object_id"], "refund-enterprise-rewrite")
        impacts = cast(list[dict[str, object]], selected_preview["impacts"])
        effects: set[str] = {cast(str, impact["effect"]) for impact in impacts}
        self.assertIn("conflict", effects)
        self.assertIn("stopped_exposure", effects)
        available_commands = cast(list[str], payload["available_commands"])
        self.assertIn("hold_external", available_commands)
        self.assertIn("split_variant", available_commands)
        self.assertIn("republish_internal_only", available_commands)
        self.assertIsNotNone(payload["previous_object_ref"])

    def test_selected_action_returns_action_echo_and_updated_preview(self) -> None:
        payload = _preview_surface_payload(
            "refund-enterprise-rewrite",
            action_key="republish_internal_only",
        )

        self.assertEqual(payload["selected_action"], "republish_internal_only")
        self.assertIsNotNone(payload["action_echo"])
        action_echo = cast(dict[str, object], payload["action_echo"])
        self.assertEqual(action_echo["selected_action"], "republish_internal_only")
        self.assertEqual(
            len(cast(list[dict[str, object]], action_echo["removed_bindings"])), 2
        )
        selected_preview = cast(dict[str, object], payload["selected_preview"])
        impacts = cast(list[dict[str, object]], selected_preview["impacts"])
        effects: dict[tuple[str, str], str] = {
            (
                cast(str, impact["audience_label"]),
                cast(str, impact["channel"]),
            ): cast(str, impact["effect"])
            for impact in impacts
        }
        self.assertEqual(
            effects[("internal · billing", "copilot")], "continuing_exposure"
        )
        self.assertEqual(
            effects[("external · billing · free · us", "help_center")],
            "stopped_exposure",
        )

    def test_propagation_surface_defaults_to_recommended_action_and_status_lanes(
        self,
    ) -> None:
        payload = _propagation_surface_payload()

        self.assertEqual(payload["surface_id"], "publish-propagation")
        selected_card = cast(dict[str, object], payload["selected_card"])
        self.assertEqual(selected_card["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_action"], "restrict_publish")
        self.assertIn("propagation_ledger", payload)
        self.assertIn("status_lanes", payload)
        status_lanes = cast(list[dict[str, object]], payload["status_lanes"])
        lane_counts: dict[str, int] = {
            cast(str, lane["status"]): cast(int, lane["count"]) for lane in status_lanes
        }
        self.assertEqual(lane_counts["failed"], 2)
        self.assertGreaterEqual(lane_counts["pending"], 1)
        propagation_ledger = cast(dict[str, object], payload["propagation_ledger"])
        self.assertIn(
            "repair_source_chain",
            cast(list[str], propagation_ledger["continue_commands"]),
        )

    def test_propagation_surface_can_rehearse_customer_facing_hold_path(self) -> None:
        payload = _propagation_surface_payload(
            "refund-enterprise-rewrite",
            action_key="hold_external",
        )

        self.assertEqual(payload["selected_action"], "hold_external")
        action_echo = cast(dict[str, object], payload["action_echo"])
        self.assertEqual(action_echo["selected_action"], "hold_external")
        propagation_ledger = cast(dict[str, object], payload["propagation_ledger"])
        records = cast(list[dict[str, object]], propagation_ledger["records"])
        record_map: dict[str, dict[str, object]] = {
            cast(str, record["surface_id"]): record for record in records
        }
        self.assertEqual(
            record_map["hold_resolution"]["status"], "manual_action_required"
        )
        self.assertEqual(record_map["feedback"]["status"], "manual_action_required")
        self.assertIn(
            "resolve_surface_hold",
            cast(list[str], propagation_ledger["continue_commands"]),
        )

    def test_feedback_derived_signals_never_compile_publish_truth(self) -> None:
        for signal_type in (
            PressureSignalType.LOW_RATING,
            PressureSignalType.STALE_ANSWER,
        ):
            with self.subTest(signal_type=signal_type.value):
                signal = _persisted_signal()
                signal.signal_type = signal_type.value
                signal.evidence_source_type = "consumption_feedback"
                session = AsyncMock()

                command = asyncio.run(
                    durable_publish_command_for_signal(
                        cast(AsyncSession, cast(object, session)),
                        signal=signal,
                    )
                )
                candidate = asyncio.run(
                    persisted_publish_candidate_for_signal(
                        cast(AsyncSession, cast(object, session)),
                        signal=signal,
                    )
                )

                self.assertIsNone(command)
                self.assertIsNone(candidate)
                session.get.assert_not_awaited()
                session.execute.assert_not_awaited()

                with self.assertRaisesRegex(
                    ValueError,
                    rf"signal_type={signal_type.value} is review-only feedback and cannot compile a publish action",
                ):
                    get_pressure_intake_publish_preview_surface(
                        records=(_feedback_record(signal_type),)
                    )
                with self.assertRaisesRegex(
                    ValueError,
                    rf"signal_type={signal_type.value} is review-only feedback and cannot compile a publish action",
                ):
                    get_pressure_intake_publish_preview_surface(
                        records=(_feedback_record(signal_type),),
                        candidate_override=_persisted_candidate(),
                    )

    def test_runtime_preview_skips_feedback_before_selecting_publish_candidate(
        self,
    ) -> None:
        feedback = _persisted_signal()
        feedback.signal_ref = "feedback-route:stale-answer"
        feedback.signal_type = PressureSignalType.STALE_ANSWER.value
        feedback.object_ref = "ko-feedback-answer"
        feedback.title = "Suspected stale answer"
        feedback.evidence_source_type = "consumption_feedback"
        feedback.freshness = "stale"
        feedback.trigger_signals = ["stale_answer"]
        publishable = _persisted_signal()
        candidate = _persisted_candidate()
        candidate_loader = AsyncMock(return_value=candidate)
        command_loader = AsyncMock(return_value=None)
        db = cast(AsyncSession, cast(object, AsyncMock()))

        with (
            patch.object(
                publish_router,
                "list_governance_signals",
                AsyncMock(return_value=(feedback, publishable)),
            ),
            patch.object(
                publish_router,
                "persisted_publish_candidate_for_signal",
                candidate_loader,
            ),
            patch.object(
                publish_router,
                "durable_publish_command_for_signal",
                command_loader,
            ),
        ):
            payload = asyncio.run(
                publish_router.publish_preview(
                    current_user=cast(
                        Employee,
                        cast(object, SimpleNamespace(role="admin")),
                    ),
                    db=db,
                )
            )

        selected_card = cast(dict[str, object], payload["selected_card"])
        self.assertEqual(selected_card["object_ref"], publishable.object_ref)
        candidate_loader.assert_awaited_once_with(db, signal=publishable)
        command_loader.assert_awaited_once_with(
            db,
            signal=publishable,
            action_key=None,
        )

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
        self.assertIn(
            "no explicit active audience binding truth", str(raised.exception.detail)
        )


if __name__ == "__main__":
    unittest.main()
