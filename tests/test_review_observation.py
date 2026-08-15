from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, cast
import unittest
import uuid

from cygnus.domain import governed_object_ref
from cygnus.review.drift import DriftGovernanceSurface, get_drift_governance_surface
from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.home import get_review_home_surface
from cygnus.review.intake import build_pressure_intake_surfaces
from cygnus.runtime.database.models import (
    GovernanceAudienceBinding,
    GovernancePropagation,
    GovernancePublication,
    Source,
    WikiPage,
)
from cygnus.review.source_blindness import (
    SourceFailureObservation,
    SourceImpactState,
    build_source_blindness_surface,
    build_source_failure_observations,
)
from cygnus.review.surface import ObservationState, SurfaceObservation

_VISIBLE_PAGE_ID = uuid.UUID("00000000-0000-4000-8000-000000000701")
_HIDDEN_PAGE_ID = uuid.UUID("00000000-0000-4000-8000-000000000702")


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

    def test_valid_observation_serializes_machine_codes_and_deduplicates_signals(
        self,
    ) -> None:
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
        empty_home = get_review_home_surface(
            bundles=(), observation=PARTIAL_REVIEW
        ).to_dict()
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
            impact_state=SourceImpactState.UNMAPPED,
        )

        drift_builder = cast(
            Callable[..., DriftGovernanceSurface], get_drift_governance_surface
        )
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

    def test_projector_excludes_non_error_sources_and_marks_mapped_impact(self) -> None:
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
                    id=_VISIBLE_PAGE_ID,
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
                    id=_HIDDEN_PAGE_ID,
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
        self.assertEqual(
            observation.linked_object_refs,
            (governed_object_ref(_VISIBLE_PAGE_ID),),
        )
        self.assertEqual(observation.impact_state, SourceImpactState.MAPPED)

    def test_projector_carries_durable_audience_and_page_scoped_propagation_truth(
        self,
    ) -> None:
        source = cast(
            Source,
            cast(
                object,
                SimpleNamespace(
                    id="source-error",
                    status="error",
                    title="Incident feed",
                    file_name=None,
                    url="https://status.example/feed",
                    error_message="upstream timeout",
                    updated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
                ),
            ),
        )
        page = cast(
            WikiPage,
            cast(
                object,
                SimpleNamespace(
                    id=_VISIBLE_PAGE_ID,
                    slug="billing-incident",
                    knowledge_type_slugs=("known_issue_page",),
                    source_ids=("source-error",),
                ),
            ),
        )
        binding = cast(
            GovernanceAudienceBinding,
            cast(
                object,
                SimpleNamespace(
                    page_id=_VISIBLE_PAGE_ID,
                    object_ref=governed_object_ref(_VISIBLE_PAGE_ID),
                    variant_ref="enterprise-eu",
                    channel="external-help",
                    visibility="external",
                    brands=(),
                    product_lines=("billing",),
                    plans=("enterprise",),
                    regions=("eu",),
                    languages=("en",),
                    product_versions=(),
                    lifecycle_state="active",
                    binding_key="binding-visible",
                    version=4,
                ),
            ),
        )
        publication = cast(
            GovernancePublication,
            cast(
                object,
                SimpleNamespace(
                    id="publication-visible",
                    page_id=_VISIBLE_PAGE_ID,
                    object_ref=governed_object_ref(_VISIBLE_PAGE_ID),
                ),
            ),
        )
        same_ref_other_page = cast(
            GovernancePublication,
            cast(
                object,
                SimpleNamespace(
                    id="publication-hidden",
                    page_id=_HIDDEN_PAGE_ID,
                    object_ref=governed_object_ref(_VISIBLE_PAGE_ID),
                ),
            ),
        )
        visible_propagation = cast(
            GovernancePropagation,
            cast(
                object,
                SimpleNamespace(
                    id="propagation-visible",
                    publication_id="publication-visible",
                    surface_id="external-help",
                    status="failed",
                    channel_refs=("external-help",),
                    version=2,
                ),
            ),
        )
        hidden_propagation = cast(
            GovernancePropagation,
            cast(
                object,
                SimpleNamespace(
                    id="propagation-hidden",
                    publication_id="publication-hidden",
                    surface_id="internal-copilot",
                    status="synced",
                    channel_refs=("internal-copilot",),
                    version=1,
                ),
            ),
        )

        observation = build_source_failure_observations(
            (source,),
            (page,),
            audience_bindings=(binding,),
            publications=(publication, same_ref_other_page),
            propagations=(visible_propagation, hidden_propagation),
        )[0]
        payload = observation.to_dict()

        self.assertEqual(payload["impact_state"], "mapped")
        self.assertEqual(len(observation.audience_impacts), 1)
        self.assertEqual(observation.audience_impacts[0].binding_ref, "binding-visible")
        self.assertEqual(
            observation.audience_impacts[0].audience.product_lines,
            ("billing",),
        )
        self.assertEqual(len(observation.propagation_impacts), 1)
        self.assertEqual(
            observation.propagation_impacts[0].propagation_ref,
            "propagation-visible",
        )
        propagation_payloads = cast(
            list[dict[str, object]], payload["propagation_impacts"]
        )
        self.assertEqual(propagation_payloads[0]["status"], "failed")

    def test_unmapped_source_is_explicit_without_claiming_no_business_impact(
        self,
    ) -> None:
        source = cast(
            Source,
            cast(
                object,
                SimpleNamespace(
                    id="source-unmapped",
                    status="error",
                    title="Uncompiled feed",
                    file_name=None,
                    url=None,
                    error_message="parse failure",
                    updated_at=None,
                ),
            ),
        )
        observation = build_source_failure_observations((source,), ())[0]
        surface = build_source_blindness_surface(
            (),
            observation=SurfaceObservation(
                state=ObservationState.READY,
                observed_count=1,
                reason="source_impact_observed",
                covered_signals=("source_status", "source_impact"),
            ),
            source_observations=(observation,),
        )

        self.assertEqual(observation.impact_state, SourceImpactState.UNMAPPED)
        self.assertEqual(observation.linked_wiki_refs, ())
        self.assertEqual(observation.audience_impacts, ())
        self.assertEqual(observation.propagation_impacts, ())
        self.assertIn("no governed Wiki impact mapped", surface.summary)
        self.assertEqual(surface.available_commands, ())
