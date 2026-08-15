from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from cygnus.evidence.freshness import (
    freshness_gate,
    parse_freshness_state,
    resolve_source_freshness,
    rollup_freshness,
    source_freshness_attestation,
    validate_freshness_attestation,
)
from cygnus.evidence.records import FreshnessState


def _utc(offset_days: float = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=offset_days)


class _FreshnessSource:
    """Duck-typed Source row carrying only the attestation surface."""

    def __init__(
        self,
        *,
        source_id: str = "src-1",
        freshness_state: str | None = "unknown",
        freshness_actor_id: object = None,
        freshness_reason: str | None = None,
        freshness_attested_at: datetime | None = None,
        freshness_expires_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = source_id
        self.freshness_state = freshness_state
        self.freshness_actor_id = freshness_actor_id
        self.freshness_reason = freshness_reason
        self.freshness_attested_at = freshness_attested_at
        self.freshness_expires_at = freshness_expires_at
        self.updated_at = updated_at


def _fresh_source(**kwargs) -> _FreshnessSource:
    defaults: dict[str, Any] = dict(
        source_id="src-fresh",
        freshness_state="fresh",
        freshness_actor_id="actor-1",
        freshness_reason="Verified against the 2026-08 release.",
        freshness_attested_at=_utc(-1),
        freshness_expires_at=_utc(30),
        updated_at=_utc(-2),
    )
    defaults.update(kwargs)
    return _FreshnessSource(**defaults)


class SourceFreshnessPredicateTests(unittest.TestCase):
    def test_default_and_missing_attestation_never_resolve_fresh(self) -> None:
        self.assertIs(
            resolve_source_freshness(_FreshnessSource(freshness_state="unknown")),
            FreshnessState.UNKNOWN,
        )
        self.assertIs(
            resolve_source_freshness(_FreshnessSource(freshness_state=None)),
            FreshnessState.UNKNOWN,
        )

    def test_explicit_stale_and_unknown_attestations_resolve_as_recorded(self) -> None:
        stale = _FreshnessSource(
            freshness_state="stale",
            freshness_reason="Retired guidance.",
            freshness_actor_id="actor-1",
            freshness_attested_at=_utc(-1),
        )
        self.assertIs(resolve_source_freshness(stale), FreshnessState.STALE)

        unknown = _FreshnessSource(
            freshness_state="unknown",
            freshness_reason="Attestation reset.",
            freshness_actor_id="actor-1",
            freshness_attested_at=_utc(-1),
        )
        self.assertIs(resolve_source_freshness(unknown), FreshnessState.UNKNOWN)

    def test_fresh_requires_full_attestation_envelope(self) -> None:
        cases = (
            dict(freshness_actor_id=None),
            dict(freshness_reason=None),
            dict(freshness_reason="   "),
            dict(freshness_attested_at=None),
            dict(freshness_expires_at=None),
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assertIs(
                    resolve_source_freshness(_fresh_source(**overrides)),
                    FreshnessState.UNKNOWN,
                )

    def test_expired_attestation_is_never_fresh(self) -> None:
        expired = _fresh_source(freshness_expires_at=_utc(-1))
        self.assertIs(resolve_source_freshness(expired), FreshnessState.UNKNOWN)
        self.assertTrue(source_freshness_attestation(expired)["freshness_expired"])

    def test_naive_timestamps_never_resolve_fresh(self) -> None:
        naive = _fresh_source(
            freshness_attested_at=datetime.now(),
            freshness_expires_at=datetime.now() + timedelta(days=30),
        )
        self.assertIs(resolve_source_freshness(naive), FreshnessState.UNKNOWN)

    def test_content_updated_after_attestation_invalidates_fresh(self) -> None:
        reingested = _fresh_source(
            freshness_attested_at=_utc(-1),
            updated_at=_utc(0),
        )
        self.assertIs(resolve_source_freshness(reingested), FreshnessState.UNKNOWN)

    def test_full_fresh_envelope_resolves_fresh(self) -> None:
        source = _fresh_source()
        self.assertIs(resolve_source_freshness(source), FreshnessState.FRESH)
        attestation = source_freshness_attestation(source)
        self.assertTrue(attestation["freshness_active"])
        self.assertFalse(attestation["freshness_expired"])
        self.assertEqual(attestation["freshness_state"], "fresh")
        self.assertEqual(attestation["freshness_actor_id"], "actor-1")
        self.assertEqual(
            attestation["freshness_reason"], "Verified against the 2026-08 release."
        )

    def test_freshness_gate_passes_only_when_every_source_is_fresh(self) -> None:
        fresh = _fresh_source()
        result = freshness_gate((fresh,))
        self.assertTrue(result.passed)
        self.assertEqual(result.violations, ())

        stale = _FreshnessSource(freshness_state="stale", freshness_reason="Old.")
        blocked = freshness_gate((fresh, stale))
        self.assertFalse(blocked.passed)
        self.assertEqual(len(blocked.violations), 1)
        self.assertIn("src-1", blocked.violations[0])
        self.assertIn("stale", blocked.violations[0])

    def test_rollup_never_infers_fresh_from_unknown(self) -> None:
        self.assertIs(rollup_freshness(()), FreshnessState.UNKNOWN)
        self.assertIs(
            rollup_freshness((FreshnessState.UNKNOWN,)),
            FreshnessState.UNKNOWN,
        )
        self.assertIs(
            rollup_freshness((FreshnessState.FRESH, FreshnessState.UNKNOWN)),
            FreshnessState.UNKNOWN,
        )
        self.assertIs(
            rollup_freshness((FreshnessState.FRESH, FreshnessState.FRESH)),
            FreshnessState.FRESH,
        )
        self.assertIs(
            rollup_freshness((FreshnessState.FRESH, FreshnessState.STALE)),
            FreshnessState.STALE,
        )

    def test_attestation_validation_rules(self) -> None:
        with self.assertRaises(ValueError):
            validate_freshness_attestation(
                state=FreshnessState.FRESH,
                reason="  ",
                expires_at=_utc(30),
            )
        with self.assertRaises(ValueError):
            validate_freshness_attestation(
                state=FreshnessState.FRESH,
                reason="Verified.",
                expires_at=None,
            )
        with self.assertRaises(ValueError):
            validate_freshness_attestation(
                state=FreshnessState.FRESH,
                reason="Verified.",
                expires_at=_utc(-1),
            )
        # STALE/UNKNOWN attestations need no expiry.
        validate_freshness_attestation(
            state=FreshnessState.STALE,
            reason="Retired.",
            expires_at=None,
        )
        validate_freshness_attestation(
            state=FreshnessState.FRESH,
            reason="Verified.",
            expires_at=_utc(30),
        )

    def test_parse_freshness_state_rejects_unknown_values(self) -> None:
        self.assertIs(parse_freshness_state("fresh"), FreshnessState.FRESH)
        self.assertIs(parse_freshness_state("stale"), FreshnessState.STALE)
        self.assertIs(parse_freshness_state("unknown"), FreshnessState.UNKNOWN)
        with self.assertRaises(ValueError):
            parse_freshness_state("always-fresh")
        with self.assertRaises(ValueError):
            parse_freshness_state(None)


if __name__ == "__main__":
    unittest.main()
