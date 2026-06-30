from __future__ import annotations

import types
import unittest


class RuntimeSourceStateTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
