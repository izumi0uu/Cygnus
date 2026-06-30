from __future__ import annotations

import tempfile
import unittest

from cygnus.substrate import DurableWorkflowJob, FileDurableJobStore, QueueStatus
from cygnus.substrate.pipeline_phases import PipelinePhase
from cygnus.workflows import (
    GovernanceGoldenPathWorkflow,
    GoldenPathStage,
    assert_governance_golden_path_complete,
    build_governance_golden_path,
)


class GovernanceGoldenPathWorkflowTests(unittest.TestCase):
    def test_golden_path_tracks_product_stage_and_substrate_phase_together(self) -> None:
        workflow = GovernanceGoldenPathWorkflow.sample()

        self.assertEqual(workflow.current_stage, GoldenPathStage.INGEST)
        self.assertEqual(workflow.current_phase, PipelinePhase.INGEST)

        workflow.mark_current_stage_complete()
        self.assertEqual(workflow.current_stage, GoldenPathStage.COMPILE)
        self.assertEqual(workflow.current_phase, PipelinePhase.NORMALIZE)

        workflow.mark_current_stage_complete()
        self.assertEqual(workflow.current_stage, GoldenPathStage.REVIEW)
        self.assertEqual(workflow.current_phase, PipelinePhase.REVIEW)

        workflow.mark_current_stage_complete()
        self.assertEqual(workflow.current_stage, GoldenPathStage.PUBLISH)
        self.assertEqual(workflow.current_phase, PipelinePhase.PUBLISH)

        workflow.mark_current_stage_complete()
        self.assertEqual(workflow.current_stage, GoldenPathStage.RECOVERY)
        self.assertEqual(workflow.current_phase, PipelinePhase.FEEDBACK)

        workflow.mark_current_stage_complete()
        self.assertTrue(workflow.is_complete)

    def test_built_golden_path_is_complete_and_serializable(self) -> None:
        payload = assert_governance_golden_path_complete()
        self.assertEqual(payload["workflow_name"], "governance_golden_path")
        self.assertEqual(payload["current_stage"], "recovery")
        self.assertEqual(payload["current_phase"], "feedback")
        self.assertTrue(payload["is_complete"])

    def test_golden_path_round_trips_through_durable_job_store(self) -> None:
        workflow = build_governance_golden_path()

        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileDurableJobStore(tmpdir)
            job = store.enqueue(
                DurableWorkflowJob.from_workflow(
                    workflow_name="governance_golden_path",
                    workflow=workflow,
                )
            )
            restored = store.load(job.job_id)

        self.assertEqual(restored.queue_status, QueueStatus.PENDING)
        self.assertIsNone(restored.resume_phase)
        self.assertEqual(restored.workflow_name, "governance_golden_path")
        self.assertTrue(restored.workflow_payload["is_complete"])
        restored_workflow = GovernanceGoldenPathWorkflow.from_dict(restored.workflow_payload)
        self.assertTrue(restored_workflow.is_complete)
        self.assertEqual(restored_workflow.current_stage, GoldenPathStage.RECOVERY)
        self.assertEqual(restored_workflow.current_phase, PipelinePhase.FEEDBACK)


if __name__ == "__main__":
    unittest.main()
