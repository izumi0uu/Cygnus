from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cygnus.evaluation.contracts import PolicyExpectation
from cygnus.evaluation.policy import evaluate_policy_expectation
from cygnus.integrations.governed_publish_tools import GovernedPublishTools


class EvaluationPolicyTests(unittest.TestCase):
    def test_pending_draft_returns_real_approval_required_envelope(self) -> None:
        result = asyncio.run(
            evaluate_policy_expectation(
                PolicyExpectation(
                    draft_status="pending",
                    page_version=2,
                    expected_version=2,
                    expected_status="approval_required",
                    expected_error="approval_required",
                )
            )
        )

        data = result["data"]
        assert isinstance(data, dict)
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(result["errors"], ["approval_required"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(data["object_version"], 2)
        self.assertEqual(
            data["object_ref"],
            "ko-page-00000000-0000-4000-8000-000000000217",
        )
        self.assertFalse(data["allowed"])

    def test_stale_expected_version_returns_tool_conflict(self) -> None:
        result = asyncio.run(
            evaluate_policy_expectation(
                PolicyExpectation(
                    draft_status="approved",
                    page_version=5,
                    expected_version=4,
                    is_admin=True,
                    expected_status="conflict",
                    expected_error="stale_version",
                )
            )
        )

        data = result["data"]
        assert isinstance(data, dict)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["stale_version"])
        self.assertEqual(data["object_version"], 5)
        self.assertFalse(data["allowed"])

    def test_admin_with_durable_policy_truth_is_allowed(self) -> None:
        result = asyncio.run(
            evaluate_policy_expectation(
                PolicyExpectation(
                    draft_status="approved",
                    page_version=3,
                    expected_version=3,
                    is_admin=True,
                    expected_status="success",
                )
            )
        )

        data = result["data"]
        assert isinstance(data, dict)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(data["allowed"])
        self.assertEqual(data["target_channels"], ["internal-copilot"])
        self.assertEqual(
            data["recommended_action_key"],
            "publish",
        )

    def test_non_admin_never_becomes_success_for_an_approved_draft(self) -> None:
        result = asyncio.run(
            evaluate_policy_expectation(
                PolicyExpectation(
                    draft_status="approved",
                    page_version=3,
                    expected_version=3,
                    is_admin=False,
                    expected_status="approval_required",
                )
            )
        )

        data = result["data"]
        assert isinstance(data, dict)
        self.assertEqual(result["status"], "approval_required")
        self.assertNotEqual(result["status"], "success")
        self.assertFalse(data["allowed"])
        self.assertTrue(data["approval_required"])

    def test_probe_invokes_existing_tool_and_preserves_denial(self) -> None:
        denied = {
            "status": "denied",
            "summary": "Denied by the existing policy tool.",
            "data": {"allowed": False},
            "warnings": [],
            "errors": ["source_not_ready"],
        }
        validate = AsyncMock(return_value=denied)

        with patch.object(
            GovernedPublishTools,
            "validate_publish_policy",
            validate,
        ):
            result = asyncio.run(
                evaluate_policy_expectation(
                    PolicyExpectation(
                        draft_status="approved",
                        page_version=7,
                        expected_version=7,
                        is_admin=True,
                        expected_status="denied",
                        expected_error="source_not_ready",
                    )
                )
            )

        validate.assert_awaited_once_with(
            draft_id="00000000-0000-4000-8000-000000000317",
            target_channel="internal-copilot",
            expected_version=7,
        )
        self.assertIs(result, denied)
        self.assertEqual(result["status"], "denied")
        self.assertNotEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
