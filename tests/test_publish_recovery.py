from __future__ import annotations

import unittest
from typing import cast

from cygnus.recovery import get_pressure_intake_recovery_proof_surface


def _recovery_payload(selected_object_ref: str | None = None) -> dict[str, object]:
    return get_pressure_intake_recovery_proof_surface(selected_object_ref).to_dict()


def _signal_map(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    signals = cast(list[dict[str, object]], payload["signals"])
    return {cast(str, signal["surface_id"]): signal for signal in signals}


class PublishRecoverySurfaceTests(unittest.TestCase):
    def test_default_recovery_surface_focuses_on_blocked_incident_recovery(
        self,
    ) -> None:
        payload = _recovery_payload()

        self.assertEqual(payload["surface_id"], "recovery-proof")
        selected_card = cast(dict[str, object], payload["selected_card"])
        self.assertEqual(selected_card["object_ref"], "incident-sync-eu-billing")
        self.assertEqual(payload["selected_action"], "restrict_publish")
        recovery_window = cast(dict[str, object], payload["recovery_window"])
        self.assertEqual(recovery_window["blocked"], 2)
        signal_map = _signal_map(payload)
        self.assertEqual(
            signal_map["source_repair"]["behavior_type"], "source_fallback"
        )
        self.assertEqual(signal_map["review_queue"]["status"], "blocked")
        self.assertIn(
            "repair_source_chain",
            cast(list[str], payload["continue_commands"]),
        )

    def test_recovery_surface_can_show_confirmed_frontline_shift(self) -> None:
        payload = _recovery_payload("billing-verification-w25")

        selected_card = cast(dict[str, object], payload["selected_card"])
        self.assertEqual(selected_card["object_ref"], "billing-verification-w25")
        recovery_window = cast(dict[str, object], payload["recovery_window"])
        self.assertEqual(recovery_window["confirmed"], 2)
        signal_map = _signal_map(payload)
        self.assertEqual(signal_map["queue-sidebar"]["status"], "confirmed")
        self.assertEqual(signal_map["feedback"]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
