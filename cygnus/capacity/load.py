"""Bounded load generation for the staging capacity gate.

The phase driver is bounded by construction: concurrency, duration, and
request counts come from the validated load profile (hard caps enforced in
``cygnus.capacity.schema``), the wall clock caps every worker loop, and
fault windows are scheduled mid-phase with a bounded post-restore sampling
window so recovery evidence is always observed before the phase ends.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence

from cygnus.capacity.inject import InjectionScenario, RecoveryEvidence
from cygnus.capacity.metrics import RouteSample, _required_float
from cygnus.capacity.schema import ROUTES, InjectionTarget, Outcome, RouteId
from cygnus.capacity.thresholds import RouteLoadProfile


class RouteTarget(Protocol):
    """One staging route surface the gate drives with bounded load."""

    async def execute(
        self,
    ) -> tuple[float, Outcome, float | None, float | None, float | None]:
        """Return (duration_ms, outcome, queue_age_seconds, pool_in_use, pool_size)."""

    def supports_injection(self, target: InjectionTarget) -> bool:
        """Whether this target can inject the requested fault on this deployment."""
        return False

    async def enable_failure(self, target: InjectionTarget) -> None:
        """Enable a bounded fault on the target's dependency."""

    async def disable_failure(self, target: InjectionTarget) -> None:
        """Restore the dependency; recovery observation starts here."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PhaseResult:
    """Measured phase for one route; the replayable unit of evidence."""

    route: RouteId
    wall_seconds: float
    samples: tuple[RouteSample, ...]
    recovery: RecoveryEvidence | None = None

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise ValueError(f"unknown route: {self.route}")
        if self.wall_seconds <= 0:
            raise ValueError("wall_seconds must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "route": self.route,
            "wall_seconds": round(self.wall_seconds, 6),
            "samples": [sample.to_dict() for sample in self.samples],
            "recovery": self.recovery.to_dict() if self.recovery is not None else None,
        }


def phase_result_from_dict(raw: Mapping[str, object]) -> PhaseResult:
    try:
        route_raw = raw["route"]
        if not isinstance(route_raw, str) or route_raw not in ROUTES:
            raise ValueError(f"invalid route: {route_raw!r}")
        wall_seconds = _required_float(raw, "wall_seconds")
        sample_raw = raw["samples"]
        if not isinstance(sample_raw, Sequence):
            raise ValueError("samples must be a list")
        sample_items: list[RouteSample] = []
        for item in sample_raw:
            if not isinstance(item, dict):
                raise ValueError("samples must be a list of objects")
            sample_items.append(RouteSample.from_dict(item))
        recovery_raw = raw.get("recovery")
        recovery = (
            RecoveryEvidence.from_dict(recovery_raw)
            if isinstance(recovery_raw, dict)
            else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid phase record: {exc}") from exc
    return PhaseResult(
        route=route_raw,
        wall_seconds=wall_seconds,
        samples=tuple(sample_items),
        recovery=recovery,
    )


async def _sleep_until(target_time: float, clock: Callable[[], float]) -> None:
    delay = target_time - clock()
    if delay > 0:
        await asyncio.sleep(delay)


async def run_route_phase(
    *,
    route: RouteId,
    target: RouteTarget,
    profile: RouteLoadProfile,
    scenario: InjectionScenario | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> PhaseResult:
    """Drive one route under bounded load, optionally through a fault window."""
    started = clock()
    deadline = started + profile.duration_seconds
    if scenario is not None:
        enable_at = started + profile.duration_seconds / 2.0
        disable_at = enable_at + scenario.duration_seconds
    else:
        enable_at = None
        disable_at = None

    samples: list[RouteSample] = []
    counter = 0
    lock = asyncio.Lock()
    failures_during_window = 0
    first_success_after_disable: float | None = None
    post_successes = 0
    post_errors = 0

    async def worker() -> None:
        nonlocal counter, failures_during_window, first_success_after_disable
        nonlocal post_successes, post_errors
        while True:
            now = clock()
            if now >= deadline:
                return
            async with lock:
                if counter >= profile.max_requests:
                    return
                counter += 1
            attempt_started = clock()
            try:
                (
                    duration_ms,
                    outcome,
                    queue_age,
                    pool_in_use,
                    pool_size,
                ) = await target.execute()
            except Exception:
                duration_ms = max((clock() - attempt_started) * 1000.0, 0.0)
                outcome, queue_age, pool_in_use, pool_size = (
                    "error",
                    None,
                    None,
                    None,
                )
            if disable_at is not None:
                if enable_at is not None and enable_at <= attempt_started < disable_at:
                    if outcome in ("error", "denied"):
                        failures_during_window += 1
                elif attempt_started >= disable_at:
                    if first_success_after_disable is None and outcome == "success":
                        first_success_after_disable = attempt_started - disable_at
                    if outcome == "success":
                        post_successes += 1
                    elif outcome in ("error", "denied"):
                        post_errors += 1
            samples.append(
                RouteSample(
                    started_at=attempt_started - started,
                    duration_ms=duration_ms,
                    outcome=outcome,
                    queue_age_seconds=queue_age,
                    pool_in_use=pool_in_use,
                    pool_size=pool_size,
                )
            )

    workers = [asyncio.create_task(worker()) for _ in range(profile.concurrency)]

    async def fault_scheduler(active: InjectionScenario) -> None:
        assert enable_at is not None and disable_at is not None
        await _sleep_until(enable_at, clock)
        await target.enable_failure(active.target)
        await _sleep_until(disable_at, clock)
        await target.disable_failure(active.target)

    fault_task: asyncio.Task[None] | None = None
    if scenario is not None:
        fault_task = asyncio.create_task(fault_scheduler(scenario))

    if fault_task is not None:
        await asyncio.gather(*workers, fault_task)
    else:
        await asyncio.gather(*workers)
    wall = clock() - started

    recovery: RecoveryEvidence | None = None
    if scenario is not None:
        post_total = post_successes + post_errors
        post_error_rate = post_errors / post_total if post_total else 0.0
        recovered = first_success_after_disable is not None and post_error_rate == 0.0
        if first_success_after_disable is not None:
            detail = (
                f"fault window {scenario.duration_seconds:g}s on {scenario.target}; "
                f"first success {first_success_after_disable:.3f}s after restore; "
                f"post-recovery error rate {post_error_rate:.3f}"
            )
        else:
            detail = (
                f"fault window {scenario.duration_seconds:g}s on {scenario.target}; "
                "no success observed after restore"
            )
        recovery = RecoveryEvidence(
            target=scenario.target,
            injected=True,
            window_seconds=scenario.duration_seconds,
            failures_during_window=failures_during_window,
            recovery_seconds=first_success_after_disable,
            post_recovery_error_rate=post_error_rate,
            recovered=recovered,
            detail=detail,
        )

    return PhaseResult(
        route=route,
        wall_seconds=wall,
        samples=tuple(samples),
        recovery=recovery,
    )
