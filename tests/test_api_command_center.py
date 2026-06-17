from __future__ import annotations

import unittest

from cygnus.api.app import (
    command_center,
    downstream_reality_check,
    governance_overview,
    healthz,
    recovery_window,
)


class CommandCenterApiTests(unittest.TestCase):
    def test_healthz_ok(self) -> None:
        self.assertEqual(healthz(), {"status": "ok"})

    def test_command_center_payload_shape(self) -> None:
        payload = command_center()
        self.assertIn("situation_frame", payload)
        self.assertIn("priority_stack", payload)
        self.assertIn("available_commands", payload)
        self.assertEqual(len(payload["priority_stack"]), 4)
        self.assertEqual(payload["situation_frame"]["urgent_items"], 1)

    def test_downstream_reality_check_payload_shape(self) -> None:
        payload = downstream_reality_check("cmd-publish-1")
        self.assertEqual(payload["surface_id"], "downstream-reality-check")
        self.assertIn("reality_check_strip", payload)
        self.assertIn("feedback_feed", payload)
        self.assertIn("mismatch_by_audience", payload)

    def test_recovery_window_payload_shape(self) -> None:
        payload = recovery_window("cmd-publish-1")
        self.assertEqual(payload["surface_id"], "recovery-window")
        self.assertIn("before_after_alignment_view", payload)
        self.assertIn("rewrite_delta", payload)
        self.assertIn("closure_judge", payload)

    def test_governance_overview_payload_shape(self) -> None:
        payload = governance_overview()
        self.assertEqual(payload["surface_id"], "governance-overview")
        self.assertIn("open_loops", payload)
        self.assertIn("open_loop_ranks", payload)
        self.assertIn("highest_leverage_command", payload)
        self.assertEqual(len(payload["open_loops"]), 2)
        self.assertEqual(payload["highest_leverage_command"], "cmd-restrict-2")


if __name__ == "__main__":
    unittest.main()
