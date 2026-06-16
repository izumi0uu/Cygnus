from __future__ import annotations

import unittest

from cygnus.recovery import (
    DownstreamRealityCheckQuery,
    build_downstream_reality_check,
    get_downstream_reality_check_surface,
    sample_reality_check_command_ref,
    sample_reality_check_feedback,
)


class RecoveryRealityCheckTests(unittest.TestCase):
    def test_build_downstream_reality_check_groups_feedback_by_command(self) -> None:
        surface = build_downstream_reality_check(
            command_ref=sample_reality_check_command_ref(),
            feedback_feed=sample_reality_check_feedback(),
        ).to_dict()

        self.assertEqual(surface["surface_id"], "downstream-reality-check")
        self.assertEqual(surface["reality_check_strip"]["command_id"], "cmd-publish-1")
        self.assertTrue(surface["reality_check_strip"]["frontline_changed"])
        self.assertIn("copilot", surface["reality_check_strip"]["converging_surfaces"])
        self.assertIn("macro", surface["reality_check_strip"]["lagging_surfaces"])
        self.assertIn("queue_sidebar", surface["reality_check_strip"]["lagging_surfaces"])
        self.assertEqual(surface["reality_check_strip"]["unresolved_signal_count"], 3)
        self.assertEqual(surface["feedback_feed"][0]["signal_id"], "sig-accepted-1")
        self.assertIn("object:ko-invoice-export-enterprise-eu", surface["upstream_object_links"])
        self.assertIn("return_to_command_brief", surface["send_back_commands"])

    def test_reality_check_rolls_up_mismatch_by_audience(self) -> None:
        surface = build_downstream_reality_check(
            command_ref=sample_reality_check_command_ref(),
            feedback_feed=sample_reality_check_feedback(),
        ).to_dict()
        audience_map = {
            item["audience_label"]: item for item in surface["mismatch_by_audience"]
        }

        enterprise_eu = audience_map["external · billing · enterprise · eu"]
        self.assertEqual(enterprise_eu["rewrite_count"], 1)
        self.assertEqual(enterprise_eu["reject_count"], 0)
        self.assertEqual(enterprise_eu["escalation_count"], 0)
        self.assertIn("macro", enterprise_eu["affected_surfaces"])

        free_us = audience_map["external · billing · free · us"]
        self.assertEqual(free_us["escalation_count"], 1)
        self.assertEqual(free_us["unresolved_count"], 1)
        self.assertIn("queue_sidebar", free_us["affected_surfaces"])

    def test_query_returns_surface_for_known_command(self) -> None:
        payload = get_downstream_reality_check_surface(
            DownstreamRealityCheckQuery(command_id="cmd-publish-1")
        ).to_dict()
        self.assertEqual(payload["reality_check_strip"]["command_type"], "publish")

    def test_query_raises_when_command_missing(self) -> None:
        with self.assertRaises(ValueError):
            get_downstream_reality_check_surface(
                DownstreamRealityCheckQuery(command_id="missing-command")
            )


if __name__ == "__main__":
    unittest.main()
