from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, cast
import unittest

from cygnus.review.drift import DriftGovernanceSurface, get_drift_governance_surface
from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.home import get_review_home_surface
from cygnus.review.intake import build_pressure_intake_surfaces
from cygnus.runtime.database.models import Source, WikiPage
from cygnus.review.source_blindness import (
    SourceFailureObservation,
    build_source_blindness_surface,
    build_source_failure_observations,
)
from cygnus.review.surface import ObservationState, SurfaceObservation


PARTIAL_REVIEW = SurfaceObservation(
    state=ObservationState.PARTIAL,
    observed_count=0,
    reason="review_signal_coverage_partial",
    covered_signals=("source_status",),
    missing_signals=("ticket_pressure",),
)
UNAVAILABLE_DRIFT = SurfaceObservation(
    state=ObservationState.UNAVAILABLE,
    observed_count=0,
    reason="drift_detectors_unavailable",
    missing_signals=("release_delta",),
)
PARTIAL_SOURCE = SurfaceObservation(
    state=ObservationState.PARTIAL,
    observed_count=1,
    reason="source_impact_coverage_partial",
    covered_signals=("source_status",),
    missing_signals=("source_impact",),
)


class SurfaceObservationTests(unittest.TestCase):
    def test_state_invariants_reject_invalid_signal_combinations(self) -> None:
        with self.assertRaises(ValueError):
            _ = SurfaceObservation(
                state=ObservationState.READY,
                observed_count=0,
                reason="ready",
            )
        with self.assertRaises(ValueError):
            _ = SurfaceObservation(
                state=ObservationState.PARTIAL,
                observed_count=1,
                reason="partial",
                covered_signals=("source_status",),
            )
        with self.assertRaises(ValueError):
            _ = SurfaceObservation(
                state=ObservationState.UNAVAILABLE,
                observed_count=1,
                reason="unavailable",
                missing_signals=("release_delta",),
            )
        with self.assertRaises(ValueError):
            _ = SurfaceObservation(
                state=ObservationState.UNAVAILABLE,
                observed_count=0,
                reason="unavailable",
                covered_signals=("source_status",),
                missing_signals=("release_delta",),
            )

    def test_valid_observation_serializes_machine_codes_and_deduplicates_signals(self) -> None:
        observation = SurfaceObservation(
            state=ObservationState.PARTIAL,
            observed_count=0,
            reason="  review_signal_coverage_partial  ",
            covered_signals=("source_status", "source_status"),
            missing_signals=("ticket_pressure", "ticket_pressure"),
        )

        self.assertEqual(
            observation.to_dict(),
            {
                "state": "partial",
                "observed_count": 0,
                "reason": "review_signal_coverage_partial",
                "covered_signals": ["source_status"],
                "missing_signals": ["ticket_pressure"],
            },
        )

    def test_empty_and_nonempty_builders_keep_truthful_shape(self) -> None:
        empty_home = get_review_home_surface(bundles=(), observation=PARTIAL_REVIEW).to_dict()
        self.assertEqual(empty_home["priority_stack"], [])
        self.assertEqual(empty_home["available_commands"], [])
        self.assertIsNone(empty_home["command_brief"])
        self.assertEqual(empty_home["observation"], PARTIAL_REVIEW.to_dict())

        nonempty_home = get_review_home_surface(
            bundles=sample_review_bundles(),
            observation=SurfaceObservation(
                state=ObservationState.READY,
                observed_count=4,
                reason="review_signals_observed",
                covered_signals=("ticket_pressure",),
            ),
        )
        self.assertGreater(len(nonempty_home.priority_stack), 0)
        self.assertTrue(nonempty_home.available_commands)
        self.assertIsNotNone(nonempty_home.command_brief)

    def test_empty_drift_source_and_intake_surfaces_do_not_offer_commands(self) -> None:
        source_failure = SourceFailureObservation(
            source_id="source-error",
            title="Incident feed",
            source_ref="incident-feed",
            status="error",
            error_message="upstream timeout",
        )

        drift_builder = cast(Callable[..., DriftGovernanceSurface], get_drift_governance_surface)
        drift_surface = drift_builder(
            bundles=(),
            observation=UNAVAILABLE_DRIFT,
        )
        self.assertEqual(drift_surface.contexts, ())
        self.assertEqual(drift_surface.available_commands, ())
        self.assertEqual(drift_surface.proposal_lane, ())

        source_surface = build_source_blindness_surface(
            (),
            observation=PARTIAL_SOURCE,
            source_observations=(source_failure,),
        )
        self.assertEqual(source_surface.contexts, ())
        self.assertEqual(source_surface.available_commands, ())
        self.assertEqual(source_surface.source_observations, (source_failure,))

        intake = build_pressure_intake_surfaces(
            bundles=(),
            review_observation=PARTIAL_REVIEW,
            source_observation=PARTIAL_SOURCE,
            source_observations=(source_failure,),
        )
        self.assertEqual(intake.bundles, ())
        self.assertIsNone(intake.pressure_surface)
        source_blindness_surface = intake.source_blindness_surface
        self.assertIsNotNone(source_blindness_surface)
        if source_blindness_surface is None:
            self.fail("empty intake must retain the partial source surface")
        self.assertEqual(
            source_blindness_surface.source_observations,
            (source_failure,),
        )

    def test_projector_excludes_non_error_sources_and_keeps_impact_unknown(self) -> None:
        error_source = cast(
            Source,
            cast(
                object,
                SimpleNamespace(
                    id="source-error",
                    status="error",
                    title="",
                    file_name="incident-feed.json",
                    url=None,
                    error_message="",
                    updated_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
                ),
            ),
        )
        ready_source = cast(
            Source,
            cast(
                object,
                SimpleNamespace(
                    id="source-ready",
                    status="ready",
                    title="Ready source",
                    file_name="ready.md",
                    url=None,
                    error_message=None,
                    updated_at=None,
                ),
            ),
        )
        visible_page = cast(
            WikiPage,
            cast(
                object,
                SimpleNamespace(
                    slug="billing-incident",
                    knowledge_type_slugs=("known_issue_page",),
                    source_ids=("source-error",),
                ),
            ),
        )
        hidden_page = cast(
            WikiPage,
            cast(
                object,
                SimpleNamespace(
                    slug="hidden-incident",
                    knowledge_type_slugs=("known_issue_page",),
                    source_ids=("source-ready",),
                ),
            ),
        )

        observations = build_source_failure_observations(
            (error_source, ready_source),
            (visible_page, hidden_page),
        )

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.source_id, "source-error")
        self.assertEqual(observation.title, "incident-feed.json")
        self.assertEqual(observation.error_message, "source_error_detail_unavailable")
        self.assertEqual(observation.linked_wiki_refs, ("billing-incident",))
        self.assertEqual(observation.linked_object_refs, ("ko-billing-incident",))
        self.assertEqual(observation.impact_state, "unknown")

