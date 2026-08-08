from __future__ import annotations

from datetime import datetime, timezone
import unittest
import uuid

from cygnus.governance.drift_signals import (
    DriftSignalProviderResult,
    compile_drift_signal_bundles,
)
from cygnus.review import build_drift_governance_surface
from cygnus.review.surface import ObservationState, SurfaceObservation
from cygnus.runtime.database.models import GovernanceSignal


_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def _drift_signal(
    *,
    signal_type: str,
    signal_ref: str,
    evidence_source_type: str,
) -> GovernanceSignal:
    return GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref=signal_ref,
        signal_type=signal_type,
        object_ref=f"ko:{signal_ref}",
        title=f"Governed {signal_type}",
        object_type="known_issue_page",
        page_id=None,
        source_id=None,
        audience_binding_ref=None,
        audience_filter={
            "visibility": "external",
            "brands": [],
            "product_lines": ["billing"],
            "plans": ["enterprise"],
            "regions": ["eu"],
            "languages": [],
            "product_versions": [],
        },
        affected_surfaces=["help_center", "copilot"],
        trigger_signals=[signal_type],
        evidence_source_type=evidence_source_type,
        freshness="stale",
        summary="Published guidance may no longer match current behavior.",
        reason="The upstream state changed after the last governed review.",
        evidence_excerpt="The changed behavior affects the current workaround.",
        queue_owner="support-ops",
        status="active",
        observed_at=_NOW,
        resolved_at=None,
        created_by_id=uuid.uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


class GovernanceDriftProviderTests(unittest.TestCase):
    def test_release_and_incident_rows_compile_into_drift_bundles(self) -> None:
        bundles = compile_drift_signal_bundles(
            (
                _drift_signal(
                    signal_type="release_delta",
                    signal_ref="release:billing:2026-08-08",
                    evidence_source_type="release_note",
                ),
                _drift_signal(
                    signal_type="incident_delta",
                    signal_ref="incident:billing:sev2",
                    evidence_source_type="incident_update",
                ),
            )
        )

        self.assertEqual(len(bundles), 2)
        self.assertEqual(
            {bundle.signal.risk_type.value for bundle in bundles},
            {"drift"},
        )
        surface = build_drift_governance_surface(bundles).to_dict()
        self.assertEqual(len(surface["contexts"]), 2)
        self.assertEqual(
            {event for context in surface["contexts"] for event in context["event_types"]},
            {"release_note", "incident_update"},
        )

    def test_empty_provider_is_covered_ready_truth_not_fixture_fallback(self) -> None:
        provider = DriftSignalProviderResult(signals=(), bundles=())
        observation = SurfaceObservation(
            state=ObservationState.READY,
            observed_count=0,
            reason="persisted_drift_provider_ready",
            covered_signals=provider.covered_signals,
        )

        payload = build_drift_governance_surface(
            provider.bundles,
            observation=observation,
        ).to_dict()

        self.assertEqual(payload["contexts"], [])
        self.assertEqual(payload["observation"]["state"], "ready")
        self.assertEqual(
            payload["observation"]["covered_signals"],
            ["release_delta", "incident_delta"],
        )
        self.assertEqual(payload["observation"]["missing_signals"], [])


if __name__ == "__main__":
    unittest.main()
