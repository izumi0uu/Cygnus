from __future__ import annotations

import types
import unittest
from unittest.mock import call
import uuid
from unittest.mock import AsyncMock, patch


class WorkerJobRoutingRecoveryTests(unittest.TestCase):
    def test_post_extraction_routing_prefers_caption_before_map_reduce(self) -> None:
        from cygnus.runtime.worker import resolve_post_extraction_task

        self.assertEqual(resolve_post_extraction_task(has_images=True), "caption_images_task")
        self.assertEqual(resolve_post_extraction_task(has_images=False), "ingest_map_reduce_task")

    def test_retry_routing_reenters_map_reduce_for_plan_ready_sources(self) -> None:
        from cygnus.runtime.worker import resolve_retry_task

        task_name = resolve_retry_task(
            source_type="file",
            pipeline_phase=None,
            current_status="plan_ready",
        )

        self.assertEqual(task_name, "ingest_map_reduce_task")

    def test_retry_routing_reenters_refine_for_late_pipeline_phases(self) -> None:
        from cygnus.runtime.worker import resolve_retry_task

        for phase in ("refine", "verify", "commit"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    resolve_retry_task(
                        source_type="file",
                        pipeline_phase=phase,
                        current_status="error",
                    ),
                    "ingest_refine_task",
                )

    def test_worker_settings_publish_real_ingest_and_resume_jobs(self) -> None:
        from cygnus.runtime.worker import WorkerSettings

        job_names = {
            getattr(item, "name", None)
            or getattr(item, "__name__", None)
            or getattr(getattr(item, "coroutine", None), "__name__", None)
            for item in WorkerSettings.functions
        }

        self.assertTrue(
            {
                "ingest_file_task",
                "ingest_url_task",
                "caption_images_task",
                "ingest_map_reduce_task",
                "ingest_refine_task",
                "regenerate_plan_task",
            }.issubset(job_names)
        )


class WorkerJobExecutionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_dispatch_helpers_use_runtime_owned_worker_names(self) -> None:
        import cygnus.runtime.worker as worker_module

        fake_pool = types.SimpleNamespace(
            enqueue_job=AsyncMock(side_effect=[
                types.SimpleNamespace(job_id="job-file"),
                types.SimpleNamespace(job_id="job-url"),
                types.SimpleNamespace(job_id="job-map"),
                types.SimpleNamespace(job_id="job-refine"),
                types.SimpleNamespace(job_id="job-regen"),
            ])
        )

        with patch.object(worker_module, "get_arq_pool", AsyncMock(return_value=fake_pool)):
            file_job = await worker_module.enqueue_source_ingest_file("src-1")
            url_job = await worker_module.enqueue_source_ingest_url("src-2")
            map_job = await worker_module.enqueue_source_map_reduce("src-3")
            refine_job = await worker_module.enqueue_source_refine("src-4")
            regen_job = await worker_module.enqueue_source_plan_regeneration("src-5", "note")

        self.assertEqual(file_job, "job-file")
        self.assertEqual(url_job, "job-url")
        self.assertEqual(map_job, "job-map")
        self.assertEqual(refine_job, "job-refine")
        self.assertEqual(regen_job, "job-regen")
        self.assertEqual(
            fake_pool.enqueue_job.await_args_list,
            [
                call("ingest_file_task", "src-1"),
                call("ingest_url_task", "src-2"),
                call("ingest_map_reduce_task", "src-3"),
                call("ingest_refine_task", "src-4"),
                call("regenerate_plan_task", "src-5", "note"),
            ],
        )

    async def test_enqueue_post_extraction_pipeline_uses_worker_job_topology(self) -> None:
        import cygnus.runtime.worker as worker_module

        fake_pool = types.SimpleNamespace(
            enqueue_job=AsyncMock(return_value=types.SimpleNamespace(job_id="job-55-caption"))
        )

        with patch.object(worker_module, "get_arq_pool", AsyncMock(return_value=fake_pool)):
            job_id = await worker_module.enqueue_post_extraction_pipeline(
                "src-55",
                has_images=True,
            )

        fake_pool.enqueue_job.assert_awaited_once_with("caption_images_task", "src-55")
        self.assertEqual(job_id, "job-55-caption")

    async def test_enqueue_source_retry_uses_runtime_retry_resolution(self) -> None:
        import cygnus.runtime.worker as worker_module

        fake_pool = types.SimpleNamespace(
            enqueue_job=AsyncMock(return_value=types.SimpleNamespace(job_id="job-88-retry"))
        )

        with patch.object(worker_module, "get_arq_pool", AsyncMock(return_value=fake_pool)):
            job_id, task_name = await worker_module.enqueue_source_retry(
                "src-88",
                source_type="url",
                pipeline_phase=None,
                current_status="error",
            )

        fake_pool.enqueue_job.assert_awaited_once_with("ingest_url_task", "src-88")
        self.assertEqual(job_id, "job-88-retry")
        self.assertEqual(task_name, "ingest_url_task")

    async def test_auto_trigger_refine_promotes_plan_and_enqueues_resume_job(self) -> None:
        import cygnus.runtime.ai.mrp.pipeline as pipeline_module
        from cygnus.runtime.database.models import Source, SourceCompilationPlan

        source_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        plan_row = types.SimpleNamespace(
            id=plan_id,
            status="pending_review",
            review_note=None,
            reviewed_at=None,
        )
        source_row = types.SimpleNamespace(
            id=source_id,
            status="plan_ready",
            progress_message=None,
        )

        class _FakeSession:
            async def get(self, model, obj_id):
                if model is SourceCompilationPlan and obj_id == plan_id:
                    return plan_row
                if model is Source and obj_id == source_id:
                    return source_row
                return None

            async def commit(self):
                return None

        class _SessionScope:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _SessionFactory:
            def __call__(self):
                return _SessionScope(_FakeSession())

        fake_pool = types.SimpleNamespace(
            enqueue_job=AsyncMock(return_value=types.SimpleNamespace(job_id="job-55-refine"))
        )

        with (
            patch("cygnus.runtime.database.async_session_factory", new=_SessionFactory()),
            patch("cygnus.runtime.worker.get_arq_pool", AsyncMock(return_value=fake_pool)),
        ):
            result = await pipeline_module._auto_trigger_refine(
                source_id,
                types.SimpleNamespace(id=plan_id),
            )

        self.assertEqual(plan_row.status, "approved")
        self.assertEqual(plan_row.review_note, "Auto-approved")
        self.assertIsNotNone(plan_row.reviewed_at)
        self.assertEqual(source_row.status, "processing")
        self.assertEqual(source_row.progress_message, "Plan approved — compiling wiki pages...")
        fake_pool.enqueue_job.assert_awaited_once_with("ingest_refine_task", str(source_id))
        self.assertEqual(
            result,
            {"status": "plan_auto_approved", "job_id": "job-55-refine"},
        )


if __name__ == "__main__":
    unittest.main()
