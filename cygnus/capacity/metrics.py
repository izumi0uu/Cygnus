"""Deterministic capacity metrics: percentiles, throughput, rates, saturation.

All summaries are pure functions of the recorded samples, so a replayed
samples file always reproduces the exact same report (acceptance:
"reports are replayable"). Latency percentiles use nearest-rank, which is
stable and well-defined for any sample size.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Mapping, Sequence

from cygnus.capacity.schema import METRICS, MetricId, Outcome, OUTCOMES


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"invalid numeric value: {value!r}")
    return float(value)


def _required_float(raw: Mapping[str, object], key: str) -> float:
    """Extract one required numeric field from parsed JSON, validating its type."""
    value = raw[key]
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"invalid {key!r} value: {value!r}")
    return float(value)


def _required_int(raw: Mapping[str, object], key: str) -> int:
    """Extract one required integral field from parsed JSON, validating its type."""
    value = raw[key]
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"invalid {key!r} value: {value!r}")
    return int(value)


@dataclass(frozen=True, slots=True)
class RouteSample:
    """One completed load attempt against a route."""

    started_at: float
    duration_ms: float
    outcome: Outcome
    queue_age_seconds: float | None = None
    pool_in_use: float | None = None
    pool_size: float | None = None

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome: {self.outcome}")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        if self.pool_size is not None and self.pool_size <= 0:
            raise ValueError("pool_size must be positive when provided")
        if (self.pool_in_use is None) != (self.pool_size is None):
            raise ValueError("pool_in_use and pool_size must be provided together")

    def to_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "outcome": self.outcome,
            "queue_age_seconds": self.queue_age_seconds,
            "pool_in_use": self.pool_in_use,
            "pool_size": self.pool_size,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "RouteSample":
        try:
            outcome_raw = raw["outcome"]
            if not isinstance(outcome_raw, str) or outcome_raw not in OUTCOMES:
                raise ValueError(f"invalid outcome: {outcome_raw!r}")
            return cls(
                started_at=_required_float(raw, "started_at"),
                duration_ms=_required_float(raw, "duration_ms"),
                outcome=outcome_raw,
                queue_age_seconds=_optional_float(raw.get("queue_age_seconds")),
                pool_in_use=_optional_float(raw.get("pool_in_use")),
                pool_size=_optional_float(raw.get("pool_size")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid route sample: {exc}") from exc


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile over a sequence of values."""
    if not values:
        raise ValueError("cannot compute percentile of an empty sequence")
    ordered = sorted(values)
    rank = ceil(q / 100.0 * len(ordered))
    return ordered[min(rank, len(ordered)) - 1]


def _round3(value: float) -> float:
    return round(value, 3)


def _round6(value: float) -> float:
    return round(value, 6)


def _round3_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


@dataclass(frozen=True, slots=True)
class SummaryMetrics:
    """Computed metrics for one measured route phase."""

    samples: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_rps: float
    error_rate: float
    denial_rate: float
    retry_rate: float
    queue_age_seconds: float | None
    pool_saturation: float | None
    recovery_seconds: float | None = None

    def value_for(self, metric: MetricId) -> float | None:
        if metric not in METRICS:
            raise ValueError(f"unknown metric: {metric}")
        values: dict[str, float | None] = {
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "throughput_rps": self.throughput_rps,
            "error_rate": self.error_rate,
            "denial_rate": self.denial_rate,
            "retry_rate": self.retry_rate,
            "queue_age_seconds": self.queue_age_seconds,
            "pool_saturation": self.pool_saturation,
        }
        return values[metric]

    def to_dict(self) -> dict[str, object]:
        return {
            "samples": self.samples,
            "p50_ms": _round3(self.p50_ms),
            "p95_ms": _round3(self.p95_ms),
            "p99_ms": _round3(self.p99_ms),
            "throughput_rps": _round3(self.throughput_rps),
            "error_rate": _round6(self.error_rate),
            "denial_rate": _round6(self.denial_rate),
            "retry_rate": _round6(self.retry_rate),
            "queue_age_seconds": _round3_or_none(self.queue_age_seconds),
            "pool_saturation": _round3_or_none(self.pool_saturation),
            "recovery_seconds": _round3_or_none(self.recovery_seconds),
        }


def summarize_samples(
    samples: Sequence[RouteSample],
    *,
    wall_seconds: float | None = None,
    recovery_seconds: float | None = None,
) -> SummaryMetrics:
    """Summarize a phase's samples into the full measured metric set."""
    if not samples:
        raise ValueError("cannot summarize zero samples")
    durations = [sample.duration_ms for sample in samples]
    total = len(samples)
    error_rate = sum(sample.outcome == "error" for sample in samples) / total
    denial_rate = sum(sample.outcome == "denied" for sample in samples) / total
    retry_rate = sum(sample.outcome == "retry" for sample in samples) / total
    queue_ages = [
        sample.queue_age_seconds
        for sample in samples
        if sample.queue_age_seconds is not None
    ]
    saturations = [
        sample.pool_in_use / sample.pool_size
        for sample in samples
        if sample.pool_in_use is not None
        and sample.pool_size is not None
        and sample.pool_size > 0
    ]
    throughput = (
        total / wall_seconds if wall_seconds is not None and wall_seconds > 0 else 0.0
    )
    return SummaryMetrics(
        samples=total,
        p50_ms=percentile(durations, 50.0),
        p95_ms=percentile(durations, 95.0),
        p99_ms=percentile(durations, 99.0),
        throughput_rps=throughput,
        error_rate=error_rate,
        denial_rate=denial_rate,
        retry_rate=retry_rate,
        queue_age_seconds=_mean_or_none(queue_ages),
        pool_saturation=_mean_or_none(saturations),
        recovery_seconds=recovery_seconds,
    )


def _mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
