from __future__ import annotations

import unittest

from cygnus.recovery import (
    RecoveryWindowQuery,
    build_recovery_window,
    get_recovery_window_surface,
    sample_recovery_alignment_planes,
    sample_recovery_metrics_after,
    sample_recovery_metrics_before,
    sample_recovery_residual_risks,
    sample_reality_check_command_ref,
)


class RecoveryWindowTests(unittest.TestCase):
    def test_build_recovery_window_returns_before_after_surface(self) -> None:
        surface = build_recovery_window(
            command_ref=sample_reality_check_command_ref(),
            before_metrics=sample_recovery_metrics_before(),
            after_metrics=sample_recovery_metrics_after(),
            alignment_planes=sample_recovery_alignment_planes(),
            residual_risks=sample_recovery_residual_risks(),
        ).to_dict()

        self.assertEqual(surface["surface_id"], "recovery-window")
        self.assertEqual(surface["assessment"], "false_recovery")
        self.assertTrue(surface["rewrite_delta"]["improved"])
        self.assertEqual(surface["rewrite_delta"]["delta"], -6)
        self.assertIn(
            "audience_truth",
            surface["before_after_alignment_view"]["residual_truth_planes"],
        )
        self.assertEqual(
            surface["closure_judge"]["recommendation"],
            "continue_with_lightweight_follow_up",
        )
        self.assertIn("open_audience_mismatch_review", surface["continue_commands"])
        self.assertIn("downstream_reality_check:cmd-publish-1", surface["supporting_links"])

    def test_query_returns_surface_for_known_command(self) -> None:
        payload = get_recovery_window_surface(
            RecoveryWindowQuery(command_id="cmd-publish-1")
        ).to_dict()
        self.assertEqual(payload["publish_conflict_delta"]["after_value"], 1)

    def test_query_raises_when_command_missing(self) -> None:
        with self.assertRaises(ValueError):
            get_recovery_window_surface(
                RecoveryWindowQuery(command_id="missing-command")
            )


if __name__ == "__main__":
    unittest.main()
