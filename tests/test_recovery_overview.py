from __future__ import annotations

import unittest

from cygnus.recovery import (
    GovernanceOverviewQuery,
    build_governance_overview,
    get_governance_overview_surface,
    sample_all_recovery_residual_risks,
    sample_recovery_command_refs,
)
from cygnus.recovery.query import get_recovery_window_surface, RecoveryWindowQuery


class RecoveryOverviewTests(unittest.TestCase):
    def test_build_governance_overview_returns_multi_loop_comparison(self) -> None:
        command_refs = sample_recovery_command_refs()
        windows = tuple(
            get_recovery_window_surface(
                RecoveryWindowQuery(command_id=command_ref.command_id)
            )
            for command_ref in command_refs
        )
        surface = build_governance_overview(
            command_refs=command_refs,
            recovery_windows=windows,
            residual_risks=sample_all_recovery_residual_risks(),
        ).to_dict()

        self.assertEqual(surface["surface_id"], "governance-overview")
        self.assertEqual(len(surface["open_loops"]), 2)
        self.assertEqual(surface["highest_leverage_command"], "cmd-restrict-2")
        self.assertEqual(surface["open_loops"][0]["command_id"], "cmd-restrict-2")
        self.assertEqual(surface["open_loops"][0]["pending_propagation_count"], 2)
        self.assertIn("split_refund_contract_variant", surface["next_command_ribbon"])

    def test_query_returns_surface_for_known_command_ids(self) -> None:
        payload = get_governance_overview_surface(
            GovernanceOverviewQuery(command_ids=("cmd-publish-1", "cmd-restrict-2"))
        ).to_dict()
        self.assertEqual(payload["open_loop_ranks"][0]["command_id"], "cmd-restrict-2")
        self.assertEqual(payload["open_loop_ranks"][1]["command_id"], "cmd-publish-1")
        self.assertEqual(payload["open_loop_ranks"][0]["pending_propagation_count"], 2)

    def test_query_raises_when_command_ids_missing(self) -> None:
        with self.assertRaises(ValueError):
            get_governance_overview_surface(
                GovernanceOverviewQuery(command_ids=("missing-command",))
            )


if __name__ == "__main__":
    unittest.main()
