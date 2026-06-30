from __future__ import annotations

import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch


class SourcePlanLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_source_compilation_plan_updates_plan_and_source(self) -> None:
        import cygnus.review.source_plans as plan_module

        plan = types.SimpleNamespace(
            id=uuid.uuid4(),
            status="pending_review",
            reviewed_by=None,
            review_note=None,
            reviewed_at=None,
        )
        source = types.SimpleNamespace(
            status="plan_ready",
            progress=0,
            progress_message=None,
        )
        reviewer = types.SimpleNamespace(id=uuid.uuid4(), role="admin")

        with patch.object(plan_module, "log_audit", AsyncMock()) as log_audit:
            result = await plan_module.approve_source_compilation_plan(
                object(),
                plan,
                source,
                reviewer,
                "Looks good",
            )

        self.assertIs(result, plan)
        self.assertEqual(plan.status, "approved")
        self.assertEqual(plan.reviewed_by, reviewer.id)
        self.assertEqual(plan.review_note, "Looks good")
        self.assertIsNotNone(plan.reviewed_at)
        self.assertEqual(source.status, "processing")
        self.assertEqual(source.progress, 78)
        self.assertEqual(source.progress_message, "Plan approved — compiling wiki pages...")
        log_audit.assert_awaited_once()

    async def test_reject_source_compilation_plan_updates_plan_and_source(self) -> None:
        import cygnus.review.source_plans as plan_module

        plan = types.SimpleNamespace(
            id=uuid.uuid4(),
            status="pending_review",
            reviewed_by=None,
            review_note=None,
            reviewed_at=None,
        )
        source = types.SimpleNamespace(status="plan_ready", error_message=None)
        reviewer = types.SimpleNamespace(id=uuid.uuid4(), role="admin")

        with patch.object(plan_module, "log_audit", AsyncMock()) as log_audit:
            result = await plan_module.reject_source_compilation_plan(
                object(),
                plan,
                source,
                reviewer,
                "Need a narrower plan",
            )

        self.assertIs(result, plan)
        self.assertEqual(plan.status, "rejected")
        self.assertEqual(plan.reviewed_by, reviewer.id)
        self.assertEqual(plan.review_note, "Need a narrower plan")
        self.assertIsNotNone(plan.reviewed_at)
        self.assertEqual(source.status, "error")
        self.assertEqual(source.error_message, "Compilation plan rejected: Need a narrower plan")
        log_audit.assert_awaited_once()

    async def test_request_source_plan_regeneration_marks_regenerating(self) -> None:
        import cygnus.review.source_plans as plan_module

        plan = types.SimpleNamespace(id=uuid.uuid4(), status="pending_review", review_note=None)
        reviewer = types.SimpleNamespace(id=uuid.uuid4(), role="admin")

        with patch.object(plan_module, "log_audit", AsyncMock()) as log_audit:
            result = await plan_module.request_source_plan_regeneration(
                object(),
                plan,
                reviewer,
                "Use stronger grouping by issue type",
            )

        self.assertIs(result, plan)
        self.assertEqual(plan.status, "regenerating")
        self.assertEqual(plan.review_note, "Use stronger grouping by issue type")
        log_audit.assert_awaited_once()

    async def test_invalid_plan_transition_raises(self) -> None:
        import cygnus.review.source_plans as plan_module

        plan = types.SimpleNamespace(id=uuid.uuid4(), status="approved")
        source = types.SimpleNamespace(status="processing")
        reviewer = types.SimpleNamespace(id=uuid.uuid4(), role="admin")

        with self.assertRaises(plan_module.SourcePlanInvalidTransition):
            await plan_module.approve_source_compilation_plan(object(), plan, source, reviewer)

    def test_auto_approve_source_compilation_plan_promotes_pending_review(self) -> None:
        import cygnus.review.source_plans as plan_module

        plan = types.SimpleNamespace(status="pending_review", review_note=None, reviewed_at=None)
        source = types.SimpleNamespace(status="plan_ready", progress_message=None)

        result = plan_module.auto_approve_source_compilation_plan(plan, source)

        self.assertIs(result, plan)
        self.assertEqual(plan.status, "approved")
        self.assertEqual(plan.review_note, "Auto-approved")
        self.assertIsNotNone(plan.reviewed_at)
        self.assertEqual(source.status, "processing")
        self.assertEqual(source.progress_message, "Plan approved — compiling wiki pages...")

    def test_restore_and_fail_regeneration_preserve_owner_truth(self) -> None:
        import cygnus.review.source_plans as plan_module

        plan = types.SimpleNamespace(
            status="regenerating",
            plan_json={"before": True},
            reviewed_by=uuid.uuid4(),
            review_note="old",
            reviewed_at=object(),
        )

        plan_module.restore_source_plan_pending_review(plan, plan_json={"after": True})
        self.assertEqual(plan.status, "pending_review")
        self.assertEqual(plan.plan_json, {"after": True})
        self.assertIsNone(plan.reviewed_by)
        self.assertIsNone(plan.review_note)
        self.assertIsNone(plan.reviewed_at)

        plan.status = "regenerating"
        plan_module.fail_source_plan_regeneration(plan, reason="provider unavailable")
        self.assertEqual(plan.status, "pending_review")
        self.assertEqual(plan.review_note, "Regeneration failed: provider unavailable")


if __name__ == "__main__":
    unittest.main()
