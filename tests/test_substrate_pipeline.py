from __future__ import annotations

import unittest

from cygnus.substrate.pipeline_checkpoint import PipelineCheckpoint
from cygnus.substrate.pipeline_phases import PipelinePhase
from cygnus.substrate.source_outline import (
    PAGE_JOIN_SEPARATOR,
    assemble_full_text,
    build_outline,
    parse_page_range,
    slice_pages_by_range,
)


class PipelinePhaseTests(unittest.TestCase):
    def test_pipeline_phase_enum_matches_cygnus_workflow_shape(self) -> None:
        self.assertEqual(
            [phase.value for phase in PipelinePhase],
            [
                "ingest",
                "normalize",
                "map_reduce",
                "plan",
                "review",
                "publish",
                "feedback",
            ],
        )


class PipelineCheckpointTests(unittest.TestCase):
    def test_checkpoint_tracks_completed_prefix_and_resume_phase(self) -> None:
        checkpoint = PipelineCheckpoint(workflow_id="wf-19")
        checkpoint = checkpoint.advance_to(PipelinePhase.NORMALIZE)
        checkpoint = checkpoint.advance_to(PipelinePhase.MAP_REDUCE)

        self.assertEqual(checkpoint.resume_phase, PipelinePhase.MAP_REDUCE)
        self.assertEqual(
            checkpoint.completed_phases,
            (PipelinePhase.INGEST, PipelinePhase.NORMALIZE),
        )

    def test_checkpoint_round_trips_as_resume_stub(self) -> None:
        checkpoint = PipelineCheckpoint(workflow_id="wf-19")
        checkpoint = checkpoint.advance_to(PipelinePhase.NORMALIZE)
        checkpoint = checkpoint.advance_to(PipelinePhase.MAP_REDUCE)
        payload = checkpoint.to_dict()

        restored = PipelineCheckpoint.from_dict(payload)

        self.assertEqual(restored.workflow_id, "wf-19")
        self.assertEqual(restored.current_phase, PipelinePhase.MAP_REDUCE)
        self.assertEqual(restored.resume_phase, PipelinePhase.MAP_REDUCE)

    def test_checkpoint_rejects_skipping_phases(self) -> None:
        checkpoint = PipelineCheckpoint(workflow_id="wf-19")
        with self.assertRaisesRegex(ValueError, "advance one step"):
            checkpoint.advance_to(PipelinePhase.PLAN)

    def test_checkpoint_can_mark_final_phase_complete(self) -> None:
        checkpoint = PipelineCheckpoint(workflow_id="wf-19")
        for target in (
            PipelinePhase.NORMALIZE,
            PipelinePhase.MAP_REDUCE,
            PipelinePhase.PLAN,
            PipelinePhase.REVIEW,
            PipelinePhase.PUBLISH,
            PipelinePhase.FEEDBACK,
        ):
            checkpoint = checkpoint.advance_to(target)

        checkpoint = checkpoint.mark_current_phase_complete()

        self.assertTrue(checkpoint.is_complete)
        self.assertIsNone(checkpoint.resume_phase)
        self.assertEqual(checkpoint.completed_phases, tuple(PipelinePhase))


class SourceOutlinePrimitiveTests(unittest.TestCase):
    def test_outline_primitives_round_trip_page_slices(self) -> None:
        pages = [
            {"page_number": 1, "content": "# Intro\nHello world"},
            {"page_number": 2, "content": "## Details\nMore detail"},
        ]

        full_text, offsets = assemble_full_text(pages)
        outline = build_outline(pages)
        selected = slice_pages_by_range(full_text, offsets, parse_page_range("1-2"))

        self.assertEqual(offsets, [0, len(pages[0]["content"]) + len(PAGE_JOIN_SEPARATOR)])
        self.assertEqual([item["page"] for item in selected], [1, 2])
        self.assertEqual(outline[0]["title"], "Intro")
        self.assertEqual(outline[0]["children"][0]["title"], "Details")
