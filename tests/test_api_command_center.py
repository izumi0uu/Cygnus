from __future__ import annotations

import unittest

from cygnus.api.app import command_center, healthz


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


if __name__ == "__main__":
    unittest.main()
