"""Explicit source freshness attestation rules for Cygnus governed truth.

Ownership:
- explicit freshness attestation fields, resolution, and the publish freshness
  gate live here
- no freshness is ever inferred from content, age, or timestamps; UNKNOWN is
  the default, and only an explicit FRESH attestation carrying actor, reason,
  attestation time, and a future expiry resolves to FRESH
- consumers (substrate projection, durable publish gate, session bridge,
  governed tool adapters) import these predicates instead of re-deriving
  freshness locally
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from cygnus.evidence.records import FreshnessState

if TYPE_CHECKING:
    pass

FRESHNESS_STATE_VALUES = frozenset(state.value for state in FreshnessState)

_MAX_REASON_LENGTH = 2000


def parse_freshness_state(
    value: object, *, label: str = "freshness_state"
) -> FreshnessState:
    """Strictly parse a persisted freshness state string."""
    if not isinstance(value, str) or value.strip() not in FRESHNESS_STATE_VALUES:
        raise ValueError(f"{label} must be one of: unknown, fresh, stale")
    return FreshnessState(value.strip())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value
    return None


def resolve_source_freshness(
    source: object, *, now: datetime | None = None
) -> FreshnessState:
    """Resolve one source's freshness from explicit attestation only.

    FRESH requires every attestation field:
      - freshness_state == "fresh"
      - freshness_actor_id (who attested)
      - freshness_reason (why)
      - freshness_attested_at (when, timezone-aware, after the last content
        change recorded in updated_at)
      - freshness_expires_at (expiry, timezone-aware, strictly in the future)

    Default, missing, partial, naive, or expired attestation never resolves to
    FRESH — it falls back to UNKNOWN so callers fail closed.
    """
    raw_state = getattr(source, "freshness_state", None)
    if raw_state is None:
        return FreshnessState.UNKNOWN
    try:
        state = parse_freshness_state(raw_state)
    except ValueError:
        return FreshnessState.UNKNOWN
    if state is not FreshnessState.FRESH:
        # Explicit STALE/UNKNOWN attestations resolve as recorded; they are
        # never upgraded to FRESH by anything in this module.
        return state

    actor_id = getattr(source, "freshness_actor_id", None)
    reason = getattr(source, "freshness_reason", None)
    attested_at = _aware(getattr(source, "freshness_attested_at", None))
    expires_at = _aware(getattr(source, "freshness_expires_at", None))
    if actor_id is None:
        return FreshnessState.UNKNOWN
    if not isinstance(reason, str) or not reason.strip():
        return FreshnessState.UNKNOWN
    if attested_at is None or expires_at is None:
        return FreshnessState.UNKNOWN

    current = now or _utcnow()
    if expires_at <= current:
        # Expired attestation is never fresh.
        return FreshnessState.UNKNOWN

    updated_at = _aware(getattr(source, "updated_at", None))
    if updated_at is not None and attested_at < updated_at:
        # Content changed after the attestation; the attestation no longer
        # covers the current bytes.
        return FreshnessState.UNKNOWN
    return FreshnessState.FRESH


def source_freshness_attestation(
    source: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Serializable attestation view for one source row (API/read surface)."""
    resolved = resolve_source_freshness(source, now=now)
    raw_state = getattr(source, "freshness_state", None)
    stored_fresh = raw_state == FreshnessState.FRESH.value
    actor_id = getattr(source, "freshness_actor_id", None)
    reason = getattr(source, "freshness_reason", None)
    attested_at = _aware(getattr(source, "freshness_attested_at", None))
    expires_at = _aware(getattr(source, "freshness_expires_at", None))
    return {
        "freshness_state": resolved.value,
        "freshness_active": resolved is FreshnessState.FRESH,
        "freshness_expired": stored_fresh and resolved is not FreshnessState.FRESH,
        "freshness_actor_id": str(actor_id) if actor_id is not None else None,
        "freshness_reason": reason,
        "freshness_attested_at": attested_at.isoformat()
        if attested_at is not None
        else None,
        "freshness_expires_at": expires_at.isoformat()
        if expires_at is not None
        else None,
    }


def validate_freshness_attestation(
    *,
    state: FreshnessState,
    reason: str,
    expires_at: datetime | None,
    now: datetime | None = None,
) -> None:
    """Validate one attestation command before persisting it."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("freshness reason must not be blank")
    if len(reason.strip()) > _MAX_REASON_LENGTH:
        raise ValueError(
            f"freshness reason must not exceed {_MAX_REASON_LENGTH} characters"
        )
    if state is FreshnessState.FRESH:
        if expires_at is None:
            raise ValueError("FRESH attestation requires an expiry timestamp")
        if expires_at.tzinfo is None:
            raise ValueError("freshness expiry must be timezone-aware")
        current = now or _utcnow()
        if expires_at <= current:
            raise ValueError("freshness expiry must be in the future")


def rollup_freshness(states: Iterable[FreshnessState]) -> FreshnessState:
    """Strict, inference-free aggregation of explicitly attested states.

    - any STALE evidence makes the object STALE
    - any UNKNOWN (or empty) evidence makes the object UNKNOWN
    - FRESH is only returned when every piece of evidence is explicitly FRESH
    """
    collected = tuple(states)
    if any(state is FreshnessState.STALE for state in collected):
        return FreshnessState.STALE
    if not collected or any(state is FreshnessState.UNKNOWN for state in collected):
        return FreshnessState.UNKNOWN
    return FreshnessState.FRESH


def _source_label(source: object) -> str:
    source_id = getattr(source, "id", None)
    title = getattr(source, "title", None)
    url = getattr(source, "url", None)
    if source_id is not None:
        return str(source_id)
    if title:
        return str(title)
    if url:
        return str(url)
    return "<source>"


@dataclass(frozen=True, slots=True)
class FreshnessGateResult:
    """Outcome of the durable publish freshness gate for linked sources."""

    passed: bool
    states: tuple[FreshnessState, ...]
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "states": [state.value for state in self.states],
            "violations": list(self.violations),
        }


def freshness_gate(
    sources: Iterable[object],
    *,
    now: datetime | None = None,
) -> FreshnessGateResult:
    """Publish gate: every linked required source must resolve FRESH.

    Any UNKNOWN, STALE, or expired source produces a named violation so the
    caller can deny publication with an actionable reason.
    """
    source_list = tuple(sources)
    states = tuple(resolve_source_freshness(source, now=now) for source in source_list)
    violations = tuple(
        f"source={_source_label(source)} freshness={state.value}"
        for source, state in zip(source_list, states)
        if state is not FreshnessState.FRESH
    )
    return FreshnessGateResult(
        passed=not violations,
        states=states,
        violations=violations,
    )
