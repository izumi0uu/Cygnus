from __future__ import annotations

import tempfile
import unittest

from cygnus.domain.objects import KnowledgeObjectType
from cygnus.substrate.compilation_plan import (
    CompilationProposal,
    EvidenceSufficiency,
    PlanAction,
    UrgencyLevel,
)
from cygnus.substrate.durable_jobs import (
    DurableWorkflowJob,
    FileDurableJobStore,
    QueueStatus,
)
from cygnus.substrate.pipeline_phases import PipelinePhase
from cygnus.workflows.review_publish import ReviewPublishWorkflow


class DurableWorkflowJobTests(unittest.TestCase):
    def test_durable_job_round_trips_pending_snapshot(self) -> None:
        workflow = _build_workflow()
        workflow.advance(PipelinePhase.NORMALIZE)
        workflow.advance(PipelinePhase.MAP_REDUCE)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileDurableJobStore(tmpdir)
            job = DurableWorkflowJob.from_workflow(
                workflow_name="review_publish",
                workflow=workflow,
            )
            store.enqueue(job)

            restored = store.load(job.job_id)

        self.assertEqual(restored.queue_status, QueueStatus.PENDING)
        self.assertEqual(restored.resume_phase, "map_reduce")
        restored_workflow = ReviewPublishWorkflow.from_dict(restored.workflow_payload)
        self.assertEqual(restored_workflow.workflow_id, workflow.workflow_id)
        self.assertEqual(restored_workflow.current_phase, PipelinePhase.MAP_REDUCE)

    def test_queue_status_progression_preserves_same_workflow_context(self) -> None:
        workflow = _build_workflow()
        workflow.advance(PipelinePhase.NORMALIZE)
        workflow.advance(PipelinePhase.MAP_REDUCE)
        workflow.advance(PipelinePhase.PLAN)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileDurableJobStore(tmpdir)
            job = store.enqueue(
                DurableWorkflowJob.from_workflow(
                    workflow_name="review_publish",
                    workflow=workflow,
                )
            )
            active = store.activate(job.job_id)
            failed = store.fail(job.job_id, error="worker crashed mid-plan")
            resumed = store.resume(job.job_id)
            reactivated = store.activate(job.job_id)
            completed = store.complete(job.job_id)

        self.assertEqual(active.queue_status, QueueStatus.ACTIVE)
        self.assertEqual(active.attempt_count, 1)
        self.assertEqual(failed.queue_status, QueueStatus.FAILED)
        self.assertEqual(failed.last_error, "worker crashed mid-plan")
        self.assertEqual(resumed.queue_status, QueueStatus.RESUMED)
        self.assertEqual(resumed.resume_phase, "plan")
        self.assertEqual(reactivated.queue_status, QueueStatus.ACTIVE)
        self.assertEqual(reactivated.attempt_count, 2)
        self.assertEqual(completed.queue_status, QueueStatus.COMPLETED)
        restored_workflow = ReviewPublishWorkflow.from_dict(completed.workflow_payload)
        self.assertEqual(restored_workflow.workflow_id, workflow.workflow_id)
        self.assertEqual(restored_workflow.resume_phase, PipelinePhase.PLAN)

    def test_invalid_queue_transition_is_rejected(self) -> None:
        workflow = _build_workflow()
        job = DurableWorkflowJob.from_workflow(
            workflow_name="review_publish",
            workflow=workflow,
        )

        with self.assertRaisesRegex(ValueError, "invalid queue transition"):
            job.transition_to(QueueStatus.COMPLETED)


def _build_workflow() -> ReviewPublishWorkflow:
    proposal = CompilationProposal(
        proposal_id="cp-job-1",
        object_type=KnowledgeObjectType.ANSWER_CARD,
        action=PlanAction.UPDATE,
        title="Update invoice timing guidance",
        summary="Preserve the canonical billing answer under queue-backed execution.",
        evidence_ids=("ev-queue-1",),
        urgency=UrgencyLevel.HIGH,
        evidence_sufficiency=EvidenceSufficiency.PARTIAL,
        review_owner="support-ops",
        why_now="A durable recovery path is required before recovery surfaces ship.",
    )
    return ReviewPublishWorkflow(workflow_id="wf-job-1", proposals=(proposal,))
