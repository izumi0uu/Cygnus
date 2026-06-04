from __future__ import annotations

import unittest

from cygnus.domain.lifecycle import (
    LifecycleState,
    allowed_transitions,
    assert_transition,
    can_transition,
    transition,
)


class LifecycleTests(unittest.TestCase):
    def test_expected_publish_path_is_allowed(self) -> None:
        state = LifecycleState.DRAFT
        state = transition(state, LifecycleState.IN_REVIEW)
        state = transition(state, LifecycleState.APPROVED)
        state = transition(state, LifecycleState.PUBLISHED)

        self.assertEqual(state, LifecycleState.PUBLISHED)

    def test_illegal_transition_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_transition(LifecycleState.PUBLISHED, LifecycleState.DRAFT)

    def test_can_transition_matches_allowed_targets(self) -> None:
        self.assertTrue(can_transition(LifecycleState.APPROVED, LifecycleState.PUBLISHED))
        self.assertFalse(
            can_transition(LifecycleState.SUPERSEDED, LifecycleState.PUBLISHED)
        )
        self.assertEqual(
            allowed_transitions(LifecycleState.DRAFT),
            (LifecycleState.ARCHIVED, LifecycleState.IN_REVIEW),
        )


if __name__ == "__main__":
    unittest.main()
