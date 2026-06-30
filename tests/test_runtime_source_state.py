from __future__ import annotations

import types
import unittest


class RuntimeSourceStateTests(unittest.TestCase):
    def test_mark_source_processing_sets_processing_preset(self) -> None:
        from cygnus.runtime.source_state import mark_source_processing

        source = types.SimpleNamespace(
            status="pending",
            progress=0,
            progress_message=None,
        )

        result = mark_source_processing(
            source,
            progress=56,
            progress_message="Extracting knowledge from document...",
        )

        self.assertIs(result, source)
        self.assertEqual(source.status, "processing")
        self.assertEqual(source.progress, 56)
        self.assertEqual(source.progress_message, "Extracting knowledge from document...")

    def test_mark_source_requeued_after_department_change_sets_runtime_fields(self) -> None:
        from cygnus.runtime.source_state import mark_source_requeued_after_department_change

        source = types.SimpleNamespace(
            status="ready",
            progress=100,
            progress_message="Done",
            error_message="old",
            job_id=None,
        )

        result = mark_source_requeued_after_department_change(source, job_id="job-1")

        self.assertIs(result, source)
        self.assertEqual(source.status, "processing")
        self.assertEqual(source.progress, 0)
        self.assertEqual(source.progress_message, "Re-queued after department change...")
        self.assertIsNone(source.error_message)
        self.assertEqual(source.job_id, "job-1")

    def test_mark_source_retry_queued_sets_runtime_fields(self) -> None:
        from cygnus.runtime.source_state import mark_source_retry_queued

        source = types.SimpleNamespace(
            status="error",
            progress=12,
            progress_message="Error",
            error_message="boom",
            job_id=None,
        )

        result = mark_source_retry_queued(source, job_id="job-2")

        self.assertIs(result, source)
        self.assertEqual(source.status, "pending")
        self.assertEqual(source.progress, 0)
        self.assertEqual(source.progress_message, "Queued for retry...")
        self.assertIsNone(source.error_message)
        self.assertEqual(source.job_id, "job-2")

    def test_mark_source_ingest_queued_sets_initial_ingest_fields(self) -> None:
        from cygnus.runtime.source_state import mark_source_ingest_queued

        source = types.SimpleNamespace(
            status="draft",
            progress=10,
            progress_message="old",
            error_message="bad",
            job_id=None,
        )

        result = mark_source_ingest_queued(source, job_id="job-ingest-1")

        self.assertIs(result, source)
        self.assertEqual(source.status, "pending")
        self.assertEqual(source.progress, 0)
        self.assertEqual(source.progress_message, "Queued for ingestion...")
        self.assertIsNone(source.error_message)
        self.assertEqual(source.job_id, "job-ingest-1")

    def test_mark_source_post_extraction_resume_covers_caption_and_direct_paths(self) -> None:
        from cygnus.runtime.source_state import mark_source_post_extraction_resume

        image_source = types.SimpleNamespace(
            status="awaiting_approval",
            progress=55,
            progress_message=None,
            job_id=None,
        )
        result = mark_source_post_extraction_resume(
            image_source,
            has_images=True,
            job_id="job-3",
        )
        self.assertIs(result, image_source)
        self.assertEqual(image_source.status, "processing")
        self.assertEqual(image_source.progress, 56)
        self.assertEqual(image_source.progress_message, "Captioning images before extraction...")
        self.assertEqual(image_source.job_id, "job-3")

        direct_source = types.SimpleNamespace(
            status="awaiting_approval",
            progress=55,
            progress_message=None,
            job_id=None,
        )
        mark_source_post_extraction_resume(
            direct_source,
            has_images=False,
            job_id="job-4",
            progress=55,
        )
        self.assertEqual(direct_source.status, "processing")
        self.assertEqual(direct_source.progress, 55)
        self.assertEqual(direct_source.progress_message, "Extraction queued...")
        self.assertEqual(direct_source.job_id, "job-4")

    def test_mark_source_plan_refine_queued_only_attaches_job(self) -> None:
        from cygnus.runtime.source_state import mark_source_plan_refine_queued

        source = types.SimpleNamespace(
            status="processing",
            progress=78,
            progress_message="Plan approved — compiling wiki pages...",
            job_id=None,
        )

        result = mark_source_plan_refine_queued(source, job_id="job-5")

        self.assertIs(result, source)
        self.assertEqual(source.status, "processing")
        self.assertEqual(source.progress, 78)
        self.assertEqual(source.progress_message, "Plan approved — compiling wiki pages...")
        self.assertEqual(source.job_id, "job-5")

    def test_mark_source_awaiting_approval_formats_threshold_message(self) -> None:
        from cygnus.runtime.source_state import mark_source_awaiting_approval

        source = types.SimpleNamespace(
            status="processing",
            progress=50,
            progress_message=None,
        )

        result = mark_source_awaiting_approval(
            source,
            token_count=12345,
            threshold=2000,
        )

        self.assertIs(result, source)
        self.assertEqual(source.status, "awaiting_approval")
        self.assertEqual(source.progress, 55)
        self.assertEqual(
            source.progress_message,
            "Awaiting human approval: 12,345 tokens > 2,000 threshold",
        )

    def test_mark_source_runtime_error_sets_default_progress_message(self) -> None:
        from cygnus.runtime.source_state import mark_source_runtime_error

        source = types.SimpleNamespace(
            status="processing",
            progress=80,
            progress_message="Writing wiki pages...",
            error_message=None,
        )

        result = mark_source_runtime_error(
            source,
            error_message="Unable to fetch content from URL",
        )

        self.assertIs(result, source)
        self.assertEqual(source.status, "error")
        self.assertEqual(source.progress, 0)
        self.assertEqual(source.error_message, "Unable to fetch content from URL")
        self.assertEqual(source.progress_message, "Unable to fetch content from URL")

    def test_mark_source_plan_ready_and_ready_reset_runtime_recovery_state(self) -> None:
        from cygnus.runtime.source_state import (
            mark_source_plan_ready_for_review,
            mark_source_ready,
        )

        source = types.SimpleNamespace(
            status="processing",
            progress=78,
            progress_message=None,
            auto_recover_count=3,
            error_message="old",
        )

        mark_source_plan_ready_for_review(source)
        self.assertEqual(source.status, "plan_ready")
        self.assertEqual(source.progress, 80)
        self.assertEqual(source.progress_message, "Compilation plan ready — awaiting review")
        self.assertEqual(source.auto_recover_count, 0)

        mark_source_ready(source)
        self.assertEqual(source.status, "ready")
        self.assertEqual(source.progress, 100)
        self.assertEqual(source.progress_message, "Done")
        self.assertEqual(source.auto_recover_count, 0)
        self.assertIsNone(source.error_message)


if __name__ == "__main__":
    unittest.main()
