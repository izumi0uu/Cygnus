from __future__ import annotations

import unittest

from cygnus.api.app import command_center, downstream_reality_check, healthz


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


if __name__ == "__main__":
    unittest.main()
