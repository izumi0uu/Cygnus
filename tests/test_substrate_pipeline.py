from __future__ import annotations

import unittest

from cygnus.substrate.pipeline_phases import PipelinePhase


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

