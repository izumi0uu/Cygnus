from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.signals import (
    GovernanceSignalStatus,
    governance_signal_to_pressure_record,
    list_governance_signals,
)
from cygnus.review.intake import (
    PressureSignalType,
    compile_pressure_proposal_bundles,
)
from cygnus.review.service import ProposalBundle
from cygnus.runtime.database.models import Employee, GovernanceSignal


DRIFT_SIGNAL_TYPES = (
    PressureSignalType.RELEASE_DELTA,
    PressureSignalType.INCIDENT_DELTA,
)


@dataclass(frozen=True, slots=True)
class DriftSignalProviderResult:
    """Persisted drift rows plus explicit detector coverage."""

    signals: tuple[GovernanceSignal, ...]
    bundles: tuple[ProposalBundle, ...]
    covered_signals: tuple[str, ...] = (
        PressureSignalType.RELEASE_DELTA.value,
        PressureSignalType.INCIDENT_DELTA.value,
    )


async def load_drift_signal_provider(
    session: AsyncSession,
    *,
    current_user: Employee,
) -> DriftSignalProviderResult:
    signals = await list_governance_signals(
        session,
        current_user=current_user,
        status=GovernanceSignalStatus.ACTIVE,
        signal_types=DRIFT_SIGNAL_TYPES,
    )
    return DriftSignalProviderResult(
        signals=signals,
        bundles=compile_drift_signal_bundles(signals),
    )


def compile_drift_signal_bundles(
    signals: Iterable[GovernanceSignal],
) -> tuple[ProposalBundle, ...]:
    records = (
        governance_signal_to_pressure_record(signal)
        for signal in signals
        if signal.signal_type
        in {
            PressureSignalType.RELEASE_DELTA.value,
            PressureSignalType.INCIDENT_DELTA.value,
        }
    )
    return compile_pressure_proposal_bundles(records)
