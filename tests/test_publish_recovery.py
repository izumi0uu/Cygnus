from __future__ import annotations

import unittest

from cygnus.recovery import get_pressure_intake_recovery_proof_surface


class PublishRecoverySurfaceTests(unittest.TestCase):
    def test_default_recovery_surface_focuses_on_blocked_incident_recovery(self) -> None:
        payload = get_pressure_intake_recovery_proof_surface().to_dict()

        self.assertEqual(payload["surface_id"], "recovery-proof")
        self.assertEqual(payload["selected_card"]["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_action"], "restrict_publish")
        self.assertEqual(payload["recovery_window"]["blocked"], 2)
        signal_map = {signal["surface_id"]: signal for signal in payload["signals"]}
        self.assertEqual(signal_map["source_repair"]["behavior_type"], "source_fallback")
        self.assertEqual(signal_map["review_queue"]["status"], "blocked")
        self.assertIn("repair_source_chain", payload["continue_commands"])

    def test_recovery_surface_can_show_confirmed_frontline_shift(self) -> None:
        payload = get_pressure_intake_recovery_proof_surface("billing-verification-w25").to_dict()

        self.assertEqual(payload["selected_card"]["object_ref"], "billing-verification-w25")
        self.assertEqual(payload["recovery_window"]["confirmed"], 2)
        signal_map = {signal["surface_id"]: signal for signal in payload["signals"]}
        self.assertEqual(signal_map["queue-sidebar"]["status"], "confirmed")
        self.assertEqual(signal_map["feedback"]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
